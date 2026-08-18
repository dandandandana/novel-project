from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .chunking import chunk_text
from .config import DEFAULT_SEARCH_STATUSES
from .documents import RagDocument, metadata_json


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
        with self.connect() as connection:
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
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [SearchResult(
            document_id=row["document_id"], title=row["title"], document_type=row["document_type"],
            status=row["status"], source_file=row["source_file"], score=-float(row["rank"]),
            content=row["content"], metadata=json.loads(row["metadata_json"]),
        ) for row in rows]
