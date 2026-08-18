from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .chunking import chunk_text
from .config import DEFAULT_SEARCH_STATUSES
from .documents import RagDocument, metadata_json
from .layout import SHARED_STORY_ID, SHARED_TIMELINE_ID, shared_index_path, story_index_path


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


@dataclass(frozen=True)
class SearchResult:
    document_id: str
    title: str
    document_type: str
    status: str
    source_file: str
    score: float
    content: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class IndexBuildResult:
    scope: str
    path: Path
    document_count: int
    chunk_count: int


class SqliteIndex:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        return connection

    def rebuild(self, documents: list[RagDocument]) -> tuple[int, int]:
        connection = self.connect()
        try:
            with connection:
                connection.execute("DELETE FROM chunks")
                connection.execute("DELETE FROM documents")
                chunk_count = 0
                for document in documents:
                    m = document.metadata
                    connection.execute(
                        "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (document.document_id, str(document.path), str(m["story_id"]), str(m["timeline_id"]),
                         str(m["document_type"]), str(m["status"]), str(m["version"]), str(m["title"]), metadata_json(m)),
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

    def search(self, query: str, story_id: str, timeline_id: str, *, document_types: list[str] | None = None,
               statuses: list[str] | None = None, limit: int = 6) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("query 不能为空")
        # Treat CLI input as literal terms instead of exposing FTS5 operators.
        query = " ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in query.split())
        statuses = statuses or list(DEFAULT_SEARCH_STATUSES)
        clauses = ["chunks MATCH ?", "d.story_id = ?", "d.timeline_id = ?"]
        params: list[Any] = [query, story_id, timeline_id]
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
        connection = self.connect()
        try:
            rows = connection.execute(sql, params).fetchall()
        finally:
            connection.close()
        return [SearchResult(
            document_id=row["document_id"], title=row["title"], document_type=row["document_type"],
            status=row["status"], source_file=row["source_file"], score=-float(row["rank"]),
            content=row["content"], metadata=json.loads(row["metadata_json"]),
        ) for row in rows]


def rebuild_isolated_indexes(
    index_directory: Path,
    documents: list[RagDocument],
    story_ids: list[str],
) -> list[IndexBuildResult]:
    story_directory = index_directory / "stories"
    story_directory.mkdir(parents=True, exist_ok=True)
    expected_story_paths = {story_index_path(index_directory, story_id).resolve() for story_id in story_ids}
    for stale_path in story_directory.glob("*.db"):
        if stale_path.resolve() not in expected_story_paths:
            stale_path.unlink()
    shared_documents = [
        document for document in documents if document.metadata.get("story_id") == SHARED_STORY_ID
    ]
    results: list[IndexBuildResult] = []
    shared_path = shared_index_path(index_directory)
    document_count, chunk_count = SqliteIndex(shared_path).rebuild(shared_documents)
    results.append(IndexBuildResult("shared", shared_path, document_count, chunk_count))
    for story_id in story_ids:
        story_documents = [
            document for document in documents if document.metadata.get("story_id") == story_id
        ]
        path = story_index_path(index_directory, story_id)
        document_count, chunk_count = SqliteIndex(path).rebuild(story_documents)
        results.append(IndexBuildResult(story_id, path, document_count, chunk_count))
    return results


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
) -> list[SearchResult]:
    story_path = story_index_path(index_directory, story_id)
    if not story_path.exists():
        raise FileNotFoundError(f"小说索引不存在，请先执行 index: {story_path}")
    candidates = SqliteIndex(story_path).search(
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
            SqliteIndex(shared_path).search(
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
