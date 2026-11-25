"""ui.json 配置加载与验证：有类型、有默认值、损坏时降级为默认。"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path.home() / ".novel-rag" / "ui.json"

_THEMES = frozenset({"neutral-dark", "safe"})
_COLOR_MODES = frozenset({"auto", "truecolor", "safe"})


@dataclass(frozen=True)
class UiConfig:
    max_buffer_lines: int = 2000
    preview_chars: int = 1200
    theme: str = "neutral-dark"
    color_mode: str = "auto"
    notification_level: str = "warning"
    progress_refresh_hz: float = 4.0


class UiConfigError(ValueError):
    pass


_CAMEL_ALIASES = {
    "maxBufferLines": "max_buffer_lines",
    "previewChars": "preview_chars",
    "colorMode": "color_mode",
    "notificationLevel": "notification_level",
    "progressRefreshHz": "progress_refresh_hz",
}


def _normalize_keys(raw: Any) -> Any:
    if not isinstance(raw, dict):
        return raw
    normalized: dict[str, Any] = {}
    for key, value in raw.items():
        name = _CAMEL_ALIASES.get(key, key)
        if name in normalized and name != key:
            raise UiConfigError(f"配置键重复：{key} 与既有键冲突")
        normalized[name] = value
    return normalized


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise UiConfigError(message)


def validate_ui_config(raw: Any) -> UiConfig:
    raw = _normalize_keys(raw)
    _check(isinstance(raw, dict), "配置必须是 JSON 对象")
    known = {item.name for item in fields(UiConfig)}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise UiConfigError("未知配置键: " + ", ".join(unknown))
    values: dict[str, Any] = {}
    for item in fields(UiConfig):
        if item.name not in raw:
            continue
        value = raw[item.name]
        name = item.name
        if name in {"max_buffer_lines", "preview_chars"}:
            _check(isinstance(value, int) and not isinstance(value, bool) and value > 0,
                   f"{name} 必须是正整数")
        elif name == "progress_refresh_hz":
            _check(isinstance(value, (int, float)) and not isinstance(value, bool)
                   and 0.5 <= float(value) <= 30,
                   "progress_refresh_hz 必须在 0.5–30 之间")
        elif name == "theme":
            _check(value in _THEMES, f"theme 必须是 {'/'.join(sorted(_THEMES))}")
        elif name == "color_mode":
            _check(value in _COLOR_MODES, f"color_mode 必须是 {'/'.join(sorted(_COLOR_MODES))}")
        elif name == "notification_level":
            _check(value in ("info", "warning", "error"),
                   "notification_level 必须是 info/warning/error")
        values[name] = value
    return UiConfig(**values)


def load_ui_config(path: Path | None = None) -> tuple[UiConfig, list[str]]:
    """返回 (生效配置, 告警列表)；缺失/损坏/非法一律回退默认并给出告警。"""

    warnings: list[str] = []
    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not target.is_file():
        return UiConfig(), warnings
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        config = validate_ui_config(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, UiConfigError) as exc:
        warnings.append(f"ui.json 无效，已使用默认配置：{exc}")
        return UiConfig(), warnings
    return config, warnings
