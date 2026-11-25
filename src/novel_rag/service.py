from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from .config import MODULE_MAP_DOCUMENT_TYPES, SYSTEM_DOCUMENT_TYPES
from .documents import (
    DocumentRef,
    DocumentError,
    RagDocument,
    iter_documents,
    iter_shared_documents,
    iter_story_documents,
    legacy_document_directories,
    load_document,
    read_yaml_snapshot,
    read_yaml_mapping,
    registered_story_ids,
    unregistered_story_directories,
    validate_document,
)
from .identity import GraphKey, StoryCoordinate
from .layout import (
    LAYOUT_VERSION,
    SHARED_STORY_ID,
    SHARED_TIMELINE_ID,
    classify_document_path,
    relative_parts,
    shared_registry_root,
    SYSTEM_DIRS,
    story_registry_root,
    story_registry_roots,
    story_root,
    timeline_registry_path,
)

if TYPE_CHECKING:
    from .catalog.timelines import TimelineRegistry


_TARGET_COMMON_DOCUMENT_DIRS = ("canon",)
_TARGET_TIMELINE_DOCUMENT_DIRS = (
    "canon",
    "history",
    "outline",
    "character-state",
    "world-state",
    "feedback",
    "summaries",
)


@dataclass(frozen=True)
class ValidationIssue:
    path: Path
    message: str


@dataclass(frozen=True)
class SourceCorpus:
    """v3 同份原文字节及引用；不依赖运行、索引或旧 shared 规则。"""

    scope: GraphKey
    documents: tuple[RagDocument, ...]
    source_refs: dict[str, DocumentRef]
    snapshots: dict[str, Any]
    timeline_registry: Any
    gaps: tuple[str, ...] = ()

    def read(self, document_id: str) -> tuple[RagDocument, DocumentRef]:
        """依赖：已过滤 corpus。输入：不透明文档ID。输出：原文及同版本引用。实现：只查本作用域映射，缺失拒绝。"""
        for document in self.documents:
            if document.document_id == document_id:
                return document, self.source_refs[document_id]
        raise DocumentError(f"scope_denied: 当前游标无文档 {document_id}")

    def entities(self) -> dict[str, dict[str, Any]]:
        """依赖：graph.builder.normalize_entities。输入：本实例。输出：可见实体索引。实现：复用元数据投影，不猜同名身份。"""
        from .graph.builder import normalize_entities

        result: dict[str, dict[str, Any]] = {}
        for document in self.documents:
            for entity in normalize_entities(document.metadata):
                result.setdefault(entity["entity_id"], entity)
        return result

    def at_cursor(self, coordinate: StoryCoordinate | None = None, endpoint: str = "after") -> "SourceCorpus":
        """依赖：公共document_coordinate/同次源快照。输入：before/after游标。输出：同字节裁取的可见corpus。实现：只裁已有lineage来源，不重新解析或配新hash。"""
        from .catalog.corpus import document_coordinate

        if endpoint not in {"before", "after"}:
            raise DocumentError("scope_denied: 无效叙事游标")
        if coordinate is None:
            return self
        documents = tuple(document for document in self.documents if
                          document_coordinate(document) is None or
                          document_coordinate(document) < coordinate or
                          endpoint == "after" and document_coordinate(document) == coordinate)
        ids = {document.document_id for document in documents}
        return SourceCorpus(self.scope, documents, {key: ref for key, ref in self.source_refs.items() if key in ids},
                            {key: snapshot for key, snapshot in self.snapshots.items() if key in ids},
                            self.timeline_registry, self.gaps)

    def search(self, query: str = "", *, focus: Iterable[str] = (), limit: int | None = 8) -> list[dict]:
        """依赖：safe_query_terms/chunk_text/实体投影。输入：词/明确ID、可选上限。输出：原来源相关片段。实现：无搜索条件直接返回，焦点不命中且无词时不分块，None保留全部命中。"""
        from .chunking import chunk_text
        from .graph.builder import normalize_entities
        from .retrieval.service import safe_query_terms

        terms, targets, hits = safe_query_terms(query.casefold()), set(focus), []
        if not terms and not targets:
            return []
        for document in self.documents:
            entity_refs = normalize_entities(document.metadata)
            direct = document.document_id in targets or bool(targets.intersection(
                entity["entity_id"] for entity in entity_refs))
            if not terms and not direct:
                continue
            chunks = chunk_text(document.searchable_text())
            ranked = [(sum(term in chunk.text.casefold() for term in terms), chunk) for chunk in chunks]
            score, chunk = max(ranked, key=lambda pair: (pair[0], -pair[1].ordinal), default=(0, None))
            if direct or score:
                hits.append((int(direct), score, document.document_id, {
                    "kind": "original", "document_id": document.document_id,
                    "source_ref": self.source_refs[document.document_id].as_dict(),
                    "entity_refs": entity_refs,
                    "text": chunk.text if chunk else None, "chunk_ordinal": chunk.ordinal if chunk else None}))
        ordered = sorted(hits, key=lambda row: (-row[0], -row[1], row[2]))
        return [row[3] for row in (ordered if limit is None else ordered[:max(0, limit)])]


