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

from ..model_api import ModelAPIError, normalize_mode, validate_context_policy


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
    "context_window_tokens",
    "output_reserve_tokens",
    "max_turns",
    "prompt_cache_key",
    "prompt_cache_retention",
    "provider_compaction",
}
_DEFAULT_PROFILE: dict[str, Any] = {
    "base_url": "https://api.openai.com/v1",
    "model": "",
    # 用户可见默认协议是 OpenAI chat/completions；normalize_mode 会把
    # completions/openai-completions 等别名归一化为规范存储值 "chat"。
    "mode": "chat",
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
    """依赖：math/安全配置错误。输入：数值、字段及范围。输出：规范数或错误。实现：拒绝bool、非有限及溢出值，保留既有字符串转换。"""
    if isinstance(value, bool):
        raise ModelConfigError(f"模型配置字段 {field_name} 数值无效")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
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
    context_window_tokens: int | None = None
    output_reserve_tokens: int | None = None
    max_turns: int | None = None
    prompt_cache_key: str | None = field(default=None, repr=False)
    prompt_cache_retention: str | None = None
    provider_compaction: bool = False

    @classmethod
    def from_mapping(cls, name: str, value: Mapping[str, Any]) -> "ModelProfile":
        """依赖：既有字段转换/共同policy校验。输入：profile映射。输出：纯配置或安全错误。实现：新选项显式转换，保留未知extras而不猜模型能力。"""
        profile_name = _text(name, "profile name", allow_empty=False)
        data = dict(value)
        base_url = _text(data.get("base_url", _DEFAULT_PROFILE["base_url"]), "base_url")
        model = _text(data.get("model", _DEFAULT_PROFILE["model"]), "model")
        mode = normalize_mode(data.get("mode", _DEFAULT_PROFILE["mode"]))
        key = data.get("api_key")
        if key is not None and not isinstance(key, str):
            raise ModelConfigError("模型配置字段 api_key 必须是文本")
        timeout = float(_number(data.get("timeout", _DEFAULT_PROFILE["timeout"]), "timeout", minimum=0.000001))
        retries = int(_number(data.get("retries", _DEFAULT_PROFILE["retries"]), "retries", integer=True))
        max_tokens = data.get("max_output_tokens", _DEFAULT_PROFILE["max_output_tokens"])
        if max_tokens is not None:
            max_tokens = int(_number(max_tokens, "max_output_tokens", integer=True, minimum=1))
        no_auth = _boolean(data.get("no_auth", _DEFAULT_PROFILE["no_auth"]), "no_auth")
        options = {}
        for option, minimum in (("context_window_tokens", 1), ("output_reserve_tokens", 0), ("max_turns", 1)):
            raw = data.get(option)
            options[option] = int(_number(raw, option, integer=True, minimum=minimum)) if raw is not None else None
        for option in ("prompt_cache_key", "prompt_cache_retention"):
            raw = data.get(option)
            options[option] = _text(raw, option, allow_empty=False) if raw is not None else None
        options["provider_compaction"] = _boolean(data.get("provider_compaction", False), "provider_compaction")
        try:
            validate_context_policy(**options)
        except ModelAPIError as exc:
            raise ModelConfigError(str(exc)) from exc
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
            **options,
        )

    def to_dict(self, *, include_api_key: bool = False) -> dict[str, Any]:
        """依赖：已校验字段/extras。输入：是否含凭证。输出：可编辑映射。实现：默认脱敏，新增None/off字段省略以保旧形状。"""

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
        for option in ("context_window_tokens", "output_reserve_tokens", "max_turns", "prompt_cache_key", "prompt_cache_retention"):
            setting = getattr(self, option)
            if setting is not None:
                value[option] = setting
        if self.provider_compaction:
            value["provider_compaction"] = True
        if include_api_key:
            value["api_key"] = self.api_key
        else:
            value["api_key"] = "***" if self.api_key else None
        return value

    def _stored_dict(self) -> dict[str, Any]:
        return self.to_dict(include_api_key=True)

    def model_kwargs(self) -> dict[str, Any]:
        """依赖：OpenAICompatibleModel显式配置。输入：当前profile。输出：客户端参数。实现：保留legacy参数，只转发实际配置的新策略。"""

        result = {
            "base_url": self.base_url,
            "model": self.model,
            "mode": self.mode,
            "api_key": None if self.no_auth else self.api_key,
            "timeout": self.timeout,
            "retries": self.retries,
            "max_output_tokens": self.max_output_tokens,
        }
        for option in ("context_window_tokens", "output_reserve_tokens", "max_turns", "prompt_cache_key", "prompt_cache_retention"):
            setting = getattr(self, option)
            if setting is not None:
                result[option] = setting
        if self.provider_compaction:
            result["provider_compaction"] = True
        return result
