"""语义主题 token：hex 全色与 ANSI safe 两套，颜色永远伴随符号冗余。"""

from __future__ import annotations

from prompt_toolkit.styles import Style

from .config import UiConfig

_HEX = {
    "text": "#c6c6c6",
    "muted": "#7a7a7a",
    "dim": "#585858",
    "accent": "#5fd7d7",
    "command": "#e4e4e4 bold",
    "success": "#87af87",
    "warning": "#d7af5f",
    "error": "#d75f5f bold",
    "progress": "#5f87af",
    "border": "#444444",
    "input-prefix": "#5fd7d7 bold",
    "badge": "#d7af5f bold",
    "header": "#9e9e9e",
}

_SAFE = {
    "text": "",
    "muted": "ansibrightblack",
    "dim": "ansiblack",
    "accent": "ansicyan",
    "command": "ansiwhite bold",
    "success": "ansigreen",
    "warning": "ansiyellow",
    "error": "ansired bold",
    "progress": "ansiblue",
    "border": "ansibrightblack",
    "input-prefix": "ansicyan bold",
    "badge": "ansiyellow bold",
    "header": "ansiwhite",
}

def build_style(config: UiConfig) -> Style:
    palette = dict(_SAFE if config.color_mode == "safe" or config.theme == "safe" else _HEX)
    palette.update({
        "dialog.body": palette["text"],
        "dialog shadow": palette["border"],
        "dialog frame.border": palette["border"],
        "button.text": palette["command"],
        "button.arrow": palette["accent"],
        "search.text": palette["muted"],
        "search.selected": palette["accent"],
    })
    return Style.from_dict(palette)


def style_classes() -> tuple[str, ...]:
    return tuple(_HEX)
