"""Catalog-owned source fingerprints used by graph manifests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..catalog import ValidatedCorpus
from ..catalog import fingerprint_documents as catalog_fingerprint_documents
from ..documents import RagDocument
from .corpus import metadata_of, require_validated_corpus, scope_corpus
from ..identity import GraphKey


def fingerprint_documents(documents: Any, *, source_root: Path | None = None) -> str:
    """Delegate fingerprinting to the canonical catalog implementation.

    The graph layer does not maintain a second hashing algorithm.  The small
    adapter exists only to preserve the graph package's historical keyword
    name while ensuring the catalog's stable relative-path/byte rules are the
    sole implementation.
    """

    root = Path(source_root) if source_root is not None else None
    if isinstance(documents, ValidatedCorpus):
        return catalog_fingerprint_documents(
            documents.documents,
            root=root or documents.root,
        )
    return catalog_fingerprint_documents(documents, root=root)


def corpus_fingerprint(corpus: Any) -> str:
    """Fingerprint a canonical corpus, never a duck-typed fallback."""

    value = require_validated_corpus(corpus)
    return value.fingerprint(root=value.root)


def scoped_corpus_fingerprint(corpus: Any, *, source_root: Path | None = None) -> str:
    """Fingerprint a caller-provided, already scoped canonical corpus."""

    value = require_validated_corpus(corpus)
    return catalog_fingerprint_documents(
        value.documents,
        root=Path(source_root) if source_root is not None else value.root,
    )


def graph_corpus_fingerprint(corpus: Any, key: GraphKey) -> str:
    """Fingerprint only the story-scoped, non-shared documents for ``key``."""

    scoped = scope_corpus(corpus, key)
    documents = tuple(
        document
        for document in scoped.documents
        if str(metadata_of(document).get("story_id", "")) != "__shared__"
    )
    return catalog_fingerprint_documents(documents, root=scoped.root)


def database_fingerprint(
    connection: sqlite3.Connection,
    *,
    source_root: Path | None = None,
) -> str | None:
    """Recompute a graph fingerprint from its recorded source files.

    A graph built from in-memory documents has no source bytes that a Reader
    can rediscover.  In that case ``None`` asks the Reader to rely on its
    explicit expected fingerprint/corpus contract instead of inventing a
    second serialization format.
    """

    rows = connection.execute(
        "SELECT source_file, metadata_json, content FROM documents ORDER BY document_id"
    ).fetchall()
    if not rows:
        return catalog_fingerprint_documents((), root=source_root)
    documents: list[RagDocument] = []
    for row in rows:
        source_file = str(row["source_file"] or "")
        if not source_file:
            return None
        path = Path(source_file)
        if not path.is_absolute() and source_root is not None:
            rooted = Path(source_root) / path
            if rooted.is_file():
                path = rooted
        if not path.is_file():
            return None
        try:
            metadata = json.loads(str(row["metadata_json"] or "{}"))
        except json.JSONDecodeError:
            return None
        if not isinstance(metadata, dict):
            return None
        documents.append(
            RagDocument(
                path=path,
                metadata=metadata,
                # Existing source bytes win when the path exists; this body
                # is only the adapter payload required by catalog's contract.
                body={"text": str(row["content"] or "")},
            )
        )
    return catalog_fingerprint_documents(
        documents,
        root=Path(source_root) if source_root is not None else None,
    )


compute_source_fingerprint = fingerprint_documents


__all__ = [
    "compute_source_fingerprint",
    "corpus_fingerprint",
    "database_fingerprint",
    "fingerprint_documents",
    "graph_corpus_fingerprint",
    "scoped_corpus_fingerprint",
]
