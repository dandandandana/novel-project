"""Error classes, type aliases, and constants for generation.

``GenerationResult`` intentionally lives in :mod:`novel_rag.generation_schema`
(as a dataclass) rather than here, so ``asdict()`` serialisation and the
schema stay in one place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping


Model = Callable[[str, dict[str, Any]], str | Mapping[str, Any]]


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


class GenerationError(RuntimeError):
    pass


class PreferenceRequired(GenerationError):
    def __init__(self, path: Path):
        self.path = path
        super().__init__(f'请先填写本书作者偏好文件（也可以只写\u201c默认\u201d）: {path}')