def load_story_scope_registry(library_root: Path, scope: GraphKey) -> TimelineRegistry:
    """依赖：作品和时间线注册表。输入：库根与作品线。输出：含指定时间线的已校验注册表或作用域错误。实现：只读取注册信息并核对作品、时间线及父线约束。"""
    from .catalog.timelines import load_timeline_registry

    root = Path(library_root).resolve()
    if scope.is_shared:
        raise DocumentError("scope_denied: 创作需要本书作用域及合法游标")
    if scope.story_id not in registered_story_ids(root):
        raise DocumentError(f"scope_denied: 未注册作品 {scope.story_id}")
    registry = load_timeline_registry(
        _timeline_registry_path(root, scope.story_id),
        expected_story_id=scope.story_id,
        snapshot_root=story_root(root, scope.story_id).resolve(),
    )
    registry.get(scope.timeline_id)
    return registry


def load_story_sources(
    library_root: Path,
    scope: GraphKey,
    *,
    coordinate: StoryCoordinate | None = None,
    endpoint: str = "after",
) -> SourceCorpus:
    """依赖：作品线注册表、文档快照和路径。输入：库、作品线、before/after游标。输出：只读SourceCorpus。实现：按注册表继承边界校验源字节，再裁叙事游标。"""
    from .catalog.corpus import document_coordinate, is_common_document
    from .config import DEFAULT_SEARCH_STATUSES

    root = Path(library_root).resolve()
    if endpoint not in {"before", "after"}:
        raise DocumentError("scope_denied: 创作需要本书作用域及合法游标")
    registry = load_story_scope_registry(root, scope)
    book_root = story_root(root, scope.story_id).resolve()
    cutoffs = registry.cutoffs(scope.timeline_id)
    documents, refs, snapshots, gaps = [], {}, {}, []
    for path in _paths_for_scope(root, scope.story_id, False):
        try:
            relative = path.resolve().relative_to(book_root)
            if "system-overrides" in relative.parts:
                continue
            if relative.parts[:1] == ("timelines",) and relative.parts[1] not in cutoffs:
                continue
            snapshot = read_yaml_snapshot(path)
            document = load_document(path, snapshot=snapshot)
            if document.metadata.get("story_id") != scope.story_id:
                raise DocumentError("物理目录与story_id不一致")
            errors = validate_document(document)
            if errors:
                raise DocumentError("；".join(errors))
            if document.metadata.get("status") not in DEFAULT_SEARCH_STATUSES:
                continue
            if document.metadata.get("document_type") in SYSTEM_DOCUMENT_TYPES:
                continue
            common = is_common_document(document)
            timeline = str(document.metadata.get("timeline_id") or "")
            if not common and timeline not in cutoffs:
                raise DocumentError("物理目录与timeline lineage不一致")
            position = document_coordinate(document)
            cutoff = None if common else cutoffs.get(timeline)
            if cutoff is not None and (position is None or not position.is_complete):
                gaps.append(f"{document.document_id}: 祖先来源时点不明")
                continue
            if cutoff is not None and position > cutoff:
                continue
            if position is None and document.metadata.get("document_type") != "canon":
                gaps.append(f"{document.document_id}: 旧来源无叙事坐标，仅作原文参考")
            if document.document_id in refs:
                raise DocumentError("document_id重复")
            actual_scope = GraphKey(scope.story_id, timeline or scope.timeline_id)
            refs[document.document_id] = DocumentRef(
                document_id=document.document_id,
                source_revision=int(document.metadata.get("source_revision", 1)),
                source_hash=snapshot.source_hash,
                scope=actual_scope,
                coordinate=position,
            )
            snapshots[document.document_id] = snapshot
            documents.append(document)
        except (DocumentError, ValueError, OSError) as exc:
            gaps.append(f"{path.name}: source_invalid: {exc}")
    return SourceCorpus(scope, tuple(documents), refs, snapshots, registry, tuple(gaps)).at_cursor(coordinate, endpoint)


