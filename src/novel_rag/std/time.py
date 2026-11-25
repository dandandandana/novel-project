"""共同UTC时间格式，不包含运行或资料版本策略。"""
from __future__ import annotations

from datetime import datetime, timezone


def utc_now_iso() -> str:
    """依赖：datetime。输入：无。输出：UTC秒级ISO字符串。实现：去微秒并保留既有Z后缀。"""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
