from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import yaml

from .config import (
    DOCUMENT_DIRS,
    DOCUMENT_TYPES,
    MODULE_DOCUMENT_TYPES,
    MODULE_TYPES,
    REQUIRED_METADATA,
    STATUSES,
)


class DocumentError(ValueError):
    pass


@dataclass(frozen=True)
class RagDocument:
    path: Path
    metadata: dict[str, Any]
    body: Any

    @property
    def document_id(self) -> str:
        explicit = self.metadata.get("document_id")
        if explicit:
            return str(explicit)
        identity = "|".join(
            str(self.metadata.get(k, ""))
            for k in ("story_id", "timeline_id", "document_type", "title", "version")
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]

    def searchable_text(self) -> str:
        title = str(self.metadata.get("title", ""))
        return f"{title}\n{_flatten(self.body)}".strip()


def _flatten(value: Any, prefix: str = "") -> str:
    lines: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            label = f"{prefix}.{key}" if prefix else str(key)
            lines.append(_flatten(child, label))
    elif isinstance(value, list):
        for child in value:
            lines.append(_flatten(child, prefix))
    elif value is not None and value != "":
        lines.append(f"{prefix}: {value}" if prefix else str(value))
    return "\n".join(line for line in lines if line)


def load_document(path: Path) -> RagDocument:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise DocumentError(f"无法读取 YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise DocumentError("文档根节点必须是映射")
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        raise DocumentError("缺少 metadata 映射")
    body = {key: value for key, value in data.items() if key != "metadata"}
    return RagDocument(path=path, metadata=metadata, body=body)


def validate_document(document: RagDocument) -> list[str]:
    metadata = document.metadata
    errors = [f"metadata.{key} 为必填字段" for key in REQUIRED_METADATA if metadata.get(key) in (None, "")]
    if metadata.get("document_type") not in DOCUMENT_TYPES:
        errors.append(f"无效 document_type: {metadata.get('document_type')!r}")
    if metadata.get("status") not in STATUSES:
        errors.append(f"无效 status: {metadata.get('status')!r}")
    module_type = metadata.get("module_type")
    if module_type is not None and module_type not in MODULE_TYPES:
        errors.append(f"无效 module_type: {module_type!r}")
    expected_module_type = MODULE_DOCUMENT_TYPES.get(str(metadata.get("document_type", "")))
    if expected_module_type:
        for key in ("module_type", "priority", "enforcement"):
            if metadata.get(key) in (None, ""):
                errors.append(f"{metadata.get('document_type')} 必须包含 metadata.{key}")
        if module_type not in (None, "", expected_module_type):
            errors.append(
                f"{metadata.get('document_type')} 的 module_type 必须为 {expected_module_type!r}"
            )
    if metadata.get("document_type") == "character_state":
        if not metadata.get("character_id"):
            errors.append("character_state 必须包含 metadata.character_id")
        if not metadata.get("variant_id"):
            errors.append("character_state 必须包含 metadata.variant_id")
    return errors


def iter_documents(library_root: Path) -> Iterator[Path]:
    for dirname in DOCUMENT_DIRS:
        root = library_root / dirname
        if root.exists():
            yield from sorted(root.rglob("*.yaml"))
            yield from sorted(root.rglob("*.yml"))


def registry_values(library_root: Path) -> tuple[set[str], set[tuple[str, str]]]:
    registry = library_root / "registry"
    stories_data = _read_yaml(registry / "stories.yaml")
    timelines_data = _read_yaml(registry / "timelines.yaml")
    stories = {str(item["story_id"]) for item in stories_data.get("stories", []) if item.get("story_id")}
    timelines = {
        (str(item["story_id"]), str(item["timeline_id"]))
        for item in timelines_data.get("timelines", [])
        if item.get("story_id") and item.get("timeline_id")
    }
    return stories, timelines


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return value if isinstance(value, dict) else {}


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    return _read_yaml(path)


def metadata_json(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True)
