"""Stable value objects used by the graph projection layer.

The graph package deliberately keeps its input contract explicit.  Builders
accept the canonical identity and catalog ``ValidatedCorpus`` types, while
the projection value objects remain independent of the legacy ``index``
module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..catalog import ValidatedCorpus
from ..identity import GraphKey


class GraphError(RuntimeError):
    """Base error for graph build and read failures."""


class GraphBuildError(GraphError):
    """Raised when a staged graph cannot be built or promoted."""


class GraphReadError(GraphError):
    """Raised when a graph is missing, invalid, stale, or not readable."""


def coerce_graph_key(key: Any) -> GraphKey:
    """Coerce a GraphKey, key-like object, or ``(story_id, timeline_id)`` pair."""

    if isinstance(key, GraphKey):
        return key
    try:
        return GraphKey(str(key.story_id), str(key.timeline_id))
    except AttributeError as exc:
        if isinstance(key, (tuple, list)) and len(key) == 2:
            return GraphKey(str(key[0]), str(key[1]))
        raise ValueError("GraphKey 必须包含 story_id 和 timeline_id") from exc


@dataclass(frozen=True)
class ModuleReference:
    """A stable reference from a story graph to a shared module."""

    module_type: str
    document_id: str
    version: str = ""
    source_file: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "module_type": self.module_type,
            "document_id": self.document_id,
            "version": self.version,
            "source_file": self.source_file,
        }


@dataclass
class ModuleGraphIndex:
    """Reverse dependency index from a shared module to story GraphKeys."""

    _mapping: dict[tuple[str, str], set[GraphKey]] = field(default_factory=dict)

    def register(self, key: GraphKey, references: Any) -> None:
        if isinstance(key, GraphKey):
            graph_key = key
        else:
            try:
                graph_key = coerce_graph_key(key)
            except (AttributeError, ValueError) as exc:
                raise ValueError("ModuleGraphIndex 需要 canonical GraphKey") from exc
        if isinstance(references, Mapping):
            references = (references,)
        for reference in references or ():
            if isinstance(reference, ModuleReference):
                module_type = reference.module_type
                document_id = reference.document_id
            elif isinstance(reference, Mapping):
                module_type = str(reference.get("module_type", reference.get("type", "")))
                document_id = str(reference.get("document_id", reference.get("id", "")))
            else:
                continue
            if module_type and document_id:
                self._mapping.setdefault((module_type, document_id), set()).add(graph_key)

    add = register

    def register_manifest(self, manifest: Any) -> None:
        self.register(manifest.key, manifest.module_references)

    def graph_keys_for_module(self, module_type: str, document_id: str) -> tuple[GraphKey, ...]:
        return tuple(sorted(self._mapping.get((str(module_type), str(document_id)), ())))

    graph_keys_for = graph_keys_for_module
    affected_graph_keys = graph_keys_for_module

    @property
    def module_to_graph_keys(self) -> dict[tuple[str, str], tuple[GraphKey, ...]]:
        return {
            key: tuple(sorted(values))
            for key, values in sorted(self._mapping.items())
        }

    def as_dict(self) -> dict[str, list[dict[str, str]]]:
        return {
            f"{module_type}:{document_id}": [key.as_dict() for key in keys]
            for (module_type, document_id), keys in self.module_to_graph_keys.items()
        }

    @classmethod
    def from_manifests(cls, manifests: Any) -> "ModuleGraphIndex":
        index = cls()
        if isinstance(manifests, GraphManifest) or hasattr(manifests, "key"):
            manifests = (manifests,)
        for manifest in manifests or ():
            index.register_manifest(manifest)
        return index


def build_module_graph_index(manifests: Any) -> ModuleGraphIndex:
    """Build the module-to-GraphKey reverse index from story manifests."""

    return ModuleGraphIndex.from_manifests(manifests)


@dataclass(frozen=True)
class GraphManifest:
    """Metadata that proves which source corpus produced a graph."""

    schema_version: str
    story_id: str
    timeline_id: str
    source_fingerprint: str
    shared_manifest_fingerprint: str | None
    module_references: tuple[Mapping[str, Any], ...]
    built_at: str
    document_count: int
    entity_count: int
    relation_count: int
    source_root: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "module_references", tuple(dict(item) for item in self.module_references))

    @property
    def key(self) -> GraphKey:
        return GraphKey(self.story_id, self.timeline_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "story_id": self.story_id,
            "timeline_id": self.timeline_id,
            "source_fingerprint": self.source_fingerprint,
            "shared_manifest_fingerprint": self.shared_manifest_fingerprint,
            "module_references": [dict(item) for item in self.module_references],
            "built_at": self.built_at,
            "document_count": self.document_count,
            "entity_count": self.entity_count,
            "relation_count": self.relation_count,
            "source_root": self.source_root,
        }


@dataclass(frozen=True)
class SharedManifest:
    """Metadata for the independent shared-system projection."""

    schema_version: str
    story_id: str
    timeline_id: str
    source_fingerprint: str
    built_at: str
    document_count: int
    module_reference_count: int
    source_root: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "story_id": self.story_id,
            "timeline_id": self.timeline_id,
            "source_fingerprint": self.source_fingerprint,
            "built_at": self.built_at,
            "document_count": self.document_count,
            "module_reference_count": self.module_reference_count,
            "source_root": self.source_root,
        }


@dataclass(frozen=True)
class GraphBuildResult:
    """Result of a graph build and single-file promotion."""

    path: Path
    manifest: GraphManifest | SharedManifest
    promoted: bool = True
    temporary_path: Path | None = None


@dataclass(frozen=True)
class EntityResolution:
    text: str
    entity_ids: tuple[str, ...]
    matches: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    @property
    def ambiguous(self) -> bool:
        return len(self.entity_ids) > 1


@dataclass(frozen=True)
class RelationHit:
    relation_id: str
    subject_id: str
    relation_type: str
    object_id: str
    document_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentHit:
    document_id: str
    title: str
    document_type: str
    status: str
    source_file: str
    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SharedModuleHit:
    module_type: str
    document_id: str
    version: str
    source_file: str
