"""Validated corpus adapter and deterministic source fingerprints."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from ..documents import DocumentError, RagDocument, load_document, validate_document
from ..identity import GraphKey, StoryCoordinate
from .errors import CorpusValidationError
from .timelines import TimelineRegistry


@dataclass(frozen=True)
class CorpusIssue:
    path: Path | None
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}" if self.path else self.message


def adapt_rag_document(value: RagDocument | str | Path | Mapping[str, Any]) -> RagDocument:
    """Adapt legacy callers to the catalog's RagDocument contract."""

    if isinstance(value, RagDocument):
        return value
    if isinstance(value, (str, Path)):
        return load_document(Path(value))
    if isinstance(value, Mapping):
        path = Path(str(value.get("path") or "<memory>"))
        metadata = value.get("metadata")
        if not isinstance(metadata, Mapping):
            raise CorpusValidationError("适配文档缺少 metadata 映射")
        body = value.get("body")
        if body is None:
            body = {key: child for key, child in value.items() if key not in {"path", "metadata"}}
        return RagDocument(path=path, metadata=dict(metadata), body=body)
    raise CorpusValidationError(f"不支持的文档类型: {type(value).__name__}")


def _stable_path(path: Path, root: Path | None) -> str:
    resolved = path.resolve(strict=False)
    if root is not None:
        try:
            return resolved.relative_to(root.resolve(strict=False)).as_posix()
        except ValueError:
            pass
    return resolved.as_posix()


def _document_bytes(document: RagDocument) -> bytes:
    try:
        return document.path.read_bytes()
    except FileNotFoundError:
        # Test fixtures and adapters may provide an in-memory RagDocument.  A
        # canonical fallback still makes those documents fingerprintable.
        payload = {"metadata": document.metadata}
        if isinstance(document.body, Mapping):
            payload.update(document.body)
        else:
            payload["body"] = document.body
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")


def fingerprint_paths(paths: Iterable[str | Path], *, root: str | Path | None = None) -> str:
    """Hash sorted relative paths and exact file bytes using SHA-256."""

    root_path = Path(root).resolve(strict=False) if root is not None else None
    records: list[tuple[str, bytes]] = []
    for raw_path in paths:
        path = Path(raw_path)
        label = _stable_path(path, root_path)
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise CorpusValidationError(f"无法读取 fingerprint 文件 {path}: {exc}") from exc
        records.append((label, content))
    records.sort(key=lambda item: item[0])
    digest = hashlib.sha256()
    for label, content in records:
        label_bytes = label.encode("utf-8")
        digest.update(len(label_bytes).to_bytes(8, "big"))
        digest.update(label_bytes)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"


def fingerprint_documents(
    documents: Iterable[RagDocument | str | Path | Mapping[str, Any]],
    *,
    root: str | Path | None = None,
) -> str:
    """Hash adapted documents by stable source path and exact source bytes."""

    root_path = Path(root).resolve(strict=False) if root is not None else None
    records: list[tuple[str, bytes]] = []
    for raw in documents:
        document = adapt_rag_document(raw)
        records.append((_stable_path(document.path, root_path), _document_bytes(document)))
    records.sort(key=lambda item: item[0])
    digest = hashlib.sha256()
    for label, content in records:
        label_bytes = label.encode("utf-8")
        digest.update(len(label_bytes).to_bytes(8, "big"))
        digest.update(label_bytes)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"


content_fingerprint = fingerprint_documents
compute_content_fingerprint = fingerprint_documents


_COMMON_TIMELINE_IDS = frozenset({"", "common"})
_COMMON_SCOPE_VALUES = frozenset(
    {"common", "story-common", "story_common", "story", "global"}
)


def _is_common_document(document: RagDocument) -> bool:
    """Return whether a document is explicitly story-common material.

    New layout documents can use ``timeline_id: common`` or a scope marker.
    The legacy canon/registry roots are also common when they retain the
    legacy default ``main`` timeline metadata; an explicit branch timeline
    keeps its timeline ownership instead of being silently reclassified.
    """

    metadata = document.metadata
    timeline_id = str(metadata.get("timeline_id") or "")
    if timeline_id in _COMMON_TIMELINE_IDS:
        return True
    for field in ("scope", "catalog_scope", "canon_scope"):
        value = str(metadata.get(field) or "").strip().casefold()
        if value in _COMMON_SCOPE_VALUES:
            return True
    if metadata.get("common") is True:
        return True

    parts = tuple(part.casefold() for part in document.path.parts)
    for index, part in enumerate(parts):
        if part != "stories" or index + 2 >= len(parts):
            continue
        category = parts[index + 2]
        if category == "common":
            return True
        if category in {"canon", "registry"} and timeline_id in {"", "main"}:
            return True
    return False


