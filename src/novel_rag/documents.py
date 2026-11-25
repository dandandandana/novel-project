from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import yaml

from .config import (
    DOCUMENT_TYPES,
    MODULE_DOCUMENT_TYPES,
    MODULE_TYPES,
    REQUIRED_METADATA,
    STATUSES,
    validate_summary_metadata,
)
from .layout import (
    SHARED_STORY_ID,
    SHARED_TIMELINE_ID,
    STORY_DATA_DIRS,
    SYSTEM_DIRS,
    shared_root,
    stories_root,
    story_root,
)
from .contracts.references import DocumentRef
from .identity import GraphKey, StoryCoordinate


class DocumentError(ValueError):
    pass


@dataclass(frozen=True)
class YamlSnapshot:
    """同一次文件读取得到的 YAML 原始字节、解析值和指纹。"""

    path: Path
    raw_bytes: bytes
    data: dict[str, Any]
    source_hash: str


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


def _parse_yaml_bytes(raw_bytes: bytes) -> Any:
    """依赖：PyYAML安全Loader/可选LibYAML。输入：UTF-8源字节。输出：解析值或原YAML错误。实现：同一入口优先安全C后端，无C时回退SafeLoader，不缓存可变解析值或跳过字节读取。"""

    return yaml.load(raw_bytes.decode("utf-8"), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))


def read_yaml_snapshot(path: Path) -> YamlSnapshot:
    """依赖：共享 YAML 解析器与std.hashing。输入：源文件路径。输出：同字节快照。实现：读一次、解析并指纹化。"""

    try:
        raw_bytes = path.read_bytes()
        data = _parse_yaml_bytes(raw_bytes)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise DocumentError(f"无法读取 YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise DocumentError("文档根节点必须是映射")
    from .std.hashing import fingerprint_bytes

    return YamlSnapshot(
        path=path,
        raw_bytes=raw_bytes,
        data=data,
        source_hash=fingerprint_bytes(raw_bytes),
    )


def load_document(
    path: Path,
    *,
    snapshot: YamlSnapshot | None = None,
) -> RagDocument:
    """依赖：read_yaml_snapshot。输入：文档路径及可选快照。输出：RagDocument或路径拒绝。实现：同路径直接复用映射，异名路径才解析物理身份，不重读来源。"""

    if snapshot is None:
        data = read_yaml_snapshot(path).data
    else:
        if snapshot.path != path and snapshot.path.resolve(strict=False) != path.resolve(strict=False):
            raise DocumentError("快照路径与文档路径不一致")
        data = snapshot.data
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
    if "relations" in metadata:
        relations = metadata.get("relations")
        if not isinstance(relations, list):
            errors.append(f"无效 relations: 必须为列表，实际为 {type(relations).__name__}")
        else:
            for index, item in enumerate(relations):
                if not isinstance(item, dict):
                    errors.append(f"metadata.relations[{index}] 必须为映射")
                    continue
                for key in ("subject_id", "relation_type", "object_id"):
                    value = item.get(key)
                    if not isinstance(value, str) or not value.strip():
                        errors.append(f"metadata.relations[{index}].{key} 必须为非空字符串")
    errors.extend(validate_summary_metadata(metadata))
    return errors


def _iter_yaml_files(root: Path) -> Iterator[Path]:
    if root.exists():
        yield from sorted(root.rglob("*.yaml"))
        yield from sorted(root.rglob("*.yml"))


def iter_shared_documents(library_root: Path) -> Iterator[Path]:
    root = shared_root(library_root)
    for dirname in SYSTEM_DIRS:
        yield from _iter_yaml_files(root / dirname)


def iter_story_documents(library_root: Path, story_id: str) -> Iterator[Path]:
    root = story_root(library_root, story_id)
    for dirname in STORY_DATA_DIRS:
        yield from _iter_yaml_files(root / dirname)
    overrides = root / "system-overrides"
    for dirname in SYSTEM_DIRS:
        yield from _iter_yaml_files(overrides / dirname)


def registered_story_ids(library_root: Path) -> list[str]:
    data = _read_yaml(library_root / "registry" / "stories.yaml")
    return [str(item["story_id"]) for item in data.get("stories", []) if item.get("story_id")]


def iter_documents(library_root: Path) -> Iterator[Path]:
    yield from iter_shared_documents(library_root)
    for story_id in registered_story_ids(library_root):
        yield from iter_story_documents(library_root, story_id)


def unregistered_story_directories(library_root: Path) -> list[Path]:
    root = stories_root(library_root)
    registered = set(registered_story_ids(library_root))
    if not root.exists():
        return []
    return sorted(path for path in root.iterdir() if path.is_dir() and path.name not in registered)


def legacy_document_directories(library_root: Path) -> list[Path]:
    values: list[Path] = []
    for dirname in (*STORY_DATA_DIRS, *SYSTEM_DIRS):
        root = library_root / dirname
        if root.exists():
            values.append(root)
    return values


def registry_values(library_root: Path) -> tuple[set[str], set[tuple[str, str]]]:
    """Return registered story/timeline identifiers during migration.

    This is a compatibility helper with no internal callers.  Keep its old
    return shape, but resolve per-story registry roots through the catalog so
    target-layout files take precedence in the same way as service callers.
    New code should use :mod:`novel_rag.service` validation/catalog APIs.
    """

    from .catalog.paths import story_registry_roots

    stories = set(registered_story_ids(library_root))
    timelines: set[tuple[str, str]] = set()
    for story_id in stories:
        for registry in story_registry_roots(library_root, story_id):
            timelines_data = _read_yaml(registry / "timelines.yaml")
            rows = timelines_data.get("timelines", [])
            if not isinstance(rows, list):
                continue
            timelines.update(
                (str(item["story_id"]), str(item["timeline_id"]))
                for item in rows
                if isinstance(item, dict)
                and item.get("story_id")
                and item.get("timeline_id")
            )
    timelines.add((SHARED_STORY_ID, SHARED_TIMELINE_ID))
    return stories, timelines


def _read_yaml(path: Path) -> dict[str, Any]:
    """依赖：共享 YAML 字节解析器。输入：映射 YAML 路径。输出：映射或空映射。实现：保留缺失、空值和非映射兼容语义。"""

    if not path.exists():
        return {}
    value = _parse_yaml_bytes(path.read_bytes()) or {}
    return value if isinstance(value, dict) else {}


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    """依赖：本模块 YAML owner。输入：映射 YAML 路径。输出：映射或空映射。实现：委托统一映射读取入口。"""

    return _read_yaml(path)


def metadata_json(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True)
