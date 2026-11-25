"""命令块环形缓冲（BlockStore）：定格块 + 活动行原位刷新，线程安全。"""

from __future__ import annotations

import threading
from datetime import datetime

STATUS_SYMBOLS = {
    "running": "●",
    "success": "✓",
    "warning": "⚠",
    "failure": "✗",
    "cancelled": "⊘",
    "timeout": "⏱",
}

STATUS_WORDS = {
    "running": "RUN",
    "success": "OK",
    "warning": "WARN",
    "failure": "FAIL",
    "cancelled": "CXL",
    "timeout": "TMO",
}


def format_status_line(status: str, label: str, detail: str = "",
                       elapsed: float | None = None,
                       *, indent: bool = True) -> str:
    symbol = STATUS_SYMBOLS.get(status, "?")
    word = STATUS_WORDS.get(status, "??")
    parts = [f"{symbol} {word} {label}"]
    if detail:
        parts.append(detail)
    if elapsed is not None:
        parts.append(f"{elapsed:.1f}s")
    prefix = "   " if indent else ""
    return prefix + "  ".join(parts)


class BlockStore:
    """按行存储转录内容；超限丢弃最旧整块；dirty 标记驱动重绘。"""

    def __init__(self, max_lines: int = 2000) -> None:
        self._max_lines = max(8, max_lines)
        self._lock = threading.Lock()
        self._lines: list[str] = []
        self._blocks: list[dict] = []
        self._live: str | None = None
        self._seq = 0
        self._dirty = True

    @property
    def dirty(self) -> bool:
        return self._dirty

    def mark_clean(self) -> None:
        self._dirty = False

    @property
    def line_count(self) -> int:
        return len(self._lines)

    def begin_block(self, echo: str, *, ts: str | None = None) -> int:
        """新命令块头：``HH:MM ❯ echo``；返回块序号。"""
        with self._lock:
            self._seq += 1
            seq = self._seq
            stamp = ts or datetime.now().strftime("%H:%M")
            self._lines.append(f"{stamp} ❯ {echo}")
            self._blocks.append({"seq": seq, "ts": stamp, "echo": echo,
                                 "start": len(self._lines) - 1})
            self._trim_locked()
            self._dirty = True
            return seq

    def append_line(self, text: str, *, indent: bool = True) -> None:
        prefix = "   " if indent else ""
        with self._lock:
            for raw in str(text).splitlines() or [""]:
                body = raw.rstrip("\r")
                self._lines.append(prefix + body if (indent and body) else body)
                self._trim_locked()
            self._dirty = True

    def set_live_line(self, text: str | None) -> None:
        with self._lock:
            if self._live != text:
                self._live = text
                self._dirty = True

    def finish_live(self, final_text: str | None = None) -> None:
        with self._lock:
            if final_text:
                self._lines.append(final_text)
            self._live = None
            self._dirty = True

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()
            self._blocks.clear()
            self._live = None
            self._dirty = True

    def render_text(self) -> str:
        with self._lock:
            body = "\n".join(self._lines)
            if self._live is not None:
                return body + ("\n" + self._live if body else self._live)
            return body

    def last_fail_index(self) -> int | None:
        with self._lock:
            for index in range(len(self._lines) - 1, -1, -1):
                if "✗ FAIL" in self._lines[index]:
                    return index
            return None

    def _trim_locked(self) -> None:
        while len(self._lines) > self._max_lines and len(self._blocks) > 1:
            drop_until = self._blocks[1]["start"]
            del self._lines[:drop_until]
            del self._blocks[0]
            for block in self._blocks:
                block["start"] -= drop_until
