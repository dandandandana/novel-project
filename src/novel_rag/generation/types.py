"""Error classes, type aliases, and constants for generation.

``GenerationResult`` intentionally lives in :mod:`novel_rag.generation_schema`
(as a dataclass) rather than here, so ``asdict()`` serialisation and the
schema stay in one place.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from ..contracts.references import (
    AuthorInputRef,
    DocumentRef,
    DraftRef,
    MemorySourceRef,
    parse_source_ref,
)
from ..identity import GraphKey, StoryCoordinate


Model = Callable[[str, dict[str, Any]], str | Mapping[str, Any]]


@dataclass(frozen=True)
class MemoryCommit:
    """依赖：纯dataclass。输入：规范批次、回执和可选效力签名。输出：提交值。实现：签名独立于持久批次，None保留当前签名。"""

    batch: dict
    result: dict
    effect_signature: dict | None = None


STAGE_INSTRUCTIONS = {
    "normalize": "宽松理解作者大纲。保留硬事件、顺序、主体、结果、自由空间和歧义；每个结果用 source_clause_ids 对应原文条目，不改善、替换或否决作者剧情。",
    "reference_profile": "只提取可迁移的底层写作能力和禁止照搬项；不得提出剧情或角色行为。",
    "decide_behavior": "只依据作者事件、人物与当前状态决定角色怎样执行。不得接触 Reference 或文风，不得否决作者事件。",
    "derive_result": "根据已经确定的行为产生现实结果、观察者信息和状态增量。不得润色正文或改变作者事件。",
    "render_prose": "把已经确定的 Behavior、Result 和 State 写成小说正文。可以使用作者偏好与抽象 Reference，但不得改变语义。",
    "polish": "依据 Reference 改善表达，但不得改变事件、顺序、主体、结果、认知、状态或结尾。",
    "validate": "检查作者硬事件、顺序、主体、结果、连续性、自然停点、可续状态及表达边界。格式小问题只警告。",
    "repair": "只修复给定问题，保持作者合同和已成立语义不变。不得新增重大事件或删除硬事件。",
}


@dataclass(frozen=True)
class NarrativeCursor:
    """正式来源游标端点及可选叙事坐标。"""

    endpoint: Literal["before", "after"]
    coordinate: StoryCoordinate | None = None


@dataclass(frozen=True)
class RunBinding:
    """单次运行固定的纯输入与来源合同。"""

    scope: GraphKey
    task_kind: str
    narrative_cursor: NarrativeCursor
    base_ref: DocumentRef | DraftRef | None
    draft_branch: str
    target_coordinate: StoryCoordinate | None = None
    selected_parent_checkpoint: str | None = None
    baseline_source_refs: tuple[DocumentRef, ...] = ()
    input_snapshot_refs: tuple[AuthorInputRef, ...] = ()
    output_mode: str = "full_body"
    initial_memory_revision: int = 0

    def as_dict(self) -> dict[str, Any]:
        """依赖：dataclasses.asdict。输入：当前绑定。输出：JSON 友好映射。实现：递归展开所有纯值字段。"""

        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RunBinding:
        """依赖：parse_source_ref 与 identity 纯类型。输入：绑定映射。输出：重建后的 RunBinding。实现：恢复嵌套值和固定来源元组。"""

        values = dict(value)
        raw_scope = values["scope"]
        if not isinstance(raw_scope, GraphKey):
            values["scope"] = GraphKey(**raw_scope)

        raw_cursor = values["narrative_cursor"]
        if not isinstance(raw_cursor, NarrativeCursor):
            raw_coordinate = raw_cursor.get("coordinate")
            coordinate = (
                raw_coordinate
                if isinstance(raw_coordinate, StoryCoordinate)
                else StoryCoordinate.from_value(raw_coordinate)
                if raw_coordinate is not None
                else None
            )
            values["narrative_cursor"] = NarrativeCursor(
                endpoint=raw_cursor["endpoint"],
                coordinate=coordinate,
            )

        raw_target = values.get("target_coordinate")
        if raw_target is not None and not isinstance(raw_target, StoryCoordinate):
            values["target_coordinate"] = StoryCoordinate.from_value(raw_target)

        raw_base = values.get("base_ref")
        if isinstance(raw_base, Mapping):
            raw_base = parse_source_ref(raw_base)
        if raw_base is not None and not isinstance(raw_base, (DocumentRef, DraftRef)):
            raise ValueError("base_ref 必须是 document、draft 或空值")
        values["base_ref"] = raw_base

        baseline_refs = tuple(
            parse_source_ref(item) if isinstance(item, Mapping) else item
            for item in values.get("baseline_source_refs", ())
        )
        if any(not isinstance(item, DocumentRef) for item in baseline_refs):
            raise ValueError("baseline_source_refs 只能包含 document 引用")
        values["baseline_source_refs"] = baseline_refs

        input_refs = tuple(
            parse_source_ref(item) if isinstance(item, Mapping) else item
            for item in values.get("input_snapshot_refs", ())
        )
        if any(not isinstance(item, AuthorInputRef) for item in input_refs):
            raise ValueError("input_snapshot_refs 只能包含 author_input 引用")
        values["input_snapshot_refs"] = input_refs
        return cls(**values)


class GenerationError(RuntimeError):
    pass


class PreferenceRequired(GenerationError):
    def __init__(self, path: Path):
        self.path = path
        super().__init__(f'请先填写本书作者偏好文件（也可以只写\u201c默认\u201d）: {path}')
