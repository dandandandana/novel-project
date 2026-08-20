"""Canonical catalog corpus adapters used by graph builders."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ..identity import GraphKey, StoryCoordinate
from .types import ModuleReference, ValidatedCorpus
from .types import GraphBuildError


def require_validated_corpus(corpus: Any) -> ValidatedCorpus:
    """Require the catalog-owned immutable corpus at the graph boundary.

    The graph projector is deliberately not a second document-schema
    validator.  Accepting a mapping or an arbitrary object here would make it
    possible to bypass identity, lineage, and source-fingerprint validation
    before SQLite is touched.
    """

    if not isinstance(corpus, ValidatedCorpus):
        raise GraphBuildError(
            "GraphBuilder/SharedBuilder 只接受 catalog.ValidatedCorpus；"
            "请先完成 catalog validation"
        )
    return corpus


def _ancestor_coordinate_or_error(
    document: Any,
    metadata: Mapping[str, Any],
    *,
    timeline_id: str,
    cutoff: StoryCoordinate,
) -> StoryCoordinate:
    """Resolve a cutoff coordinate or fail before projection.

    ``ValidatedCorpus.for_graph`` is the normal catalog path and already
    reports this condition.  Direct ``GraphBuilder`` callers reach
    :func:`scope_corpus` instead, so this boundary must not silently omit a
    malformed ancestor document and produce a partial graph.
    """

    document_id = document_id_of(document, metadata)
    source = source_path_of(document, metadata)
    location = str(source) if source is not None else document_id
    try:
        coordinate = StoryCoordinate.from_metadata(metadata)
    except ValueError as exc:
        raise GraphBuildError(
            "祖先 timeline 文档坐标无效: "
            f"document_id={document_id!r}, timeline_id={timeline_id!r}, "
            f"source={location!r}, cutoff={cutoff}: {exc}"
        ) from exc

    if coordinate is None:
        for field in ("effective_at", "valid_at", "covers_through"):
            value = metadata.get(field)
            if value in (None, ""):
                continue
            try:
                coordinate = StoryCoordinate.from_value(value)
            except ValueError as exc:
                raise GraphBuildError(
                    "祖先 timeline 文档坐标无效: "
                    f"document_id={document_id!r}, timeline_id={timeline_id!r}, "
                    f"source={location!r}, field={field!r}, cutoff={cutoff}: {exc}"
                ) from exc
            break

    if coordinate is None:
        raise GraphBuildError(
            "祖先 timeline 文档缺少可完整解析到 scene 的坐标: "
            f"document_id={document_id!r}, timeline_id={timeline_id!r}, "
            f"source={location!r}, cutoff={cutoff}"
        )
    if not coordinate.is_complete:
        raise GraphBuildError(
            "祖先 timeline 文档坐标必须精确到 scene: "
            f"document_id={document_id!r}, timeline_id={timeline_id!r}, "
            f"source={location!r}, coordinate={coordinate}, cutoff={cutoff}"
        )
    return coordinate


def scope_corpus(corpus: Any, key: GraphKey) -> ValidatedCorpus:
    """Return the canonical, lineage-scoped corpus for one GraphKey.

    ``ValidatedCorpus.for_graph`` owns coordinate cutoffs.  This adapter adds
    two graph-boundary checks that the catalog intentionally leaves to the
    projector: every non-shared document must belong to this story, and a
    sibling/descendant timeline must be rejected instead of silently omitted.
    Common documents may have an empty or ``common`` timeline marker and are
    retained in the target projection.
    """

    source = require_validated_corpus(corpus)
    if source.graph_key is not None and source.graph_key != key:
        raise GraphBuildError(
            "ValidatedCorpus.graph_key 与目标 GraphKey 不一致: "
            f"{source.graph_key.as_dict()} != {key.as_dict()}"
        )
    registry = source.timeline_registry
    try:
        allowed = set(registry.allowed_timeline_ids(key.timeline_id)) if registry else {key.timeline_id}
    except ValueError as exc:
        raise GraphBuildError(f"无法解析目标 timeline lineage: {exc}") from exc

    for document in source.documents:
        metadata = metadata_of(document)
        story_id = str(metadata.get("story_id", ""))
        timeline_id = str(metadata.get("timeline_id", ""))
        is_common = timeline_id in {"", "common"} or str(metadata.get("scope", "")) == "common"
        if story_id == "__shared__":
            continue
        if story_id != key.story_id:
            raise GraphBuildError(
                "文档 story_id 与 GraphKey 不一致: "
                f"{story_id!r} != {key.story_id!r}"
            )
        if not is_common and timeline_id not in allowed:
            raise GraphBuildError(
                "文档 timeline 不属于目标 GraphKey lineage: "
                f"{timeline_id!r} -> {key.timeline_id!r}"
            )

    try:
        cutoffs = registry.cutoffs(key.timeline_id) if registry else {}
    except ValueError as exc:
        raise GraphBuildError(f"无法解析目标 timeline cutoff: {exc}") from exc

    selected: list[Any] = []
    for document in source.documents:
        metadata = metadata_of(document)
        story_id = str(metadata.get("story_id", ""))
        timeline_id = str(metadata.get("timeline_id", ""))
        is_common = timeline_id in {"", "common"} or str(metadata.get("scope", "")) == "common"
        if story_id == "__shared__":
            selected.append(document)
            continue
        if story_id != key.story_id or (not is_common and timeline_id not in allowed):
            continue
        cutoff = cutoffs.get(timeline_id)
        if cutoff is not None:
            coordinate = _ancestor_coordinate_or_error(
                document,
                metadata,
                timeline_id=timeline_id,
                cutoff=cutoff,
            )
            if coordinate > cutoff:
                continue
        selected.append(document)

    selected_ids = {document_id_of(document, metadata_of(document)) for document in selected}
    # Catalog.for_graph intentionally treats only registered timeline IDs as
    # inherited segments.  Common material is a graph-wide scope and can be
    # represented by an empty or ``common`` timeline marker.
    for document in source.documents:
        metadata = metadata_of(document)
        story_id = str(metadata.get("story_id", ""))
        timeline_id = str(metadata.get("timeline_id", ""))
        is_common = timeline_id in {"", "common"} or str(metadata.get("scope", "")) == "common"
        document_id = document_id_of(document, metadata)
        if story_id == key.story_id and is_common and document_id not in selected_ids:
            selected.append(document)
            selected_ids.add(document_id)

    return ValidatedCorpus.from_documents(
        selected,
        root=source.root,
        graph_key=key,
        timeline_registry=registry,
        # Catalog remains the source of validation; the graph boundary keeps
        # a non-strict object here so catalog extensions such as summary
        # document types can be projected without inventing a second schema
        # validator. Identity and lineage checks above remain strict.
        strict=False,
    )


def corpus_documents(corpus: Any) -> tuple[Any, ...]:
    if isinstance(corpus, ValidatedCorpus):
        return tuple(corpus.documents)
    if isinstance(corpus, Mapping):
        value = corpus.get("documents", corpus.get("docs", ()))
        return tuple(value or ())
    value = getattr(corpus, "documents", getattr(corpus, "docs", corpus))
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def corpus_source_root(corpus: Any) -> Path | None:
    if isinstance(corpus, ValidatedCorpus):
        return corpus.source_root
    if isinstance(corpus, Mapping):
        for key in ("source_root", "library_root", "root"):
            if corpus.get(key) is not None:
                return Path(corpus[key])
        return None
    for key in ("source_root", "library_root", "root"):
        value = getattr(corpus, key, None)
        if value is not None:
            return Path(value)
    return None


def corpus_module_references(corpus: Any) -> tuple[dict[str, Any], ...]:
    if isinstance(corpus, ValidatedCorpus):
        value: Any = corpus.module_references
    elif isinstance(corpus, Mapping):
        value = corpus.get("module_references", corpus.get("modules", corpus.get("module_map", ())))
    else:
        value = getattr(
            corpus,
            "module_references",
            getattr(corpus, "modules", getattr(corpus, "module_map", ())),
        )
    if value is None:
        return ()
    if isinstance(value, Mapping):
        # A module-map commonly stores ``module_type -> [document_id]``.
        flattened: list[Any] = []
        for module_type, references in value.items():
            if isinstance(references, (list, tuple, set)):
                flattened.extend(
                    {"module_type": module_type, "document_id": item}
                    if not isinstance(item, Mapping)
                    else {"module_type": module_type, **dict(item)}
                    for item in references
                )
            else:
                flattened.append({"module_type": module_type, "document_id": references})
        value = flattened
    elif isinstance(value, (str, bytes)):
        value = (value,)
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, ModuleReference):
            result.append(item.as_dict())
        elif isinstance(item, Mapping):
            data = dict(item)
            result.append(
                {
                    "module_type": str(data.get("module_type", data.get("type", ""))),
                    "document_id": str(data.get("document_id", data.get("id", ""))),
                    "version": str(data.get("version", "")),
                    "source_file": str(data.get("source_file", "")),
                }
            )
        else:
            result.append({"module_type": "", "document_id": str(item), "version": "", "source_file": ""})
    return tuple(
        sorted(
            (item for item in result if item.get("document_id")),
            key=lambda item: (
                str(item.get("module_type", "")),
                str(item.get("document_id", "")),
                str(item.get("version", "")),
            ),
        )
    )


def metadata_of(document: Any) -> dict[str, Any]:
    if isinstance(document, Mapping):
        value = document.get("metadata")
        if isinstance(value, Mapping):
            return dict(value)
        # Accept a document mapping whose metadata fields are at the root.
        return {
            str(key): value
            for key, value in document.items()
            if key not in {"body", "content", "text", "path", "source_file"}
        }
    value = getattr(document, "metadata", {})
    return dict(value) if isinstance(value, Mapping) else {}


def body_of(document: Any) -> Any:
    if isinstance(document, Mapping):
        for key in ("body", "content", "text"):
            if key in document:
                return document[key]
        return {
            key: value
            for key, value in document.items()
            if key not in {"metadata", "path", "source_file"}
        }
    if hasattr(document, "body"):
        return getattr(document, "body")
    if hasattr(document, "content"):
        return getattr(document, "content")
    return ""


def document_id_of(document: Any, metadata: Mapping[str, Any] | None = None) -> str:
    metadata = metadata or metadata_of(document)
    value = getattr(document, "document_id", None)
    if value:
        return str(value)
    value = metadata.get("document_id", metadata.get("id"))
    if value:
        return str(value)
    identity = "|".join(
        str(metadata.get(key, ""))
        for key in ("story_id", "timeline_id", "document_type", "title", "version")
    )
    import hashlib

    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def source_path_of(document: Any, metadata: Mapping[str, Any] | None = None) -> Path | None:
    metadata = metadata or metadata_of(document)
    value = getattr(document, "path", None)
    if value is None:
        value = getattr(document, "source_file", None)
    if value is None and isinstance(document, Mapping):
        value = document.get("path", document.get("source_file"))
    if value in (None, ""):
        value = metadata.get("source_file")
    return Path(value) if value not in (None, "") else None


def _flatten(value: Any, prefix: str = "") -> str:
    lines: list[str] = []
    if isinstance(value, Mapping):
        for key in sorted(value, key=str):
            child = value[key]
            label = f"{prefix}.{key}" if prefix else str(key)
            lines.append(_flatten(child, label))
    elif isinstance(value, (list, tuple, set)):
        for child in value:
            lines.append(_flatten(child, prefix))
    elif value is not None and value != "":
        lines.append(f"{prefix}: {value}" if prefix else str(value))
    return "\n".join(line for line in lines if line)


def content_of(document: Any, metadata: Mapping[str, Any] | None = None) -> str:
    metadata = metadata or metadata_of(document)
    searchable = getattr(document, "searchable_text", None)
    if callable(searchable):
        value = searchable()
        if value is not None:
            return str(value)
    title = str(metadata.get("title", ""))
    body = _flatten(body_of(document))
    return f"{title}\n{body}".strip()


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
