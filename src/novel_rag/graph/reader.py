"""Read-only graph reader with manifest and freshness validation."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .fingerprint import database_fingerprint, graph_corpus_fingerprint
from .schema import SCHEMA_VERSION, probe_trigram, verify_integrity, verify_schema
from .types import (
    DocumentHit,
    EntityResolution,
    GraphKey,
    GraphManifest,
    GraphReadError,
    RelationHit,
    coerce_graph_key,
)


def read_only_uri(path: Path) -> str:
    """Return a SQLite URI that cannot create or mutate the target file."""

    return f"file:{quote(path.resolve().as_posix(), safe='/:')}?mode=ro"


def open_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise GraphReadError(f"图文件不存在: {path}")
    try:
        connection = sqlite3.connect(read_only_uri(path), uri=True)
        connection.row_factory = sqlite3.Row
        return connection
    except sqlite3.Error as exc:
        raise GraphReadError(f"无法只读打开图: {path}: {exc}") from exc


def _key_from_canonical_path(path: Path) -> GraphKey | None:
    candidate = Path(path).resolve()
    if candidate.name == "shared.db":
        return GraphKey.shared()
    if candidate.suffix != ".db" or candidate.parent.parent.name != "graphs":
        return None
    try:
        return GraphKey(candidate.parent.name, candidate.stem)
    except ValueError:
        return None


def _fts_match_expression(query: str) -> tuple[str, tuple[str, ...]]:
    """Split a raw query into a trigram MATCH expression and short terms.

    The trigram tokenizer cannot represent tokens shorter than three
    characters, so such terms would silently match nothing.  They are
    returned separately for exact-substring probing by ``search``.
    """

    long_terms: list[str] = []
    short_terms: list[str] = []
    for term in str(query or "").split():
        cleaned = term.replace('"', '""')
        if len(term) < 3:
            short_terms.append(term)
        else:
            long_terms.append(f'"{cleaned}"')
    return " ".join(long_terms), tuple(short_terms)


def _like_substring_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_documents(
    connection: sqlite3.Connection,
    query: str,
    *,
    limit: int,
) -> list[DocumentHit]:
    """Shared chunks_fts document search used by every graph reader.

    Long terms run through a ranked trigram MATCH; short CJK terms cannot
    produce trigram tokens and are probed as exact substrings instead.  The
    merged order is MATCH ranking first, then short-term hits by document_id.
    """

    value = str(query or "").strip()
    if not value:
        raise ValueError("query 不能为空")
    match_expression, short_terms = _fts_match_expression(value)
    hits: dict[str, DocumentHit] = {}
    if match_expression:
        rows = connection.execute(
            """SELECT d.* FROM chunks_fts f
               JOIN documents d ON d.document_id = f.document_id
               WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?""",
            (match_expression, int(limit)),
        ).fetchall()
        for row in rows:
            hit = _document_hit(row)
            hits[hit.document_id] = hit
    for term in short_terms:
        rows = connection.execute(
            """SELECT d.* FROM chunks_fts f
               JOIN documents d ON d.document_id = f.document_id
               WHERE f.content LIKE ? ESCAPE '\\'
               ORDER BY d.document_id LIMIT ?""",
            (_like_substring_pattern(term), int(limit)),
        ).fetchall()
        for row in rows:
            hit = _document_hit(row)
            hits.setdefault(hit.document_id, hit)
    return list(hits.values())


def ensure_reader_freshness(
    *,
    subject: str,
    connection: sqlite3.Connection,
    manifest_fingerprint: str,
    expected_fingerprint: str | None,
    source_root: str | None,
    graph_key: GraphKey | None = None,
) -> bool:
    """依赖：源指纹与可选预验指纹。输入：图连接、清单与可选目标身份。输出：通过或只读错误。实现：复核已登记源及边界，纯平铺源不可读时要求预验指纹。

    Returns ``True`` once freshness is proven.  Raises when the recomputed
    database fingerprint diverges from the manifest (stale) or when no proof
    is possible because neither an expected fingerprint nor source files are
    available.
    """

    current = database_fingerprint(
        connection,
        source_root=Path(source_root) if source_root else None,
        graph_key=graph_key,
    )
    if current is None:
        if expected_fingerprint is None:
            raise GraphReadError(
                f"无法证明{subject}的新鲜度；必须提供 expected_fingerprint 或 scoped corpus"
            )
        return True
    if current != manifest_fingerprint:
        raise GraphReadError(f"{subject} source_fingerprint 与当前 YAML 不一致，图已 stale")
    return True


class _SQLiteReaderLifecycle:
    """Shared close/context-manager behaviour for read-only SQLite readers."""

    _connection: sqlite3.Connection | None

    def close(self) -> None:
        connection = getattr(self, "_connection", None)
        if connection is not None:
            self._connection = None
            connection.close()

    def __enter__(self) -> Any:
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class GraphReader(_SQLiteReaderLifecycle):
    """Read one complete story/timeline projection through SQLite ``mode=ro``."""

    @classmethod
    def from_corpus(cls, path: Path, key: GraphKey, corpus: Any, **kwargs: Any) -> "GraphReader":
        """Open a graph with canonical identity and scoped freshness proof."""

        return cls(path, expected_key=key, corpus=corpus, **kwargs)

    open = from_corpus

    def __init__(
        self,
        path: Path,
        *,
        expected_key: Any | None = None,
        expected_fingerprint: str | None = None,
        expected_source_fingerprint: str | None = None,
        corpus: Any | None = None,
        expected_shared_manifest_fingerprint: str | None = None,
    ) -> None:
        self.path = Path(path)
        inferred_key = _key_from_canonical_path(self.path)
        if expected_key is None:
            expected_key = inferred_key
        if expected_key is None:
            raise GraphReadError(
                "GraphReader 必须提供 canonical expected_key，或使用 canonical 图路径"
            )
        self._expected_key = coerce_graph_key(expected_key)
        if inferred_key is not None and inferred_key != self._expected_key:
            raise GraphReadError(
                "图物理路径与 expected GraphKey 不一致: "
                f"{inferred_key.as_dict()} != {self._expected_key.as_dict()}"
            )
        if expected_source_fingerprint is not None:
            if expected_fingerprint is not None and expected_fingerprint != expected_source_fingerprint:
                raise GraphReadError("expected_fingerprint 与 expected_source_fingerprint 冲突")
            expected_fingerprint = expected_source_fingerprint
        self._validated_corpus = corpus
        self._freshness_checked = False
        if corpus is not None:
            try:
                corpus_fingerprint = graph_corpus_fingerprint(corpus, self._expected_key)
            except Exception as exc:
                raise GraphReadError(f"无法计算 scoped corpus fingerprint: {exc}") from exc
            if expected_fingerprint is not None and expected_fingerprint != corpus_fingerprint:
                raise GraphReadError("expected_fingerprint 与 scoped corpus 不一致")
            expected_fingerprint = corpus_fingerprint
            # The scoped corpus fingerprint is already a current-source proof.
            self._freshness_checked = True
        self._expected_fingerprint = expected_fingerprint
        self._connection = open_read_only(self.path)
        try:
            verify_schema(self._connection)
            verify_integrity(self._connection)
            if not probe_trigram():
                raise GraphReadError("当前 SQLite 缺少可用的 FTS5 trigram")
            self._manifest = self._load_manifest()
            if self._manifest.schema_version != SCHEMA_VERSION:
                raise GraphReadError(
                    f"图 schema_version 不受支持: {self._manifest.schema_version!r}"
                )
            if not self._manifest.source_fingerprint.startswith("sha256:"):
                raise GraphReadError("graph_manifest source_fingerprint 必须是 sha256")
            try:
                manifest_key = GraphKey(self._manifest.story_id, self._manifest.timeline_id)
            except ValueError as exc:
                raise GraphReadError(f"graph_manifest 身份无效: {exc}") from exc
            if manifest_key != self._expected_key:
                raise GraphReadError(
                    "图身份与 GraphKey 不一致: "
                    f"{manifest_key.as_dict()} != {self._expected_key.as_dict()}"
                )
            if self._expected_fingerprint is not None and self._manifest.source_fingerprint != self._expected_fingerprint:
                raise GraphReadError("图 source_fingerprint 不匹配，图已过期")
            if (
                expected_shared_manifest_fingerprint is not None
                and self._manifest.shared_manifest_fingerprint != expected_shared_manifest_fingerprint
            ):
                raise GraphReadError("图 shared_manifest_fingerprint 不匹配，图已过期")
            self._ensure_fresh()
        except Exception:
            self.close()
            raise

    def _load_manifest(self) -> GraphManifest:
        row = self._connection.execute(
            "SELECT * FROM graph_manifest WHERE id = 1"
        ).fetchone()
        if row is None:
            raise GraphReadError("图缺少唯一 graph_manifest")
        try:
            references = json.loads(str(row["module_references_json"]))
            if not isinstance(references, list) or not all(
                isinstance(item, dict) for item in references
            ):
                raise ValueError("module_references_json 必须是列表")
            return GraphManifest(
                schema_version=str(row["schema_version"]),
                story_id=str(row["story_id"]),
                timeline_id=str(row["timeline_id"]),
                source_fingerprint=str(row["source_fingerprint"]),
                shared_manifest_fingerprint=(
                    str(row["shared_manifest_fingerprint"])
                    if row["shared_manifest_fingerprint"] is not None
                    else None
                ),
                module_references=tuple(references),
                built_at=str(row["built_at"]),
                document_count=int(row["document_count"]),
                entity_count=int(row["entity_count"]),
                relation_count=int(row["relation_count"]),
                source_root=(
                    str(row["source_root"])
                    if "source_root" in row.keys() and row["source_root"]
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GraphReadError(f"graph_manifest 内容无效: {exc}") from exc

    def manifest(self) -> GraphManifest:
        self._ensure_fresh()
        return self._manifest

    def _ensure_fresh(self) -> None:
        """依赖：当前连接、图键和源指纹。输入：已打开的 reader。输出：无或 GraphReadError。实现：首次查询时验证来源及归属，已验证的 reader 复用结果。"""
        if self._connection is None:
            raise GraphReadError("GraphReader 已关闭")
        if self._freshness_checked:
            return
        self._freshness_checked = ensure_reader_freshness(
            subject="图",
            connection=self._connection,
            manifest_fingerprint=self._manifest.source_fingerprint,
            expected_fingerprint=self._expected_fingerprint,
            source_root=self._manifest.source_root,
            graph_key=self._expected_key,
        )

    @property
    def connection(self) -> sqlite3.Connection:
        """Expose the validated read-only connection for diagnostics only."""

        if self._connection is None:
            raise GraphReadError("GraphReader 已关闭")
        self._ensure_fresh()
        return self._connection

    def is_fresh(self, corpus: Any) -> bool:
        try:
            return self._manifest.source_fingerprint == graph_corpus_fingerprint(
                corpus,
                self._expected_key,
            )
        except (GraphReadError, ValueError):
            return False

    def assert_fresh(self, corpus: Any) -> None:
        self._ensure_fresh()
        if corpus is not None and corpus is self._validated_corpus:
            return
        if not self.is_fresh(corpus):
            raise GraphReadError("图 source_fingerprint 与当前 YAML 不一致，图已 stale；请重新建图")

    def resolve_aliases(self, text: str) -> EntityResolution:
        self._ensure_fresh()
        value = str(text or "").strip()
        if not value:
            return EntityResolution(value, ())
        rows = self._connection.execute(
            """SELECT alias, entity_id, normalized_alias
               FROM aliases
               WHERE alias = ? OR normalized_alias = ?
               ORDER BY length(alias) DESC, alias""",
            (value, value.casefold()),
        ).fetchall()
        matches = tuple(dict(row) for row in rows)
        entity_ids = tuple(dict.fromkeys(str(row["entity_id"]) for row in rows))
        return EntityResolution(value, entity_ids, matches)

    def neighbors(
        self,
        entity_ids: set[str],
        relation_types: set[str],
        max_hops: int = 1,
    ) -> list[RelationHit]:
        self._ensure_fresh()
        if not entity_ids or max_hops <= 0:
            return []
        frontier = set(str(item) for item in entity_ids)
        seen_entities = set(frontier)
        hits: dict[str, RelationHit] = {}
        for _ in range(max_hops):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            params: list[Any] = [*sorted(frontier)]
            clauses = [f"(subject_id IN ({placeholders}) OR object_id IN ({placeholders}))"]
            params.extend(sorted(frontier))
            if relation_types:
                type_placeholders = ",".join("?" for _ in relation_types)
                clauses.append(f"relation_type IN ({type_placeholders})")
                params.extend(sorted(relation_types))
            rows = self._connection.execute(
                "SELECT * FROM relations WHERE " + " AND ".join(clauses), params
            ).fetchall()
            next_frontier: set[str] = set()
            for row in rows:
                relation = RelationHit(
                    relation_id=str(row["relation_id"]),
                    subject_id=str(row["subject_id"]),
                    relation_type=str(row["relation_type"]),
                    object_id=str(row["object_id"]),
                    document_id=(str(row["document_id"]) if row["document_id"] is not None else None),
                    metadata=json.loads(str(row["metadata_json"] or "{}")),
                )
                hits[relation.relation_id] = relation
                next_frontier.update({relation.subject_id, relation.object_id})
            frontier = next_frontier - seen_entities
            seen_entities.update(next_frontier)
        return list(hits.values())

    def documents_for_entities(
        self,
        entity_ids: set[str],
        document_types: set[str] | None = None,
    ) -> list[DocumentHit]:
        self._ensure_fresh()
        if not entity_ids:
            return []
        entity_placeholders = ",".join("?" for _ in entity_ids)
        params: list[Any] = sorted(entity_ids)
        clauses = [f"de.entity_id IN ({entity_placeholders})"]
        if document_types:
            type_placeholders = ",".join("?" for _ in document_types)
            clauses.append(f"d.document_type IN ({type_placeholders})")
            params.extend(sorted(document_types))
        rows = self._connection.execute(
            """SELECT DISTINCT d.* FROM documents d
               JOIN document_entities de ON de.document_id = d.document_id
               WHERE """ + " AND ".join(clauses) + " ORDER BY d.document_id",
            params,
        ).fetchall()
        return [_document_hit(row) for row in rows]

    def search(self, query: str, *, limit: int = 6) -> list[DocumentHit]:
        self._ensure_fresh()
        return search_documents(self._connection, query, limit=limit)


def _document_hit(row: sqlite3.Row) -> DocumentHit:
    try:
        metadata = json.loads(str(row["metadata_json"] or "{}"))
    except json.JSONDecodeError:
        metadata = {}
    return DocumentHit(
        document_id=str(row["document_id"]),
        title=str(row["title"]),
        document_type=str(row["document_type"]),
        status=str(row["status"]),
        source_file=str(row["source_file"]),
        content=str(row["content"]),
        metadata=metadata if isinstance(metadata, dict) else {},
    )
