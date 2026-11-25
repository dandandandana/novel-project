"""既有紧凑JSON编码；其他持久化身份不得隐式改用此格式。"""
from __future__ import annotations

import json
from typing import Any


def json_text(value: Any) -> str:
    """依赖：json。输入：可编码值。输出：排序紧凑JSON。实现：保留Unicode及default=str的原兼容策略。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