def _yaml_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    yield from sorted(root.rglob("*.yaml"))
    yield from sorted(root.rglob("*.yml"))


def _target_shared_documents(library_root: Path) -> Iterable[Path]:
    # Shared system documents keep their established physical layout in v2.
    yield from iter_shared_documents(library_root)


def _target_story_documents(library_root: Path, story_id: str) -> Iterable[Path]:
    root = story_root(library_root, story_id)
    for dirname in _TARGET_COMMON_DOCUMENT_DIRS:
        yield from _yaml_files(root / "common" / dirname)
    timelines = root / "timelines"
    if not timelines.is_dir():
        return
    for timeline_root in sorted(path for path in timelines.iterdir() if path.is_dir()):
        for dirname in _TARGET_TIMELINE_DOCUMENT_DIRS:
            yield from _yaml_files(timeline_root / dirname)
        overrides = timeline_root / "system-overrides"
        for dirname in SYSTEM_DIRS:
            yield from _yaml_files(overrides / dirname)


def _unique_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        resolved = path.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(path)
    return tuple(result)


def _story_registry_roots(library_root: Path, story_id: str) -> tuple[Path, ...]:
    """Return old and target registry roots without inventing a third layout."""

    return story_registry_roots(library_root, story_id)


def _timeline_registry_path(library_root: Path, story_id: str) -> Path:
    return timeline_registry_path(library_root, story_id)


def _registry_values_compat(library_root: Path) -> tuple[set[str], set[tuple[str, str]]]:
    """Read timeline registrations from either supported layout during migration."""

    stories = set(registered_story_ids(library_root))
    timelines: set[tuple[str, str]] = set()
    for current_story in stories:
        for registry in _story_registry_roots(library_root, current_story):
            rows = read_yaml_mapping(registry / "timelines.yaml").get("timelines", [])
            if not isinstance(rows, list):
                continue
            timelines.update(
                (str(row.get("story_id")), str(row.get("timeline_id")))
                for row in rows
                if isinstance(row, dict) and row.get("story_id") and row.get("timeline_id")
            )
    timelines.add((SHARED_STORY_ID, SHARED_TIMELINE_ID))
    return stories, timelines


def _paths_for_scope(library_root: Path, story_id: str | None, include_shared: bool) -> Iterable[Path]:
    """依赖：既有布局/去重入口。输入：库、可选书及共享开关。输出：原路径序列。实现：按类别优先目标布局，单书根物理路径只求一次，逐源仍核验物理归属。"""
    story_ids = [story_id] if story_id is not None else registered_story_ids(library_root)
    paths: list[Path] = []
    if include_shared:
        paths.extend(iter_shared_documents(library_root))
        paths.extend(_target_shared_documents(library_root))
    for current_story in story_ids:
        # A migration is copy-only, so the legacy and target trees can exist
        # simultaneously.  Once a target category exists it is authoritative
        # for that category; loading both copies would manufacture duplicate
        # document_ids and make an otherwise valid migrated library fail
        # validation.  Keep category-level fallback for partially migrated
        # libraries instead of silently dropping legacy-only categories.
        target_paths = tuple(_target_story_documents(library_root, current_story))
        target_root = story_root(library_root, current_story)
        target_categories: set[str] = set()
        common_canon = target_root / "common" / "canon"
        if common_canon.is_dir():
            target_categories.add("canon")
        timelines_root = target_root / "timelines"
        if timelines_root.is_dir():
            for timeline_root in timelines_root.iterdir():
                if not timeline_root.is_dir():
                    continue
                for category in (*_TARGET_TIMELINE_DOCUMENT_DIRS, "system-overrides"):
                    if (timeline_root / category).is_dir():
                        target_categories.add(category)

        legacy_paths = tuple(iter_story_documents(library_root, current_story))
        physical_root = target_root.resolve()
        for path in legacy_paths:
            relative = path.resolve().relative_to(physical_root)
            category = relative.parts[0] if relative.parts else ""
            if category not in target_categories:
                paths.append(path)
        paths.extend(target_paths)
    yield from _unique_paths(paths)


