from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .documents import DocumentError, RagDocument, iter_documents, load_document, read_yaml_mapping, registry_values, validate_document


@dataclass(frozen=True)
class ValidationIssue:
    path: Path
    message: str


def load_valid_documents(library_root: Path) -> tuple[list[RagDocument], list[ValidationIssue]]:
    issues = validate_registries(library_root)
    stories, timelines = registry_values(library_root)
    documents: list[RagDocument] = []
    ids: set[str] = set()
    active_current: dict[tuple[str, str, str], Path] = {}
    for path in iter_documents(library_root):
        try:
            document = load_document(path)
        except DocumentError as exc:
            issues.append(ValidationIssue(path, str(exc)))
            continue
        errors = validate_document(document)
        story_id = str(document.metadata.get("story_id", ""))
        timeline_id = str(document.metadata.get("timeline_id", ""))
        if story_id and story_id not in stories:
            errors.append(f"story_id 未在 registry/stories.yaml 注册: {story_id}")
        if story_id and timeline_id and (story_id, timeline_id) not in timelines:
            errors.append(f"timeline_id 未在 registry/timelines.yaml 注册: {story_id}/{timeline_id}")
        if document.document_id in ids:
            errors.append(f"document_id 重复: {document.document_id}")
        if (document.metadata.get("document_type") == "character_state"
                and document.metadata.get("snapshot_type") == "current"
                and document.metadata.get("status") == "active"):
            key = (story_id, timeline_id, str(document.metadata.get("variant_id", "")))
            if key in active_current:
                errors.append(f"同一角色版本存在多个 active current: {active_current[key]}")
            else:
                active_current[key] = path
        if errors:
            issues.extend(ValidationIssue(path, message) for message in errors)
        else:
            ids.add(document.document_id)
            documents.append(document)
    issues.extend(validate_module_map(library_root, documents))
    return documents, issues


def validate_registries(library_root: Path) -> list[ValidationIssue]:
    registry = library_root / "registry"
    issues: list[ValidationIssue] = []
    specifications = (
        ("stories.yaml", "stories", ("story_id",)),
        ("timelines.yaml", "timelines", ("story_id", "timeline_id")),
        ("character-variants.yaml", "character_variants", ("story_id", "timeline_id", "variant_id")),
        ("module-map.yaml", "modules", ("story_id", "timeline_id", "module_type")),
    )
    for filename, collection, keys in specifications:
        path = registry / filename
        data = read_yaml_mapping(path)
        rows = data.get(collection, [])
        if not isinstance(rows, list):
            issues.append(ValidationIssue(path, f"{collection} 必须是列表"))
            continue
        seen: set[tuple[str, ...]] = set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                issues.append(ValidationIssue(path, f"{collection}[{index}] 必须是映射"))
                continue
            identity = tuple(str(row.get(key, "")) for key in keys)
            missing = [key for key, value in zip(keys, identity) if not value]
            if missing:
                issues.append(ValidationIssue(path, f"{collection}[{index}] 缺少 {', '.join(missing)}"))
            elif identity in seen:
                issues.append(ValidationIssue(path, f"重复注册: {'/'.join(identity)}"))
            else:
                seen.add(identity)
    return issues


def validate_module_map(library_root: Path, documents: list[RagDocument]) -> list[ValidationIssue]:
    path = library_root / "registry" / "module-map.yaml"
    if not path.exists():
        return []
    rows = read_yaml_mapping(path).get("modules", [])
    if not isinstance(rows, list):
        return []
    by_id = {document.document_id: document for document in documents}
    issues: list[ValidationIssue] = []
    supported_types = {"rule", "judgment_spec", "generator_spec", "audit_spec"}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        module_type = str(row.get("module_type", ""))
        active_version = str(row.get("active_version", ""))
        if module_type not in supported_types:
            issues.append(ValidationIssue(path, f"modules[{index}] 无效 module_type: {module_type!r}"))
            continue
        if not active_version:
            issues.append(ValidationIssue(path, f"modules[{index}] 缺少 active_version"))
            continue
        document = by_id.get(active_version)
        if document is None:
            issues.append(ValidationIssue(path, f"active_version 未指向有效文档: {active_version}"))
            continue
        metadata = document.metadata
        expected_identity = (str(row.get("story_id", "")), str(row.get("timeline_id", "")))
        actual_identity = (str(metadata.get("story_id", "")), str(metadata.get("timeline_id", "")))
        if actual_identity != expected_identity:
            issues.append(ValidationIssue(path, f"active_version 作品/世界线不匹配: {active_version}"))
        if metadata.get("document_type") != module_type:
            issues.append(ValidationIssue(path, f"active_version 文档类型不匹配: {active_version}"))
        if metadata.get("status") != "active":
            issues.append(ValidationIssue(path, f"active_version 必须指向 active 文档: {active_version}"))
    return issues