def _document_coordinate(document: RagDocument) -> StoryCoordinate | None:
    metadata = document.metadata
    try:
        coordinate = StoryCoordinate.from_metadata(metadata)
    except ValueError:
        coordinate = None
    if coordinate is not None:
        return coordinate
    for field in ("effective_at", "valid_at", "covers_through"):
        value = metadata.get(field)
        if value in (None, ""):
            continue
        try:
            return StoryCoordinate.from_value(value)
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class ValidatedCorpus:
    """A validated, immutable view of existing ``RagDocument`` values."""

    documents: tuple[RagDocument, ...]
    root: Path | None = None
    graph_key: GraphKey | None = None
    timeline_registry: TimelineRegistry | None = None
    issues: tuple[CorpusIssue, ...] = ()

    @classmethod
    def from_documents(
        cls,
        documents: Iterable[RagDocument | str | Path | Mapping[str, Any]],
        *,
        root: str | Path | None = None,
        source_root: str | Path | None = None,
        graph_key: GraphKey | None = None,
        timeline_registry: TimelineRegistry | None = None,
        strict: bool = True,
    ) -> "ValidatedCorpus":
        adapted: list[RagDocument] = []
        issues: list[CorpusIssue] = []
        seen: dict[str, Path] = {}
        if root is not None and source_root is not None:
            if Path(root).resolve() != Path(source_root).resolve():
                raise CorpusValidationError("root 与 source_root 不一致")
        root = root if root is not None else source_root
        root_path = Path(root).resolve() if root is not None else None
        for raw in documents:
            try:
                document = adapt_rag_document(raw)
            except (CorpusValidationError, DocumentError, OSError, UnicodeError) as exc:
                issues.append(CorpusIssue(None, str(exc)))
                continue
            errors = validate_document(document)
            issues.extend(CorpusIssue(document.path, error) for error in errors)
            document_id = document.document_id
            previous = seen.get(document_id)
            if previous is not None:
                issues.append(
                    CorpusIssue(
                        document.path,
                        f"document_id 重复: {document_id}（首次位于 {previous}）",
                    )
                )
            else:
                seen[document_id] = document.path
            metadata = document.metadata
            if graph_key is not None:
                story_id = str(metadata.get("story_id") or "")
                if story_id not in {graph_key.story_id, "__shared__"}:
                    issues.append(
                        CorpusIssue(
                            document.path,
                            f"文档跨越 GraphKey story 隔离: {story_id}/{graph_key.story_id}",
                        )
                    )
                if (
                    story_id == graph_key.story_id
                    and timeline_registry is not None
                    and str(metadata.get("timeline_id") or "")
                    not in (
                        set(timeline_registry.allowed_timeline_ids(graph_key.timeline_id))
                        | set(_COMMON_TIMELINE_IDS)
                    )
                ):
                    issues.append(
                        CorpusIssue(
                            document.path,
                            f"文档 timeline 不在 GraphKey lineage 中: "
                            f"{metadata.get('timeline_id')}/{graph_key.timeline_id}",
                        )
                    )
            adapted.append(document)
        if timeline_registry is not None and graph_key is not None:
            try:
                timeline_registry.get(graph_key.timeline_id)
            except ValueError as exc:
                issues.append(CorpusIssue(None, str(exc)))
        result = cls(
            documents=tuple(adapted),
            root=root_path,
            graph_key=graph_key,
            timeline_registry=timeline_registry,
            issues=tuple(issues),
        )
        if strict and issues:
            raise CorpusValidationError(str(issue) for issue in issues)
        return result

    @classmethod
    def from_paths(
        cls,
        paths: Iterable[str | Path],
        *,
        root: str | Path | None = None,
        source_root: str | Path | None = None,
        graph_key: GraphKey | None = None,
        timeline_registry: TimelineRegistry | None = None,
        strict: bool = True,
    ) -> "ValidatedCorpus":
        return cls.from_documents(
            paths,
            root=root,
            source_root=source_root,
            graph_key=graph_key,
            timeline_registry=timeline_registry,
            strict=strict,
        )

    @property
    def document_ids(self) -> tuple[str, ...]:
        return tuple(document.document_id for document in self.documents)

    @property
    def source_root(self) -> Path | None:
        """Alias consumed by the graph projection adapter."""

        return self.root

    @property
    def module_references(self) -> tuple[Any, ...]:
        """Reserved compatibility surface for module-map projections."""

        return ()

    @property
    def source_fingerprint(self) -> str:
        return fingerprint_documents(self.documents, root=self.root)

    def fingerprint(self, *, root: str | Path | None = None) -> str:
        return fingerprint_documents(self.documents, root=root or self.root)

    def for_graph(self, graph_key: GraphKey) -> "ValidatedCorpus":
        """Return the subset compatible with a graph identity and lineage."""

        allowed = {graph_key.timeline_id}
        cutoffs: dict[str, StoryCoordinate | None] = {}
        if self.timeline_registry is not None:
            allowed = set(self.timeline_registry.allowed_timeline_ids(graph_key.timeline_id))
            cutoffs = self.timeline_registry.cutoffs(graph_key.timeline_id)
        selected = []
        coordinate_issues: list[CorpusIssue] = []
        for document in self.documents:
            metadata = document.metadata
            story_id = str(metadata.get("story_id") or "")
            timeline_id = str(metadata.get("timeline_id") or "")
            if story_id == "__shared__":
                selected.append(document)
                continue
            if story_id != graph_key.story_id:
                continue
            if _is_common_document(document):
                selected.append(document)
                continue
            if timeline_id not in allowed:
                continue
            cutoff = cutoffs.get(timeline_id)
            if cutoff is not None:
                coordinate = _document_coordinate(document)
                if coordinate is None or not coordinate.is_complete:
                    coordinate_issues.append(
                        CorpusIssue(
                            document.path,
                            "祖先 timeline 文档缺少可完整解析到 scene 的坐标: "
                            f"{timeline_id}（cutoff={cutoff}）",
                        )
                    )
                    continue
                if coordinate > cutoff:
                    continue
            selected.append(document)
        if coordinate_issues:
            raise CorpusValidationError(str(issue) for issue in coordinate_issues)
        return ValidatedCorpus.from_documents(
            selected,
            root=self.root,
            graph_key=graph_key,
            timeline_registry=self.timeline_registry,
        )


__all__ = [
    "CorpusIssue",
    "ValidatedCorpus",
    "adapt_rag_document",
    "compute_content_fingerprint",
    "content_fingerprint",
    "fingerprint_documents",
    "fingerprint_paths",
]