def load_valid_documents(
    library_root: Path,
    story_id: str | None = None,
    *,
    include_shared: bool = True,
) -> tuple[list[RagDocument], list[ValidationIssue]]:
    library_root = library_root.resolve()
    issues = validate_registries(library_root)
    stories, timelines = _registry_values_compat(library_root)
    if story_id is not None and story_id not in stories:
        issues.append(ValidationIssue(library_root / "registry" / "stories.yaml", f"未注册 story_id: {story_id}"))
        return [], issues

    documents: list[RagDocument] = []
    seen_ids: dict[str, Path] = {}
    active_current: dict[tuple[str, str, str], Path] = {}
    for path in _paths_for_scope(library_root, story_id, include_shared):
        try:
            document = load_document(path)
        except DocumentError as exc:
            issues.append(ValidationIssue(path, str(exc)))
            continue
        errors = validate_document(document)
        metadata = document.metadata
        metadata_story = str(metadata.get("story_id", ""))
        metadata_timeline = str(metadata.get("timeline_id", ""))
        document_type = str(metadata.get("document_type", ""))
        physical_scope, physical_story = classify_document_path(library_root, path)

        if physical_scope == "shared":
            if (metadata_story, metadata_timeline) != (SHARED_STORY_ID, SHARED_TIMELINE_ID):
                errors.append(
                    f"shared 文档必须使用 {SHARED_STORY_ID}/{SHARED_TIMELINE_ID}: "
                    f"{metadata_story}/{metadata_timeline}"
                )
            if document_type not in SYSTEM_DOCUMENT_TYPES:
                errors.append(f"shared 目录只允许系统文档，实际为: {document_type}")
        elif physical_scope == "story":
            if metadata_story != physical_story:
                errors.append(f"物理小说目录与 metadata.story_id 不一致: {physical_story}/{metadata_story}")
            if metadata_story and metadata_story not in stories:
                errors.append(f"story_id 未在全局目录注册: {metadata_story}")
            if metadata_story and metadata_timeline and (metadata_story, metadata_timeline) not in timelines:
                errors.append(f"timeline_id 未在小说 registry 注册: {metadata_story}/{metadata_timeline}")
            parts = relative_parts(library_root, path)
            in_overrides = (
                (len(parts) >= 3 and parts[2] == "system-overrides")
                or (len(parts) >= 5 and parts[2] == "timelines" and parts[4] == "system-overrides")
            )
            if document_type in SYSTEM_DOCUMENT_TYPES and not in_overrides:
                errors.append(f"小说专属系统文档必须放在 system-overrides: {document_type}")
            if document_type not in SYSTEM_DOCUMENT_TYPES and in_overrides:
                errors.append(f"system-overrides 不允许内容资料: {document_type}")
        else:
            errors.append("文档不在 shared 系统层或 stories/<story_id> 隔离层中")

        previous_path = seen_ids.get(document.document_id)
        if previous_path is not None:
            errors.append(f"document_id 重复: {document.document_id}（首次位于 {previous_path}）")
        else:
            seen_ids[document.document_id] = path

        if (
            document_type == "character_state"
            and metadata.get("snapshot_type") == "current"
            and metadata.get("status") == "active"
        ):
            key = (metadata_story, metadata_timeline, str(metadata.get("variant_id", "")))
            if key in active_current:
                errors.append(f"同一角色版本存在多个 active current: {active_current[key]}")
            else:
                active_current[key] = path

        if errors:
            issues.extend(ValidationIssue(path, message) for message in errors)
        else:
            documents.append(document)

    issues.extend(validate_module_maps(library_root, documents, story_id=story_id))
    issues.extend(validate_version_maps(library_root, documents, story_id=story_id))
    return documents, issues


