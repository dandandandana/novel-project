"""Migration façade for the pre-GraphKey index API.

Canonical projection and retrieval orchestration lives in
``novel_rag.composition``. This module keeps only the explicitly deprecated
SQLite adapter and argument-conversion shims needed by external callers while
legacy databases are retired. Remove this module's compatibility surface only
after a repository-wide scan finds no supported ``SqliteIndex``,
``search_isolated`` or ``rebuild_isolated_indexes`` callers and all
``index/stories/*.db`` files have been migrated to GraphKey projections.
"""

from __future__ import annotations

import json
import sqlite3
import warnings
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .chunking import chunk_text
from .composition import IndexBuildResult, SearchResult, search_graph
from .config import DEFAULT_SEARCH_STATUSES
from .documents import RagDocument, metadata_json
from .graph import GraphReadError
from .identity import GraphKey
from .layout import (
    SHARED_STORY_ID,
    SHARED_TIMELINE_ID,
    legacy_story_index_path,
    shared_index_path,
)


# This schema is migration-only. New builds must use GraphBuilder and never
# create a ``stories/<story>.db`` or unicode61 search index.
SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  document_id TEXT PRIMARY KEY, source_file TEXT NOT NULL, story_id TEXT NOT NULL,
  timeline_id TEXT NOT NULL, document_type TEXT NOT NULL, status TEXT NOT NULL,
  version TEXT NOT NULL, title TEXT NOT NULL, metadata_json TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
  chunk_id UNINDEXED, document_id UNINDEXED, content, tokenize='unicode61'
);
"""


def _legacy_read_only_uri(path: Path) -> str:
    return f"file:{quote(path.resolve().as_posix(), safe='/:')}?mode=ro"


class SqliteIndex:
    """Read/write adapter for one explicitly addressed legacy database.

    The adapter remains for migration fixtures and external compatibility only.
    Canonical CLI/TUI/service paths do not instantiate it; callers must choose
    the legacy API or ``--legacy`` explicitly.
    """

    def __init__(self, path: Path, *, _compat: bool = False):
        if not _compat:
            warnings.warn(
                "SqliteIndex 是迁移期兼容接口；请改用 GraphBuilder/GraphReader",
                DeprecationWarning,
                stacklevel=2,
            )
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        """Open a writable legacy connection for explicit rebuilds."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        return connection

    def _connect_read_only(self) -> sqlite3.Connection:
        if not self.path.is_file():
            raise FileNotFoundError(f"小说索引不存在，请先执行 index: {self.path}")
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(_legacy_read_only_uri(self.path), uri=True)
            connection.row_factory = sqlite3.Row
            table_rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
            tables = {str(row[0]) for row in table_rows}
            if not {"documents", "chunks"}.issubset(tables):
                connection.close()
                connection = None
                if "chunks_fts" in tables or "graph_manifest" in tables or "shared_manifest" in tables:
                    detail = (
                        "检测到 canonical GraphKey 图 schema；legacy 搜索不能读取该数据库"
                    )
                else:
                    detail = "数据库缺少 legacy 所需的 documents/chunks 表"
                raise GraphReadError(
                    f"旧索引 schema 不受支持: {self.path}；{detail}。"
                    "请使用默认 canonical search；若只需要旧小说索引，请显式传入"
                    " --legacy --no-shared，或提供独立的迁移期 legacy shared 数据库。"
                )
            return connection
        except GraphReadError:
            if connection is not None:
                connection.close()
            raise
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            raise GraphReadError(f"无法只读打开旧索引: {self.path}: {exc}") from exc

    def rebuild(self, documents: list[RagDocument]) -> tuple[int, int]:
        """Rebuild an explicitly requested legacy database."""

        connection = self.connect()
        try:
            with connection:
                connection.execute("DELETE FROM chunks")
                connection.execute("DELETE FROM documents")
                chunk_count = 0
                for document in documents:
                    metadata = document.metadata
                    connection.execute(
                        "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            document.document_id,
                            str(document.path),
                            str(metadata["story_id"]),
                            str(metadata["timeline_id"]),
                            str(metadata["document_type"]),
                            str(metadata["status"]),
                            str(metadata["version"]),
                            str(metadata["title"]),
                            metadata_json(metadata),
                        ),
                    )
                    for chunk in chunk_text(document.searchable_text()):
                        connection.execute(
                            "INSERT INTO chunks(chunk_id, document_id, content) VALUES (?, ?, ?)",
                            (f"{document.document_id}:{chunk.ordinal}", document.document_id, chunk.text),
                        )
                        chunk_count += 1
        finally:
            connection.close()
        return len(documents), chunk_count

    def search(
        self,
        query: str,
        story_id: str,
        timeline_id: str,
        *,
        document_types: list[str] | None = None,
        statuses: list[str] | None = None,
        limit: int = 6,
    ) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("query 不能为空")
        if limit <= 0:
            return []
        # Treat user input as literal terms instead of exposing FTS operators.
        # The legacy projection uses a unicode61 tokenizer, so short CJK
        # terms remain matchable here; this intentionally differs from the
        # trigram-based canonical readers.
        fts_query = " ".join(
            f'"{term.replace(chr(34), chr(34) * 2)}"' for term in query.split()
        )
        statuses = statuses or list(DEFAULT_SEARCH_STATUSES)
        clauses = ["chunks MATCH ?", "d.story_id = ?", "d.timeline_id = ?"]
        params: list[Any] = [fts_query, story_id, timeline_id]
        clauses.append(f"d.status IN ({','.join('?' for _ in statuses)})")
        params.extend(statuses)
        if document_types:
            clauses.append(f"d.document_type IN ({','.join('?' for _ in document_types)})")
            params.extend(document_types)
        params.append(limit)
        sql = f"""
          SELECT d.*, chunks.content, bm25(chunks) AS rank
          FROM chunks JOIN documents d ON d.document_id = chunks.document_id
          WHERE {' AND '.join(clauses)} ORDER BY rank LIMIT ?
        """
        connection = self._connect_read_only()
        try:
            rows = connection.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise GraphReadError(f"旧索引检索失败: {self.path}: {exc}") from exc
        finally:
            connection.close()
        return [
            SearchResult(
                document_id=row["document_id"],
                title=row["title"],
                document_type=row["document_type"],
                status=row["status"],
                source_file=row["source_file"],
                score=-float(row["rank"]),
                content=row["content"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]


def _search_legacy(
    index_directory: Path,
    query: str,
    story_id: str,
    timeline_id: str,
    *,
    document_types: list[str] | None,
    statuses: list[str] | None,
    limit: int,
    include_shared: bool,
) -> list[SearchResult]:
    """Read only legacy projections for the explicit migration boundary."""

    story_path = legacy_story_index_path(index_directory, story_id)
    if not story_path.exists():
        raise FileNotFoundError(f"小说索引不存在，请先执行 index: {story_path}")
    candidates = SqliteIndex(story_path, _compat=True).search(
        query,
        story_id,
        timeline_id,
        document_types=document_types,
        statuses=statuses,
        limit=limit,
    )
    if include_shared:
        shared_path = shared_index_path(index_directory)
        if not shared_path.exists():
            raise FileNotFoundError(f"共享系统索引不存在，请先执行 index: {shared_path}")
        candidates.extend(
            SqliteIndex(shared_path, _compat=True).search(
                query,
                SHARED_STORY_ID,
                SHARED_TIMELINE_ID,
                document_types=document_types,
                statuses=statuses,
                limit=limit,
            )
        )
    deduplicated: dict[str, SearchResult] = {}
    for item in candidates:
        previous = deduplicated.get(item.document_id)
        if previous is None or item.score > previous.score:
            deduplicated[item.document_id] = item
    return sorted(deduplicated.values(), key=lambda item: item.score, reverse=True)[:limit]


def rebuild_isolated_indexes(
    index_directory: Path,
    documents: list[RagDocument],
    story_ids: list[str],
    *,
    story_id: str | None = None,
    timeline_id: str | None = None,
    shared_only: bool = False,
    library_root: Path | None = None,
    timeline_registry: Any | None = None,
    prune_stale: bool = True,
) -> list[IndexBuildResult]:
    """Deprecated argument-conversion shim for canonical graph builds."""

    warnings.warn(
        "rebuild_isolated_indexes 是迁移期兼容接口；新代码应调用 composition.rebuild_graph_projections",
        DeprecationWarning,
        stacklevel=2,
    )
    from .composition import rebuild_graph_projections

    return rebuild_graph_projections(
        index_directory,
        documents,
        story_ids,
        story_id=story_id,
        timeline_id=timeline_id,
        shared_only=shared_only,
        library_root=library_root,
        timeline_registry=timeline_registry,
        prune_stale=prune_stale,
    )


def search_isolated(
    index_directory: Path,
    query: str,
    story_id: str,
    timeline_id: str,
    *,
    document_types: list[str] | None = None,
    statuses: list[str] | None = None,
    limit: int = 6,
    include_shared: bool = True,
    library_root: Path | None = None,
    legacy: bool = False,
) -> list[SearchResult]:
    """Deprecated search shim; only ``legacy=True`` reads old databases."""

    warnings.warn(
        "search_isolated 是迁移期兼容接口；新代码应注入 Retriever",
        DeprecationWarning,
        stacklevel=2,
    )
    if not query.strip():
        raise ValueError("query 不能为空")
    return search_graph(
        Path(index_directory).resolve(),
        query,
        GraphKey(story_id, timeline_id),
        document_types=document_types,
        statuses=statuses,
        limit=limit,
        include_shared=include_shared,
        library_root=Path(library_root).resolve() if library_root is not None else None,
        legacy=legacy,
    )


__all__ = [
    "IndexBuildResult",
    "SCHEMA",
    "SearchResult",
    "SqliteIndex",
    "rebuild_isolated_indexes",
    "search_isolated",
]
