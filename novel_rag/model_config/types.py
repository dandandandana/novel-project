"""Data types and field validators for local model configuration.

This module holds everything that describes *what* a model profile is:
the error type, schema constants, field validators, and the immutable
:class:`ModelProfile` dataclass.  Persistence lives in ``store.py``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ModelConfigError(RuntimeError):
    """A safe, user-facing error while reading or writing model settings."""


DEFAULT_CONFIG_PATH = Path.home() / ".novel-rag" / "model-api.json"
CONFIG_SCHEMA_VERSION = 1

_KNOWN_FIELDS = {
    "base_url",
    "model",
    "mode",
    "api_key",
    "timeout",
    "retries",
    "max_output_tokens",
    "no_auth",
}
_DEFAULT_PROFILE: dict[str, Any] = {
    "base_url": "https://api.openai.com/v1",
    "model": "",
    "mode": "responses",
    "api_key": None,
    "timeout": 300.0,
    "retries": 2,
    "max_output_tokens": None,
    "no_auth": False,
}


def default_config_path() -> Path:
    """Return the user-local default path (never under ``novel-rag``/outputs)."""

    return DEFAULT_CONFIG_PATH


def _text(value: Any, field_name: str, *, allow_empty: bool = True) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ModelConfigError(f"模型配置字段 {field_name} 必须是文本")
    result = value.strip()
    if not allow_empty and not result:
        raise ModelConfigError(f"模型配置字段 {field_name} 不能为空")
    return result


def _number(value: Any, field_name: str, *, integer: bool = False, minimum: float = 0.0) -> int | float:
    if isinstance(value, bool):
        raise ModelConfigError(f"模型配置字段 {field_name} 数值无效")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ModelConfigError(f"模型配置字段 {field_name} 数值无效") from exc
    if not math.isfinite(number) or number < minimum or (integer and number != int(number)):
        raise ModelConfigError(f"模型配置字段 {field_name} 数值无效")
    return int(number) if integer else number


def _boolean(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"0", "false", "no", "off", ""}:
        return False
    raise ModelConfigError(f"模型配置字段 {field_name} 必须是布尔值")


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """A named model endpoint.

    ``api_key`` and unknown ``extras`` are intentionally omitted from repr so
    printing a profile cannot disclose credentials.
    """

    name: str
    base_url: str = _DEFAULT_PROFILE["base_url"]
    model: str = _DEFAULT_PROFILE["model"]
    mode: str = _DEFAULT_PROFILE["mode"]
    api_key: str | None = field(default=None, repr=False)
    timeout: float = _DEFAULT_PROFILE["timeout"]
    retries: int = _DEFAULT_PROFILE["retries"]
    max_output_tokens: int | None = None
    no_auth: bool = False
    extras: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_mapping(cls, name: str, value: Mapping[str, Any]) -> "ModelProfile":
        profile_name = _text(name, "profile name", allow_empty=False)
        data = dict(value)
        base_url = _text(data.get("base_url", _DEFAULT_PROFILE["base_url"]), "base_url")
        model = _text(data.get("model", _DEFAULT_PROFILE["model"]), "model")
        mode = _text(data.get("mode", _DEFAULT_PROFILE["mode"]), "mode")
        if mode not in {"responses", "chat"}:
            raise ModelConfigError("模型配置字段 mode 必须是 responses 或 chat")
        key = data.get("api_key")
        if key is not None and not isinstance(key, str):
            raise ModelConfigError("模型配置字段 api_key 必须是文本")
        timeout = float(_number(data.get("timeout", _DEFAULT_PROFILE["timeout"]), "timeout", minimum=0.000001))
        retries = int(_number(data.get("retries", _DEFAULT_PROFILE["retries"]), "retries", integer=True))
        max_tokens = data.get("max_output_tokens", _DEFAULT_PROFILE["max_output_tokens"])
        if max_tokens is not None:
            max_tokens = int(_number(max_tokens, "max_output_tokens", integer=True, minimum=1))
        no_auth = _boolean(data.get("no_auth", _DEFAULT_PROFILE["no_auth"]), "no_auth")
        extras = {key: val for key, val in data.items() if key not in _KNOWN_FIELDS}
        return cls(
            name=profile_name,
            base_url=base_url,
            model=model,
            mode=mode,
            api_key=key,
            timeout=timeout,
            retries=retries,
            max_output_tokens=max_tokens,
            no_auth=no_auth,
            extras=extras,
        )

    def to_dict(self, *, include_api_key: bool = False) -> dict[str, Any]:
        """Return an editable mapping, redacting the key by default."""

        value: dict[str, Any] = dict(self.extras)
        value.update(
            {
                "base_url": self.base_url,
                "model": self.model,
                "mode": self.mode,
                "timeout": self.timeout,
                "retries": self.retries,
                "max_output_tokens": self.max_output_tokens,
                "no_auth": self.no_auth,
            }
        )
        if include_api_key:
            value["api_key"] = self.api_key
        else:
            value["api_key"] = "***" if self.api_key else None
        return value

    def _stored_dict(self) -> dict[str, Any]:
        return self.to_dict(include_api_key=True)

    def model_kwargs(self) -> dict[str, Any]:
        """Arguments accepted by :class:`OpenAICompatibleModel`."""

        return {
            "base_url": self.base_url,
            "model": self.model,
            "mode": self.mode,
            "api_key": None if self.no_auth else self.api_key,
            "timeout": self.timeout,
            "retries": self.retries,
            "max_output_tokens": self.max_output_tokens,
        }