def load_validated_corpus(
    library_root: Path,
    story_id: str,
    *,
    timeline_id: str | None = None,
    include_shared: bool = True,
):
    """Load the canonical catalog corpus for one story.

    ``load_valid_documents`` remains the stable legacy validation result
    (``documents, issues``).  New graph callers need the immutable
    ``ValidatedCorpus`` contract and timeline registry, so this adapter keeps
    that conversion in the service layer instead of making the graph package
    know about library YAML layout.

    The function intentionally raises on validation errors.  A graph builder
    must never project a partially validated source corpus; callers that need
    diagnostics can continue using :func:`load_valid_documents` directly.
    """

    from .catalog import ValidatedCorpus, load_timeline_registry
    from .catalog.errors import CatalogValidationError

    root = Path(library_root).resolve()
    documents, issues = load_valid_documents(root, story_id=story_id, include_shared=include_shared)
    if issues:
        detail = "；".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise CatalogValidationError(f"资料校验失败，未建立图: {detail}")

    registry_path = _timeline_registry_path(root, story_id)
    registry = load_timeline_registry(
        registry_path,
        expected_story_id=story_id,
        snapshot_root=story_root(root, story_id),
    )
    # Validate the complete story corpus first.  Passing a GraphKey into
    # ``from_documents`` here would reject sibling timelines before the
    # canonical ``for_graph`` cutoff gets a chance to select the lineage.
    corpus = ValidatedCorpus.from_documents(
        documents,
        root=root,
        timeline_registry=registry,
        strict=True,
    )
    if timeline_id is None:
        return corpus
    from .identity import GraphKey

    return corpus.for_graph(GraphKey(story_id, timeline_id))


