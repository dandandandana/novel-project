"""Local, editable configuration for OpenAI-compatible model endpoints.

The model settings deliberately live outside the RAG library and workflow
outputs.  A small JSON file is easier for an author to inspect and edit than
environment variables, while :class:`ModelConfigStore` keeps persistence and
model construction in one place for the CLI and TUI.
"""

from __future__ import annotations

import json
import math
import os
import stat
import tempfile
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


def _path(value: str | Path | None) -> Path:
    return Path(value).expanduser() if value is not None else default_config_path()


def _safe_chmod(path: Path) -> None:
    """Best-effort owner-only permissions; Windows may ignore this mapping."""

    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        # ACLs are platform-specific.  A failure to tighten permissions must
        # not make an otherwise valid local configuration unusable.
        pass


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": CONFIG_SCHEMA_VERSION, "active": None, "profiles": {}}
    try:
        raw = path.read_text(encoding="utf-8-sig")
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        # Do not include the original exception: a malformed file can contain
        # an API key and should never echo file contents in a user-facing error.
        raise ModelConfigError(f"无法读取本地模型配置文件: {path}") from exc
    if not isinstance(value, Mapping):
        raise ModelConfigError(f"本地模型配置必须是 JSON 对象: {path}")
    return _normalize_document(value)


def _normalize_document(value: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize known envelope fields while retaining unknown future fields."""

    document = dict(value)
    document.setdefault("schema_version", CONFIG_SCHEMA_VERSION)
    profiles = document.get("profiles")
    if profiles is None:
        # A short-lived early format used ``models``.  Reading it keeps the
        # store forward/backward friendly without changing the canonical output.
        profiles = document.get("models", {})
    if isinstance(profiles, list):
        converted: dict[str, Any] = {}
        for item in profiles:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name") or item.get("id") or "").strip()
            if name:
                converted[name] = {key: val for key, val in item.items() if key not in {"name", "id"}}
        profiles = converted
    if not isinstance(profiles, Mapping):
        raise ModelConfigError("本地模型配置中的 profiles 必须是对象或数组")
    document["profiles"] = {str(name): dict(profile) for name, profile in profiles.items() if isinstance(profile, Mapping)}
    active = document.get("active", document.get("active_profile"))
    document["active"] = str(active).strip() if active is not None and str(active).strip() else None
    return document


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path = path.expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Keep the temporary file beside the target so os.replace is atomic on
        # the same filesystem (including Windows).
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                json.dump(value, temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            _safe_chmod(Path(temporary_name))
            os.replace(temporary_name, path)
            _safe_chmod(path)
        finally:
            if temporary_name:
                try:
                    Path(temporary_name).unlink(missing_ok=True)
                except OSError:
                    pass
    except OSError as exc:
        raise ModelConfigError(f"无法保存本地模型配置文件: {path}") from exc


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


class ModelConfigStore:
    """Read/write named model profiles in one local JSON document."""

    def __init__(self, path: str | Path | None = None):
        self.path = _path(path)

    def load(self) -> dict[str, Any]:
        return _read_json(self.path)

    def save(self, document: Mapping[str, Any] | None = None) -> dict[str, Any]:
        value = _normalize_document(document if document is not None else self.load())
        _write_json(self.path, value)
        return value

    def list_profiles(self) -> list[str]:
        return sorted(self.load().get("profiles", {}))

    # A short alias keeps the API pleasant for CLI/TUI callers.
    def list(self) -> list[str]:
        return self.list_profiles()

    def get(self, name: str | None = None) -> ModelProfile | None:
        document = self.load()
        profile_name = name if name is not None else document.get("active")
        if profile_name is None:
            return None
        profile_name = _text(profile_name, "profile name", allow_empty=False)
        value = document.get("profiles", {}).get(profile_name)
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ModelConfigError(f"本地模型配置 profile 无效: {profile_name}")
        return ModelProfile.from_mapping(profile_name, value)

    def set_profile(
        self,
        name: str,
        profile: ModelProfile | Mapping[str, Any] | None = None,
        **updates: Any,
    ) -> ModelProfile:
        profile_name = _text(name, "profile name", allow_empty=False)
        document = self.load()
        current = document.setdefault("profiles", {}).get(profile_name, {})
        if not isinstance(current, Mapping):
            current = {}
        if isinstance(profile, ModelProfile):
            replacement: dict[str, Any] = profile._stored_dict()
            replacement.update(updates)
        elif profile is None:
            replacement = dict(current)
            replacement.update(updates)
        elif isinstance(profile, Mapping):
            replacement = dict(current)
            replacement.update(profile)
            replacement.update(updates)
        else:
            raise ModelConfigError("profile 必须是 ModelProfile 或 JSON 对象")
        normalized = ModelProfile.from_mapping(profile_name, replacement)
        document["profiles"][profile_name] = normalized._stored_dict()
        self.save(document)
        return normalized

    # ``set`` is intentionally provided as the natural CRUD spelling.
    def set(self, name: str, profile: ModelProfile | Mapping[str, Any] | None = None, **updates: Any) -> ModelProfile:
        return self.set_profile(name, profile, **updates)

    def set_active(self, name: str | None) -> str | None:
        document = self.load()
        if name is None or not str(name).strip():
            document["active"] = None
        else:
            profile_name = _text(name, "profile name", allow_empty=False)
            if profile_name not in document.get("profiles", {}):
                raise ModelConfigError(f"找不到模型 profile: {profile_name}")
            document["active"] = profile_name
        self.save(document)
        return document["active"]

    def delete_profile(self, name: str) -> bool:
        profile_name = _text(name, "profile name", allow_empty=False)
        document = self.load()
        profiles = document.get("profiles", {})
        if profile_name not in profiles:
            return False
        del profiles[profile_name]
        if document.get("active") == profile_name:
            document["active"] = sorted(profiles)[0] if profiles else None
        self.save(document)
        return True

    def delete(self, name: str) -> bool:
        return self.delete_profile(name)

    def build_model(self, name: str | None = None, **overrides: Any) -> Any:
        profile = self.get(name)
        if profile is None:
            selected = name or self.load().get("active") or ""
            raise ModelConfigError(f"找不到模型 profile: {selected}")
        kwargs = profile.model_kwargs()
        kwargs.update(overrides)
        try:
            from .model_api import OpenAICompatibleModel

            return OpenAICompatibleModel(**kwargs)
        except Exception as exc:
            # Keep credentials and arbitrary endpoint details out of errors.
            if isinstance(exc, ModelConfigError):
                raise
            raise ModelConfigError("模型 profile 无效，无法创建 API 客户端") from exc

    # Alias used by callers that describe this operation as ``model``.
    model = build_model


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    return ModelConfigStore(path).load()


def save_config(document: Mapping[str, Any], path: str | Path | None = None) -> dict[str, Any]:
    return ModelConfigStore(path).save(document)


def list_profiles(path: str | Path | None = None) -> list[str]:
    return ModelConfigStore(path).list_profiles()


def get_config(name: str | None = None, path: str | Path | None = None) -> ModelProfile | None:
    return ModelConfigStore(path).get(name)


def set_config(
    name: str,
    profile: ModelProfile | Mapping[str, Any] | None = None,
    path: str | Path | None = None,
    **updates: Any,
) -> ModelProfile:
    return ModelConfigStore(path).set_profile(name, profile, **updates)


def set_active(name: str | None, path: str | Path | None = None) -> str | None:
    return ModelConfigStore(path).set_active(name)


def delete_config(name: str, path: str | Path | None = None) -> bool:
    return ModelConfigStore(path).delete_profile(name)


def model_from_config(name: str | None = None, path: str | Path | None = None, **overrides: Any) -> Any:
    return ModelConfigStore(path).build_model(name, **overrides)


# More explicit aliases for callers that prefer verb-based names.
load = load_config
save = save_config
get = get_config
set_profile = set_config
delete = delete_config


__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "DEFAULT_CONFIG_PATH",
    "ModelConfigError",
    "ModelConfigStore",
    "ModelProfile",
    "default_config_path",
    "load_config",
    "save_config",
    "list_profiles",
    "get_config",
    "set_config",
    "set_active",
    "delete_config",
    "model_from_config",
    "load",
    "save",
    "get",
    "set_profile",
    "delete",
]
