"""来源引用与位置的纯业务合同；来源签发、读取和效力判断仍由各业务服务负责。"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping

from ..identity import GraphKey, StoryCoordinate


SOURCE_FINGERPRINT_PATTERN = re.compile(r"sha256:[0-9a-fA-F]{64}")


@dataclass(frozen=True)
class DocumentRef:
    """正式 YAML 来源的不可变引用值。依赖：identity 纯类型。输入：来源字段。输出：JSON 友好字典。实现：以冻结字段保存来源身份。"""

    document_id: str
    source_revision: int
    source_hash: str
    scope: GraphKey
    coordinate: StoryCoordinate | None = None
    kind: Literal["document"] = field(default="document", init=False)

    def as_dict(self) -> dict[str, Any]:
        """依赖：dataclasses.asdict。输入：当前引用。输出：JSON 友好映射。实现：递归展开 scope 与 coordinate。"""

        return asdict(self)


@dataclass(frozen=True)
class DraftRef:
    """草稿检查点的不可变引用。依赖：纯值字段。输入：文档、修订、内容指纹和检查点。输出：draft 引用。实现：固定 kind 并保留稿件身份。"""

    draft_document_id: str
    draft_revision: int
    content_hash: str
    checkpoint_id: str
    kind: Literal["draft"] = field(default="draft", init=False)

    def as_dict(self) -> dict[str, Any]:
        """依赖：dataclasses.asdict。输入：当前引用。输出：JSON 友好映射。实现：递归展开不可变字段。"""

        return asdict(self)


@dataclass(frozen=True)
class AuthorInputRef:
    """固定作者输入文本块的不可变引用。依赖：纯值字段。输入：run、输入槽和快照指纹。输出：author_input 引用。实现：固定 kind 并保留输入身份。"""

    run_id: str
    input_slot: str
    snapshot_hash: str
    kind: Literal["author_input"] = field(default="author_input", init=False)

    def as_dict(self) -> dict[str, Any]:
        """依赖：dataclasses.asdict。输入：当前引用。输出：JSON 友好映射。实现：递归展开不可变字段。"""

        return asdict(self)


MemorySourceRef = DocumentRef | DraftRef | AuthorInputRef


def parse_source_ref(
    value: Mapping[str, Any],
) -> MemorySourceRef:
    """依赖：identity 与本模块来源值类型。输入：带 kind 的来源映射。输出：对应来源引用。实现：解析字段并重建嵌套 scope/coordinate。"""

    kind = value.get("kind")
    if kind == "document":
        raw_scope = value["scope"]
        scope = (
            raw_scope
            if isinstance(raw_scope, GraphKey)
            else GraphKey(**raw_scope)
        )
        raw_coordinate = value.get("coordinate")
        coordinate = (
            raw_coordinate
            if isinstance(raw_coordinate, StoryCoordinate)
            else StoryCoordinate.from_value(raw_coordinate)
            if raw_coordinate is not None
            else None
        )
        return DocumentRef(
            document_id=value["document_id"],
            source_revision=value["source_revision"],
            source_hash=value["source_hash"],
            scope=scope,
            coordinate=coordinate,
        )
    if kind == "draft":
        return DraftRef(
            draft_document_id=value["draft_document_id"],
            draft_revision=value["draft_revision"],
            content_hash=value["content_hash"],
            checkpoint_id=value["checkpoint_id"],
        )
    if kind == "author_input":
        return AuthorInputRef(
            run_id=value["run_id"],
            input_slot=value["input_slot"],
            snapshot_hash=value["snapshot_hash"],
        )
    raise ValueError(f"未知来源引用 kind: {kind!r}")


def validate_source_refs(refs: object) -> list[str]:
    """依赖：parse_source_ref/公共hash格式。输入：分型引用数组。输出：字段错误列表。实现：检查真实Ref形状/类型后委托既有纯解析，不解释来源效力。"""
    if not isinstance(refs, list) or not refs:
        return ["source_refs需要非空列表"]
    errors = []
    fields = {"document": {"document_id", "source_revision", "source_hash", "scope"},
              "draft": {"draft_document_id", "draft_revision", "content_hash", "checkpoint_id"},
              "author_input": {"run_id", "input_slot", "snapshot_hash"}}
    for index, ref in enumerate(refs):
        path = f"source_refs[{index}]"
        if not isinstance(ref, dict) or not isinstance(ref.get("kind"), str) or ref["kind"] not in fields:
            errors.append(path + ": 分型Ref对象错误")
            continue
        required = fields[ref["kind"]]
        optional = {"coordinate"} if ref["kind"] == "document" else set()
        if not required <= ref.keys() or set(ref) - required - {"kind"} - optional:
            errors.append(path + ": 必需字段缺失或存在未知字段")
            continue
        for key in required - {"source_revision", "draft_revision", "scope"}:
            if not isinstance(ref[key], str) or not ref[key].strip():
                errors.append(path + "." + key + ": 需要非空字符串")
        for key in {"source_revision", "draft_revision"} & required:
            if type(ref[key]) is not int or ref[key] < (1 if key == "draft_revision" else 0):
                errors.append(path + "." + key + ": 修订需要合法整数")
        fingerprint = ref.get("source_hash", ref.get("content_hash", ref.get("snapshot_hash")))
        if not isinstance(fingerprint, str) or not SOURCE_FINGERPRINT_PATTERN.fullmatch(fingerprint):
            errors.append(path + ": 实际hash格式无效")
        if ref["kind"] == "author_input" and (not isinstance(ref["input_slot"], str) or ref["input_slot"] not in {"outline", "request"}):
            errors.append(path + ": 输入槽非法")
        if ref["kind"] == "document" and ref.get("coordinate") is not None:
            coordinate_errors = validate_position({"kind": "document", "coordinate": ref["coordinate"]})
            if coordinate_errors:
                errors.extend(path + ": " + error for error in coordinate_errors)
                continue
        try:
            parse_source_ref(ref)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            errors.append(path + ": " + str(exc))
    return errors


def validate_position(position: object) -> list[str]:
    """依赖：StoryCoordinate。输入：host生效位置或legacy未知。输出：结构错误。实现：分型位置严格检查，未知不伪造坐标且由回放显示缺口。"""
    if position is None:
        return []
    if not isinstance(position, dict):
        return ["narrative_position需要对象或未知null"]
    if position.get("kind") == "draft":
        if set(position) != {"kind", "checkpoint_id"} or not isinstance(position.get("checkpoint_id"), str) or not position["checkpoint_id"].strip():
            return ["narrative_position草稿检查点错误"]
    elif position.get("kind") == "document":
        if set(position) - {"kind", "coordinate", "endpoint"} or not isinstance(position.get("endpoint", "after"), str) or position.get("endpoint", "after") not in {"before", "after"}:
            return ["narrative_position正式位置字段错误"]
        coordinate = position.get("coordinate")
        if not isinstance(coordinate, dict) or "volume" not in coordinate or set(coordinate) - {"volume", "chapter", "scene"} or any(type(value) is not int for value in coordinate.values()):
            return ["narrative_position.coordinate需要显式整数坐标"]
        try:
            StoryCoordinate.from_value(position["coordinate"])
        except (ValueError, TypeError, KeyError, OverflowError):
            return ["narrative_position.coordinate错误"]
    else:
        return ["narrative_position.kind错误"]
    return []


__all__ = [
    "DocumentRef", "DraftRef", "AuthorInputRef", "MemorySourceRef",
    "SOURCE_FINGERPRINT_PATTERN", "parse_source_ref", "validate_source_refs",
    "validate_position",
]
