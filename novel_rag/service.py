from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import MODULE_MAP_DOCUMENT_TYPES, SYSTEM_DOCUMENT_TYPES
from .documents import (
    DocumentError,
    RagDocument,
    iter_documents,
    iter_shared_documents,
    iter_story_documents,
    legacy_document_directories,
    load_document,
    read_yaml_mapping,
    registered_story_ids,
    unregistered_story_directories,
    validate_document,
)
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
        for path in legacy_paths:
            relative = path.resolve().relative_to(target_root.resolve())
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
