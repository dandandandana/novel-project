"""SQLite schema and capability probes for graph projections."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

from .types import GraphBuildError, GraphReadError


SCHEMA_VERSION = "graph-v1"
SHARED_SCHEMA_VERSION = "shared-v1"

GRAPH_TABLES = frozenset(
    {
        "graph_manifest",
        "documents",
        "entities",
        "aliases",
        "document_entities",
        "relations",
        "summaries",
        "chunks_fts",
    }
)
SHARED_TABLES = frozenset(
    {
        "shared_manifest",
        "documents",
        "module_references",
        "chunks_fts",
    }
)


GRAPH_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE graph_manifest (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  schema_version TEXT NOT NULL,
  story_id TEXT NOT NULL,
  timeline_id TEXT NOT NULL,
  source_fingerprint TEXT NOT NULL,
  shared_manifest_fingerprint TEXT,
  module_references_json TEXT NOT NULL,
  built_at TEXT NOT NULL,
  document_count INTEGER NOT NULL CHECK (document_count >= 0),
  entity_count INTEGER NOT NULL CHECK (entity_count >= 0),
  relation_count INTEGER NOT NULL CHECK (relation_count >= 0),
  source_root TEXT NOT NULL DEFAULT ''
);

CREATE TABLE documents (
  document_id TEXT PRIMARY KEY,
  source_file TEXT NOT NULL,
  story_id TEXT NOT NULL,
  timeline_id TEXT NOT NULL,
  document_type TEXT NOT NULL,
  status TEXT NOT NULL,
  version TEXT NOT NULL,
  title TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  content TEXT NOT NULL
);

CREATE TABLE entities (
  entity_id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE aliases (
  alias TEXT NOT NULL,
  entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
  normalized_alias TEXT NOT NULL,
  PRIMARY KEY (alias, entity_id)
);

CREATE TABLE document_entities (
  document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
  entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
  PRIMARY KEY (document_id, entity_id)
);

CREATE TABLE relations (
  relation_id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
  relation_type TEXT NOT NULL,
  object_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
  document_id TEXT REFERENCES documents(document_id) ON DELETE SET NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE summaries (
  document_id TEXT PRIMARY KEY REFERENCES documents(document_id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
  chunk_id UNINDEXED,
  document_id UNINDEXED,
  content,
  tokenize='trigram'
);

CREATE INDEX idx_documents_identity
  ON documents(story_id, timeline_id, document_type, status);
CREATE INDEX idx_aliases_normalized ON aliases(normalized_alias);
CREATE INDEX idx_relations_subject ON relations(subject_id, relation_type);
CREATE INDEX idx_relations_object ON relations(object_id, relation_type);
"""


SHARED_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE shared_manifest (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  schema_version TEXT NOT NULL,
  story_id TEXT NOT NULL,
  timeline_id TEXT NOT NULL,
  source_fingerprint TEXT NOT NULL,
  built_at TEXT NOT NULL,
  document_count INTEGER NOT NULL CHECK (document_count >= 0),
  module_reference_count INTEGER NOT NULL CHECK (module_reference_count >= 0),
  source_root TEXT NOT NULL DEFAULT ''
);

CREATE TABLE documents (
  document_id TEXT PRIMARY KEY,
  source_file TEXT NOT NULL,
  story_id TEXT NOT NULL,
  timeline_id TEXT NOT NULL,
  document_type TEXT NOT NULL,
  status TEXT NOT NULL,
  version TEXT NOT NULL,
  title TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  content TEXT NOT NULL
);

CREATE TABLE module_references (
  module_type TEXT NOT NULL,
  document_id TEXT NOT NULL,
  version TEXT NOT NULL DEFAULT '',
  source_file TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (module_type, document_id)
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
  chunk_id UNINDEXED,
  document_id UNINDEXED,
  content,
  tokenize='trigram'
);

CREATE INDEX idx_shared_documents_identity
  ON documents(story_id, timeline_id, document_type, status);
CREATE INDEX idx_module_references_document ON module_references(document_id);
"""


@dataclass(frozen=True)
class TrigramProbe:
    sqlite_version: str
    fts5: bool
    trigram: bool
    sample_matches: int


def probe_trigram(connection: sqlite3.Connection | None = None) -> bool:
    """Return whether this SQLite runtime supports a working FTS5 trigram.

    The probe creates a temporary virtual table and removes it before return.
    It tests an actual three-codepoint CJK lookup instead of only checking the
    SQLite version, because packaged SQLite builds can differ in extensions.
    """

    owns_connection = connection is None
    conn = connection or sqlite3.connect(":memory:")
    name = f"__novel_rag_trigram_probe_{uuid.uuid4().hex}"
    try:
        conn.execute(
            f"CREATE VIRTUAL TABLE temp.{name} USING fts5(content, tokenize='trigram')"
        )
        conn.execute(f"INSERT INTO temp.{name}(content) VALUES (?)", ("中文检索能力",))
        count = conn.execute(
            f"SELECT count(*) FROM temp.{name} WHERE {name} MATCH ?", ("中文检",)
        ).fetchone()[0]
        return int(count) > 0
    except sqlite3.Error:
        return False
    finally:
        try:
            conn.execute(f"DROP TABLE IF EXISTS temp.{name}")
        except sqlite3.Error:
            pass
        if owns_connection:
            conn.close()


def require_trigram() -> TrigramProbe:
    """Probe the runtime or raise a diagnostic graph error."""

    conn = sqlite3.connect(":memory:")
    try:
        try:
            conn.execute("CREATE VIRTUAL TABLE __fts5_probe USING fts5(content)")
            fts5 = True
        except sqlite3.Error:
            fts5 = False
        trigram = probe_trigram(conn) if fts5 else False
        sample_matches = 1 if trigram else 0
        probe = TrigramProbe(sqlite3.sqlite_version, fts5, trigram, sample_matches)
    finally:
        conn.close()
    if not probe.fts5 or not probe.trigram:
        raise GraphBuildError(
            "当前 SQLite 缺少可用的 FTS5 trigram；请在安装阶段升级 SQLite，"
            "不会静默降级 tokenizer"
        )
    return probe


def create_schema(connection: sqlite3.Connection, *, shared: bool = False) -> None:
    """Create a new graph schema on a writable connection."""

    require_trigram()
    connection.executescript(SHARED_SCHEMA if shared else GRAPH_SCHEMA)


def _objects(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }


def verify_schema(connection: sqlite3.Connection, *, shared: bool = False) -> None:
    """Validate required tables and the FTS tokenizer on an open DB."""

    required = SHARED_TABLES if shared else GRAPH_TABLES
    missing = sorted(required - _objects(connection))
    if missing:
        error = GraphReadError(f"图 schema 缺少表: {', '.join(missing)}")
        raise error
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name='chunks_fts'"
    ).fetchone()
    sql = str(row[0] if row else "").lower()
    if "tokenize='trigram'" not in sql and 'tokenize = \'trigram\'' not in sql:
        raise GraphReadError("图 chunks_fts 未使用 trigram tokenizer")


def verify_integrity(connection: sqlite3.Connection) -> None:
    """Run SQLite integrity and foreign-key checks on a staged projection."""

    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    result = str(integrity[0] if integrity else "")
    if result.lower() != "ok":
        raise GraphReadError(f"SQLite integrity_check 失败: {result or '无结果'}")
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        details = "; ".join(",".join(str(value) for value in row) for row in violations[:5])
        raise GraphReadError(f"SQLite foreign_key_check 失败: {details}")


def manifest_schema_version(*, shared: bool = False) -> str:
    return SHARED_SCHEMA_VERSION if shared else SCHEMA_VERSION
