"""转录渲染：按行前缀正则着色的 Lexer（公开 API，无私有 hack）。"""

from __future__ import annotations

import re

from prompt_toolkit.document import Document
from prompt_toolkit.lexers import Lexer

_HEADER_RE = re.compile(r"^(?P<ts>\d{1,2}:\d{2}) (?P<arrow>❯)(?P<rest>.*)$")
_PREFIX_STYLES = (
    ("✗", "class:error"),
    ("⏱", "class:error"),
    ("⚠", "class:warning"),
    ("✓", "class:success"),
    ("⊘", "class:muted"),
    ("●", "class:progress"),
    ("⟳", "class:progress"),
)


def _fragments_for_line(line: str) -> list[tuple[str, str]]:
    match = _HEADER_RE.match(line)
    if match:
        return [
            ("class:muted", match.group("ts") + " "),
            ("class:input-prefix", match.group("arrow") + " "),
            ("class:command", match.group("rest").lstrip()),
        ]
    stripped = line.lstrip()
    for symbol, style in _PREFIX_STYLES:
        if stripped.startswith(symbol):
            lead = len(line) - len(stripped)
            return [
                ("", line[:lead]),
                (style, symbol),
                ("", line[lead + len(symbol):]),
            ]
    if line.startswith("      ↳"):
        return [("class:muted", line)]
    if line.startswith("   ·"):
        return [("class:muted", line)]
    if "▓" in line or "░" in line:
        return [("class:progress", line)]
    return [("", line)]


class TranscriptLexer(Lexer):
    """把 BlockStore 文本按前缀映射为样式片段。"""

    def lex_document(self, document: Document):
        lines = document.lines

        def get_line(line_number: int):
            return _fragments_for_line(lines[line_number])

        return get_line
