"""Atomic story graph projection builder."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Mapping

from ..chunking import chunk_text
from ..std.time import utc_now_iso
from .corpus import (
    body_of,
    content_of,
    corpus_documents,
    corpus_module_references,
    corpus_source_root,
    document_id_of,
    json_text,
    metadata_of,
    require_validated_corpus,
    scope_corpus,
    source_path_of,
)
from .fingerprint import fingerprint_documents
from .promotion import build_and_promote_atomically
from .reader import GraphReader
from .schema import create_schema, manifest_schema_version, verify_integrity
from .types import (
    GraphBuildError,
    GraphBuildResult,
    GraphKey,
    GraphManifest,
    coerce_graph_key,
)


def graph_path(index_root_or_target: Path, key: Any) -> Path:
    """Resolve the canonical physical path for a GraphKey.

    A directory is always treated as an index root.  An explicit database
    path is accepted only when it already has the canonical ``graphs/<story>/<timeline>.db``
    shape; staged ``.tmp`` files are an internal builder detail and never a
    public target.
    """

    graph_key = coerce_graph_key(key)
    value = Path(index_root_or_target)
    if value.suffix:
        candidate = value.resolve()
        if graph_key.is_shared:
            if candidate.name != "shared.db":
                raise ValueError("共享图 target 必须是 canonical shared.db")
            return candidate
        if (
            candidate.name != f"{graph_key.timeline_id}.db"
            or candidate.parent.name != graph_key.story_id
            or candidate.parent.parent.name != "graphs"
        ):
            raise ValueError(
                "故事图 target 必须是 canonical graphs/<story>/<timeline>.db 路径"
            )
        return candidate
    return graph_key.graph_path(value).resolve()


def _target_from_args(target: Path | None, index_root: Path | None, key: GraphKey) -> Path:
    if target is not None:
        return graph_path(Path(target), key)
    if index_root is not None:
        return graph_path(Path(index_root), key)
    raise ValueError("必须提供 target 或 index_root")


def _module_fingerprint(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    manifest = value.manifest() if callable(getattr(value, "manifest", None)) else value
    value = getattr(manifest, "source_fingerprint", manifest)
    return str(value) if value else None


def _document_metadata_and_content(document: Any) -> tuple[str, dict[str, Any], str, str]:
    metadata = metadata_of(document)
    document_id = document_id_of(document, metadata)
    content = content_of(document, metadata)
    path = source_path_of(document, metadata)
    source_file = str(path) if path is not None else str(metadata.get("source_file", ""))
    return document_id, metadata, content, source_file


def normalize_entities(metadata: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """依赖：graph.corpus.json_text。输入：源metadata。输出：去重实体行。实现：显式单/复数ID与entities统一投影，不推断正文。"""
    values: list[Any] = []
    explicit = metadata.get("entities")
    if isinstance(explicit, Mapping):
        explicit = [explicit]
    if isinstance(explicit, (list, tuple, set)):
        values.extend(explicit)
    for key, entity_type in (
        ("entity_id", "entity"),
        ("entity_ids", "entity"),
        ("character_id", "character"),
        ("character_ids", "character"),
        ("location_id", "location"),
        ("location_ids", "location"),
        ("faction_id", "faction"),
        ("faction_ids", "faction"),
        ("ability_id", "ability"),
        ("ability_ids", "ability"),
    ):
        value = metadata.get(key)
        if isinstance(value, (list, tuple, set)):
            values.extend(
                {"entity_id": item, "entity_type": entity_type, "name": item}
                for item in value
                if item
            )
        elif value:
            values.append({"entity_id": value, "entity_type": entity_type, "name": value})
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        if isinstance(value, Mapping):
            entity_id = str(value.get("entity_id", value.get("id", "")))
            if not entity_id:
                continue
            item = {
                "entity_id": entity_id,
                "entity_type": str(value.get("entity_type", value.get("type", ""))),
                "name": str(value.get("name", value.get("title", entity_id))),
                "metadata_json": json_text(dict(value)),
            }
        else:
            entity_id = str(value)
            if not entity_id:
                continue
            item = {"entity_id": entity_id, "entity_type": "", "name": entity_id, "metadata_json": "{}"}
        result.setdefault(entity_id, item)
    return tuple(result.values())


# 旧私有入口委托公共实现，保留既有调用兼容。
_normalize_entities = normalize_entities


def _normalize_aliases(metadata: Mapping[str, Any], entity_ids: set[str]) -> tuple[dict[str, str], ...]:
    value = metadata.get("aliases")
    result: list[dict[str, str]] = []
    if isinstance(value, Mapping):
        for entity_id, aliases in value.items():
            aliases = aliases if isinstance(aliases, (list, tuple, set)) else [aliases]
            for alias in aliases:
                if str(alias):
                    result.append({"alias": str(alias), "entity_id": str(entity_id)})
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            if isinstance(item, Mapping):
                alias = str(item.get("alias", item.get("name", "")))
                entity_id = str(item.get("entity_id", item.get("id", "")))
                if alias and entity_id:
                    result.append({"alias": alias, "entity_id": entity_id})
            elif entity_ids:
                alias = str(item)
                if alias:
                    result.append({"alias": alias, "entity_id": sorted(entity_ids)[0]})
    return tuple(result)


def _structured_body_aliases(
    document: Any,
    entity_ids: set[str],
) -> tuple[tuple[str, str], ...]:
    """Project explicit ``character.aliases`` from a structured body section.

    Aliases are accepted only from explicit YAML fields and only when the
    document declares exactly one owning entity.  Ambiguous or free-text
    sources are skipped instead of guessed (无法唯一解析时拒绝自动选取).
    """

    if len(entity_ids) != 1:
        return ()
    body = body_of(document)
    if not isinstance(body, Mapping):
        return ()
    section = body.get("character")
    value = section.get("aliases") if isinstance(section, Mapping) else None
    if isinstance(value, str):
        value = (value,)
    if not isinstance(value, (list, tuple, set)):
        return ()
    entity_id = sorted(entity_ids)[0]
    result: list[tuple[str, str]] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append((text, entity_id))
    return tuple(result)


def _normalize_relations(metadata: Mapping[str, Any], document_id: str) -> tuple[dict[str, Any], ...]:
    value = metadata.get("relations")
    if not isinstance(value, (list, tuple, set)):
        return ()
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            continue
        subject = str(item.get("subject_id", item.get("subject", item.get("from", ""))))
        object_id = str(item.get("object_id", item.get("object", item.get("to", ""))))
        relation_type = str(item.get("relation_type", item.get("type", "")))
        if not subject or not object_id or not relation_type:
            continue
        relation_id = str(item.get("relation_id", f"{document_id}:relation:{index}"))
        result.append(
            {
                "relation_id": relation_id,
                "subject_id": subject,
                "relation_type": relation_type,
                "object_id": object_id,
                "document_id": document_id,
                "metadata_json": json_text(dict(item)),
            }
        )
    return tuple(result)


def _validate_document_identity(
    metadata: Mapping[str, Any],
    key: GraphKey,
    allowed_timeline_ids: set[str] | None = None,
) -> dict[str, Any]:
    story_id = str(metadata.get("story_id", ""))
    timeline_id = str(metadata.get("timeline_id", ""))
    if story_id != key.story_id:
        raise GraphBuildError(
            f"文档 story_id 与 GraphKey 不一致: {story_id!r} != {key.story_id!r}"
        )
    # A normalized catalog may label shared/common data without a timeline.  It
    # is materialized into the target graph under the target timeline.
    allowed = allowed_timeline_ids or {key.timeline_id}
    if timeline_id not in {*allowed, "", "common"}:
        raise GraphBuildError(
            f"文档 timeline_id 与 GraphKey 不一致: {timeline_id!r} != {key.timeline_id!r}"
        )
    normalized = dict(metadata)
    normalized["timeline_id"] = key.timeline_id
    return normalized


def _normalize_registry_aliases(value: Any) -> tuple[dict[str, str], ...]:
    """Normalize explicit alias rows into sorted, de-duplicated mappings."""

    if value is None:
        return ()
    if isinstance(value, Mapping):
        raise GraphBuildError("registry_aliases 需要行列表，而不是映射")
    rows: dict[tuple[str, str, str], dict[str, str]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            raise GraphBuildError("registry_aliases 行必须是映射")
        alias = str(item.get("alias", "")).strip()
        entity_id = str(item.get("entity_id", "")).strip()
        if not alias or not entity_id:
            raise GraphBuildError("registry_aliases 行必须包含非空 alias 与 entity_id")
        timeline_id = str(item.get("timeline_id", "")).strip()
        key = (alias.casefold(), entity_id, timeline_id)
        rows.setdefault(
            key,
            {"alias": alias, "entity_id": entity_id, "timeline_id": timeline_id},
        )
    return tuple(rows[key] for key in sorted(rows))


def _insert_documents(
    connection: sqlite3.Connection,
    documents: tuple[Any, ...],
    key: GraphKey,
    allowed_timeline_ids: set[str] | None = None,
    extra_alias_rows: tuple[dict[str, str], ...] = (),
) -> tuple[int, int, int, int]:
    entity_rows: dict[str, dict[str, Any]] = {}
    alias_rows: set[tuple[str, str]] = set()
    relation_rows: dict[str, dict[str, Any]] = {}
    document_entity_rows: set[tuple[str, str]] = set()
    chunk_count = 0
    summary_count = 0
    document_count = 0
    for document in documents:
        raw_id, raw_metadata, content, source_file = _document_metadata_and_content(document)
        # Shared modules have their own projection and are intentionally not
        # duplicated into a story graph.  A catalog ``for_graph`` corpus may
        # still carry them for the caller's Authority assembly.
        if str(raw_metadata.get("story_id", "")) == "__shared__":
            continue
        metadata = _validate_document_identity(raw_metadata, key, allowed_timeline_ids)
        document_id = str(metadata.get("document_id", raw_id)) or raw_id
        document_type = str(metadata.get("document_type", ""))
        status = str(metadata.get("status", ""))
        version = str(metadata.get("version", ""))
        title = str(metadata.get("title", ""))
        connection.execute(
            """INSERT INTO documents(
                document_id, source_file, story_id, timeline_id, document_type,
                status, version, title, metadata_json, content
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                document_id,
                source_file,
                key.story_id,
                key.timeline_id,
                document_type,
                status,
                version,
                title,
                json_text(metadata),
                content,
            ),
        )
        document_count += 1
        chunks = chunk_text(content)
        for chunk in chunks:
            connection.execute(
                "INSERT INTO chunks_fts(chunk_id, document_id, content) VALUES (?, ?, ?)",
                (f"{document_id}:{chunk.ordinal}", document_id, chunk.text),
            )
            chunk_count += 1
        document_entities = normalize_entities(metadata)
        for entity in document_entities:
            entity_rows.setdefault(entity["entity_id"], entity)
            document_entity_rows.add((document_id, entity["entity_id"]))
        entity_ids = {row["entity_id"] for row in document_entities}
        for alias in _normalize_aliases(metadata, entity_ids):
            alias_rows.add((alias["alias"], alias["entity_id"]))
        for alias in _structured_body_aliases(document, entity_ids):
            alias_rows.add(alias)
        for relation in _normalize_relations(metadata, document_id):
            relation_rows.setdefault(relation["relation_id"], relation)
        if document_type in {"summary", "scene-summary", "chapter-summary", "volume-summary"}:
            connection.execute(
                "INSERT INTO summaries(document_id, content, metadata_json) VALUES (?, ?, ?)",
                (document_id, content, json_text(metadata)),
            )
            summary_count += 1
    for row in entity_rows.values():
        connection.execute(
            "INSERT INTO entities(entity_id, entity_type, name, metadata_json) VALUES (?, ?, ?, ?)",
            (row["entity_id"], row["entity_type"], row["name"], row["metadata_json"]),
        )
    for row in extra_alias_rows:
        # Registry aliases are explicit identity data but still may not
        # reference an entity owned by this projection; unknown endpoints are
        # skipped instead of inventing placeholder entities for them.
        alias = str(row.get("alias", "")).strip()
        entity_id = str(row.get("entity_id", "")).strip()
        if alias and entity_id in entity_rows:
            alias_rows.add((alias, entity_id))
    for alias, entity_id in sorted(alias_rows):
        if entity_id not in entity_rows:
            continue
        connection.execute(
            "INSERT INTO aliases(alias, entity_id, normalized_alias) VALUES (?, ?, ?)",
            (alias, entity_id, alias.casefold()),
        )
    for document_id, entity_id in sorted(document_entity_rows):
        connection.execute(
            "INSERT INTO document_entities(document_id, entity_id) VALUES (?, ?)",
            (document_id, entity_id),
        )
    for row in relation_rows.values():
        if row["subject_id"] not in entity_rows:
            entity_rows[row["subject_id"]] = {
                "entity_id": row["subject_id"],
                "entity_type": "",
                "name": row["subject_id"],
                "metadata_json": "{}",
            }
        if row["object_id"] not in entity_rows:
            entity_rows[row["object_id"]] = {
                "entity_id": row["object_id"],
                "entity_type": "",
                "name": row["object_id"],
                "metadata_json": "{}",
            }
    # Relation endpoints are explicit IDs; add their nodes before inserting FK rows.
    for row in entity_rows.values():
        connection.execute(
            "INSERT OR IGNORE INTO entities(entity_id, entity_type, name, metadata_json) VALUES (?, ?, ?, ?)",
            (row["entity_id"], row["entity_type"], row["name"], row["metadata_json"]),
        )
    for row in relation_rows.values():
        connection.execute(
            """INSERT INTO relations(
                relation_id, subject_id, relation_type, object_id, document_id, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                row["relation_id"],
                row["subject_id"],
                row["relation_type"],
                row["object_id"],
                row["document_id"],
                row["metadata_json"],
            ),
        )
    return document_count, chunk_count, len(entity_rows), len(relation_rows)


class GraphBuilder:
    """Build, validate, and atomically promote one story/timeline graph."""

    def __init__(
        self,
        key: Any,
        corpus: Any,
        target: Path | None = None,
        *,
        index_root: Path | None = None,
        shared_manifest: Any = None,
        shared_manifest_fingerprint: str | None = None,
        module_references: Any = None,
        registry_aliases: Any = None,
        retrieval_regression: Callable[[GraphReader], Any] | None = None,
        regression_gate: Callable[[GraphReader], Any] | None = None,
        regression: Callable[[GraphReader], Any] | None = None,
    ) -> None:
        self.key = coerce_graph_key(key)
        if getattr(self.key, "is_shared", False) or (
            self.key.story_id == "__shared__" and self.key.timeline_id == "global"
        ):
            raise GraphBuildError("shared GraphKey 必须交给 SharedBuilder")
        require_validated_corpus(corpus)
        self.corpus = scope_corpus(corpus, self.key)
        self.target = _target_from_args(target, index_root, self.key)
        self.shared_manifest = shared_manifest
        self.shared_manifest_fingerprint = shared_manifest_fingerprint
        self.module_references = module_references
        self._registry_alias_rows = _normalize_registry_aliases(registry_aliases)
        self.retrieval_regression = retrieval_regression or regression_gate or regression

    def _scoped_registry_aliases(self) -> tuple[dict[str, str], ...]:
        """Filter registry alias rows to the target lineage.

        Rows without a timeline apply story-wide; rows of ancestor timelines
        are inherited exactly like their documents, while sibling or
        descendant timelines never leak in.
        """

        allowed = self._allowed_timeline_ids()
        return tuple(
            row
            for row in self._registry_alias_rows
            if not row["timeline_id"] or row["timeline_id"] in allowed
        )

    def _references(self) -> tuple[dict[str, Any], ...]:
        if self.module_references is None:
            return corpus_module_references(self.corpus)
        # Reuse the normalizer by presenting explicit references as a corpus.
        return corpus_module_references({"module_references": self.module_references})

    def _build_manifest(self, counts: tuple[int, int, int, int]) -> GraphManifest:
        document_count, _chunks, entity_count, relation_count = counts
        selected = self._documents_for_graph()
        fingerprint = fingerprint_documents(selected, source_root=corpus_source_root(self.corpus))
        shared_fingerprint = self.shared_manifest_fingerprint or _module_fingerprint(self.shared_manifest)
        references = self._references()
        return GraphManifest(
            schema_version=manifest_schema_version(),
            story_id=self.key.story_id,
            timeline_id=self.key.timeline_id,
            source_fingerprint=fingerprint,
            shared_manifest_fingerprint=shared_fingerprint,
            module_references=tuple(references),
            built_at=utc_now_iso(),
            document_count=document_count,
            entity_count=entity_count,
            relation_count=relation_count,
            source_root=(str(self.corpus.root) if self.corpus.root is not None else None),
        )

    def _allowed_timeline_ids(self) -> set[str]:
        registry = getattr(self.corpus, "timeline_registry", None)
        if registry is not None:
            try:
                return set(registry.allowed_timeline_ids(self.key.timeline_id))
            except (AttributeError, ValueError):
                pass
        return {self.key.timeline_id}

    def _documents_for_graph(self) -> tuple[Any, ...]:
        documents = []
        for document in corpus_documents(self.corpus):
            metadata = getattr(document, "metadata", None)
            if not isinstance(metadata, Mapping) and isinstance(document, Mapping):
                metadata = document.get("metadata", document)
            metadata = metadata if isinstance(metadata, Mapping) else {}
            if str(metadata.get("story_id", "")) == "__shared__":
                continue
            documents.append(document)
        return tuple(documents)

    def build(self) -> GraphBuildResult:
        manifest_holder: dict[str, GraphManifest] = {}

        def populate(connection: sqlite3.Connection) -> GraphManifest:
            create_schema(connection)
            counts = _insert_documents(
                connection,
                self._documents_for_graph(),
                self.key,
                self._allowed_timeline_ids(),
                extra_alias_rows=self._scoped_registry_aliases(),
            )
            manifest = self._build_manifest(counts)
            refs_json = json_text(list(manifest.module_references))
            connection.execute(
                """INSERT INTO graph_manifest(
                    id, schema_version, story_id, timeline_id, source_fingerprint,
                    shared_manifest_fingerprint, module_references_json, built_at,
                    document_count, entity_count, relation_count, source_root
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    manifest.schema_version,
                    manifest.story_id,
                    manifest.timeline_id,
                    manifest.source_fingerprint,
                    manifest.shared_manifest_fingerprint,
                    refs_json,
                    manifest.built_at,
                    manifest.document_count,
                    manifest.entity_count,
                    manifest.relation_count,
                    manifest.source_root or "",
                ),
            )
            manifest_holder["manifest"] = manifest
            return manifest

        def accept(staged_path: Path) -> None:
            # Reader validation is the acceptance gate.
            with GraphReader(
                staged_path,
                expected_key=self.key,
                expected_fingerprint=manifest_holder["manifest"].source_fingerprint,
            ) as reader:
                verify_integrity(reader.connection)
                if self.retrieval_regression is not None:
                    self.retrieval_regression(reader)

        payload, final_path = build_and_promote_atomically(
            self.target,
            label="图",
            populate=populate,
            accept=accept,
        )
        return GraphBuildResult(path=final_path, manifest=payload, promoted=True)

    # Explicit alias for callers that use the architecture's function name on
    # a builder instance.
    build_graph = build


def build_graph(
    key: Any,
    corpus: Any,
    target: Path,
    **builder_options: Any,
) -> GraphBuildResult:
    """Stable function façade for the architecture contract."""

    return GraphBuilder(key, corpus, target, **builder_options).build()
