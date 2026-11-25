"""Catalog-owned source fingerprints used by graph manifests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..catalog import ValidatedCorpus, fingerprint_paths
from ..catalog import fingerprint_documents as catalog_fingerprint_documents
from ..catalog.errors import CatalogValidationError, LayoutMappingError
from ..catalog.layout import resolve_catalog_document_path
from ..catalog.paths import timeline_registry_path
from ..catalog.timelines import load_timeline_registry
from ..documents import DocumentError, RagDocument, load_document, read_yaml_snapshot
from ..identity import GraphKey
from ..layout import story_root
from .corpus import metadata_of, require_validated_corpus, scope_corpus
from .types import GraphBuildError, GraphReadError


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


def _check_inherited_sources(key: GraphKey, grouped_sources: dict[Path, list[RagDocument]]) -> None:
    """依赖：注册表与既有图 scope。输入：目标图键与异线原件（按库分组）。输出：无或可定位拒绝。实现：沿建图规则重验 lineage/cutoff，任何越界旧条目均使图无效。"""
    for root, documents in grouped_sources.items():
        try:
            registry = load_timeline_registry(timeline_registry_path(root, key.story_id),
                                              expected_story_id=key.story_id,
                                              snapshot_root=story_root(root, key.story_id))
            scoped = scope_corpus(ValidatedCorpus(tuple(documents), root=root, timeline_registry=registry), key)
        except (CatalogValidationError, GraphBuildError, OSError, ValueError) as exc:
            raise GraphReadError(f"{documents[0].path}: 无法核验图来源 lineage/cutoff: {exc}") from exc
        allowed_paths = {document.path for document in scoped.documents}
        for document in documents:
            if document.path not in allowed_paths:
                raise GraphReadError(f"{document.path}: source_invalid: 祖先时间线来源超过 cutoff，图已 stale")


def database_fingerprint(
    connection: sqlite3.Connection,
    *,
    source_root: Path | None = None,
    graph_key: GraphKey | None = None,
) -> str | None:
    """依赖：原文快照、catalog 与图 scope。输入：图连接、可选资料根和目标图。输出：重验指纹、缺少平铺源时的 None 或身份错误。实现：读取正式来源原 metadata，核归属和分歧边界后对同字节哈希。

    A graph built from in-memory documents has no source bytes that a Reader
    can rediscover.  In that case ``None`` asks the Reader to rely on its
    explicit expected fingerprint/corpus contract instead of inventing a
    second serialization format.
    """

    rows = connection.execute(
        "SELECT source_file, metadata_json FROM documents ORDER BY document_id"
    ).fetchall()
    paths: list[Path] = []
    source_bytes: dict[Path, bytes] = {}
    inherited: dict[Path, list[RagDocument]] = {}
    unavailable_flat_source = False
    for row in rows:
        source_file = str(row["source_file"] or "")
        if not source_file:
            unavailable_flat_source = True
            continue
        path = Path(source_file)
        if not path.is_absolute() and source_root is not None:
            rooted = Path(source_root) / path
            if rooted.is_file():
                path = rooted
        try:
            physical = resolve_catalog_document_path(path, library_root=source_root)
            if not path.is_file():
                alternate = Path(str(path).replace("\\", "/"))
                if physical is not None or (alternate != path and resolve_catalog_document_path(alternate) is not None):
                    raise DocumentError("无法读取已登记的正式来源")
                unavailable_flat_source = True
                continue
            metadata = json.loads(str(row["metadata_json"] or "{}"))
            if not isinstance(metadata, dict):
                raise DocumentError("图的 metadata_json 需要映射")
            if physical is not None:
                snapshot = read_yaml_snapshot(path)
                document = load_document(path, snapshot=snapshot)
                if not document.metadata.get("story_id") or not document.metadata.get("timeline_id"):
                    raise DocumentError("正式来源缺少 story_id/timeline_id")
                identity = resolve_catalog_document_path(path, document.metadata, library_root=physical.library_root)
                if (graph_key is not None and identity is not None and identity.scope == "timeline"
                        and identity.graph_key != graph_key and identity.library_root is not None):
                    inherited.setdefault(identity.library_root, []).append(document)
                source_bytes[path] = snapshot.raw_bytes
        except (DocumentError, LayoutMappingError, json.JSONDecodeError) as exc:
            raise GraphReadError(f"{path}: source_invalid: {exc}") from exc
        paths.append(path)
    if graph_key is not None:
        _check_inherited_sources(graph_key, inherited)
    if unavailable_flat_source:
        if source_bytes:
            raise GraphReadError("图包含正式来源和未能核验的平铺来源，无法证明新鲜度")
        return None
    return fingerprint_paths(paths, root=source_root, source_bytes=source_bytes)


compute_source_fingerprint = fingerprint_documents


__all__ = [
    "compute_source_fingerprint",
    "corpus_fingerprint",
    "database_fingerprint",
    "fingerprint_documents",
    "graph_corpus_fingerprint",
    "scoped_corpus_fingerprint",
]