def _validate_rows(
    path: Path,
    collection: str,
    keys: tuple[str, ...],
    *,
    expected_story_id: str | None = None,
) -> list[ValidationIssue]:
    data = read_yaml_mapping(path)
    rows = data.get(collection, [])
    issues: list[ValidationIssue] = []
    if not isinstance(rows, list):
        return [ValidationIssue(path, f"{collection} 必须是列表")]
    seen: set[tuple[str, ...]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            issues.append(ValidationIssue(path, f"{collection}[{index}] 必须是映射"))
            continue
        identity = tuple(str(row.get(key, "")) for key in keys)
        missing = [key for key, value in zip(keys, identity) if not value]
        if missing:
            issues.append(ValidationIssue(path, f"{collection}[{index}] 缺少 {', '.join(missing)}"))
            continue
        if identity in seen:
            issues.append(ValidationIssue(path, f"重复注册: {'/'.join(identity)}"))
        else:
            seen.add(identity)
        if expected_story_id is not None and str(row.get("story_id", "")) != expected_story_id:
            issues.append(
                ValidationIssue(path, f"{collection}[{index}] story_id 必须为目录所属小说 {expected_story_id}")
            )
    return issues


def validate_registries(library_root: Path) -> list[ValidationIssue]:
    root_registry = library_root / "registry"
    issues = _validate_rows(root_registry / "stories.yaml", "stories", ("story_id",))
    layout_path = root_registry / "layout.yaml"
    layout = read_yaml_mapping(layout_path)
    if str(layout.get("layout_version", "")) != LAYOUT_VERSION:
        issues.append(ValidationIssue(layout_path, f"layout_version 必须为 {LAYOUT_VERSION}"))

    legacy_registry_files = (
        "timelines.yaml",
        "character-variants.yaml",
        "aliases.yaml",
        "version-map.yaml",
        "module-map.yaml",
    )
    for filename in legacy_registry_files:
        path = root_registry / filename
        if path.exists():
            issues.append(ValidationIssue(path, "旧版根注册表会破坏小说隔离，请迁移到 stories/<story_id>/registry"))
    for path in legacy_document_directories(library_root):
        issues.append(ValidationIssue(path, "旧版平铺资料目录会破坏小说隔离"))
    for path in unregistered_story_directories(library_root):
        issues.append(ValidationIssue(path, "小说目录未在 registry/stories.yaml 注册"))

    catalog = read_yaml_mapping(root_registry / "stories.yaml").get("stories", [])
    for row in catalog if isinstance(catalog, list) else []:
        if not isinstance(row, dict) or not row.get("story_id"):
            continue
        story_id = str(row["story_id"])
        try:
            root = story_root(library_root, story_id)
        except ValueError as exc:
            issues.append(ValidationIssue(root_registry / "stories.yaml", f"无效 story_id {story_id!r}: {exc}"))
            continue
        if not root.is_dir():
            issues.append(ValidationIssue(root, "已注册小说缺少独立目录"))
            continue
        for registry in _story_registry_roots(library_root, story_id):
            timeline_path = registry / "timelines.yaml"
            if timeline_path.is_file():
                issues.extend(
                    _validate_rows(
                        timeline_path,
                        "timelines",
                        ("story_id", "timeline_id"),
                        expected_story_id=story_id,
                    )
                )
            variants_path = registry / "character-variants.yaml"
            if variants_path.is_file():
                issues.extend(
                    _validate_rows(
                        variants_path,
                        "character_variants",
                        ("story_id", "timeline_id", "variant_id"),
                        expected_story_id=story_id,
                    )
                )
            module_path = registry / "module-map.yaml"
            if module_path.is_file():
                issues.extend(
                    _validate_rows(
                        module_path,
                        "modules",
                        ("story_id", "timeline_id", "module_type"),
                        expected_story_id=story_id,
                    )
                )
            aliases_path = registry / "aliases.yaml"
            if aliases_path.is_file():
                aliases = read_yaml_mapping(aliases_path).get("aliases", [])
                if not isinstance(aliases, list):
                    issues.append(ValidationIssue(aliases_path, "aliases 必须是列表"))
            version_path = registry / "version-map.yaml"
            if version_path.is_file():
                versions = read_yaml_mapping(version_path).get("versions", [])
                if not isinstance(versions, list):
                    issues.append(ValidationIssue(version_path, "versions 必须是列表"))

    defaults_path = shared_registry_root(library_root) / "module-defaults.yaml"
    issues.extend(_validate_rows(defaults_path, "modules", ("module_type",)))
    shared_versions = read_yaml_mapping(shared_registry_root(library_root) / "version-map.yaml").get("versions", [])
    if not isinstance(shared_versions, list):
        issues.append(ValidationIssue(shared_registry_root(library_root) / "version-map.yaml", "versions 必须是列表"))
    return issues


def _active_versions(row: dict[str, Any]) -> list[str]:
    values = row.get("active_versions")
    if isinstance(values, list):
        return [str(value) for value in values if value]
    value = row.get("active_version")
    return [str(value)] if value else []


def validate_module_maps(
    library_root: Path,
    documents: list[RagDocument],
    *,
    story_id: str | None = None,
) -> list[ValidationIssue]:
    by_id = {document.document_id: document for document in documents}
    issues: list[ValidationIssue] = []
    defaults_path = shared_registry_root(library_root) / "module-defaults.yaml"
    default_rows = read_yaml_mapping(defaults_path).get("modules", [])
    if isinstance(default_rows, list):
        for index, row in enumerate(default_rows):
            if not isinstance(row, dict):
                continue
            module_type = str(row.get("module_type", ""))
            if module_type not in MODULE_MAP_DOCUMENT_TYPES:
                issues.append(ValidationIssue(defaults_path, f"modules[{index}] 无效 module_type: {module_type!r}"))
                continue
            active_versions = _active_versions(row)
            if not active_versions:
                issues.append(ValidationIssue(defaults_path, f"modules[{index}] 缺少 active_versions"))
                continue
            for active_version in active_versions:
                document = by_id.get(active_version)
                if document is None:
                    issues.append(ValidationIssue(defaults_path, f"active_versions 未指向有效文档: {active_version}"))
                    continue
                metadata = document.metadata
                if (
                    str(metadata.get("story_id", "")),
                    str(metadata.get("timeline_id", "")),
                ) != (SHARED_STORY_ID, SHARED_TIMELINE_ID):
                    issues.append(ValidationIssue(defaults_path, f"共享默认模块越过隔离边界: {active_version}"))
                if metadata.get("document_type") != module_type:
                    issues.append(ValidationIssue(defaults_path, f"active_versions 文档类型不匹配: {active_version}"))
                if metadata.get("status") != "active":
                    issues.append(ValidationIssue(defaults_path, f"active_versions 必须指向 active 文档: {active_version}"))
    story_ids = [story_id] if story_id is not None else registered_story_ids(library_root)
    for current_story in story_ids:
        for registry in _story_registry_roots(library_root, current_story):
            path = registry / "module-map.yaml"
            if not path.is_file():
                continue
            rows = read_yaml_mapping(path).get("modules", [])
            if not isinstance(rows, list):
                continue
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                module_type = str(row.get("module_type", ""))
                if module_type not in MODULE_MAP_DOCUMENT_TYPES:
                    issues.append(ValidationIssue(path, f"modules[{index}] 无效 module_type: {module_type!r}"))
                    continue
                active_versions = _active_versions(row)
                if not active_versions:
                    issues.append(ValidationIssue(path, f"modules[{index}] 缺少 active_versions"))
                    continue
                for active_version in active_versions:
                    document = by_id.get(active_version)
                    if document is None:
                        issues.append(ValidationIssue(path, f"active_versions 未指向有效文档: {active_version}"))
                        continue
                    metadata = document.metadata
                    identity = (str(metadata.get("story_id", "")), str(metadata.get("timeline_id", "")))
                    expected_story_identity = (str(row.get("story_id", "")), str(row.get("timeline_id", "")))
                    if identity not in (expected_story_identity, (SHARED_STORY_ID, SHARED_TIMELINE_ID)):
                        issues.append(ValidationIssue(path, f"active_versions 作品/世界线不匹配: {active_version}"))
                    if metadata.get("document_type") != module_type:
                        issues.append(ValidationIssue(path, f"active_versions 文档类型不匹配: {active_version}"))
                    if metadata.get("status") != "active":
                        issues.append(ValidationIssue(path, f"active_versions 必须指向 active 文档: {active_version}"))
    return issues


def validate_version_maps(
    library_root: Path,
    documents: list[RagDocument],
    *,
    story_id: str | None = None,
) -> list[ValidationIssue]:
    by_id = {document.document_id: document for document in documents}
    maps: list[tuple[Path, str]] = [
        (shared_registry_root(library_root) / "version-map.yaml", SHARED_STORY_ID)
    ]
    story_ids = [story_id] if story_id is not None else registered_story_ids(library_root)
    for current in story_ids:
        maps.extend(
            (registry / "version-map.yaml", current)
            for registry in _story_registry_roots(library_root, current)
            if (registry / "version-map.yaml").is_file()
        )
    issues: list[ValidationIssue] = []
    for path, expected_story in maps:
        rows = read_yaml_mapping(path).get("versions", [])
        if not isinstance(rows, list):
            continue
        seen: set[str] = set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            family = str(row.get("document_family", ""))
            current = str(row.get("current", ""))
            if not family or not current:
                issues.append(ValidationIssue(path, f"versions[{index}] 缺少 document_family/current"))
                continue
            if family in seen:
                issues.append(ValidationIssue(path, f"重复 document_family: {family}"))
            seen.add(family)
            document = by_id.get(current)
            if document is None:
                issues.append(ValidationIssue(path, f"current 未指向有效文档: {current}"))
                continue
            actual_story = str(document.metadata.get("story_id", ""))
            if actual_story != expected_story:
                issues.append(ValidationIssue(path, f"current 跨越隔离边界: {current} 属于 {actual_story}"))
    return issues
