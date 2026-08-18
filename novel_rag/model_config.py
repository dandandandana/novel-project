"""Compatibility shim: re-exports from the ``model_config`` package."""

from __future__ import annotations

from .model_config.types import (
    CONFIG_SCHEMA_VERSION,
    DEFAULT_CONFIG_PATH,
    ModelConfigError,
    ModelProfile,
    default_config_path,
)
from .model_config.store import (
    ModelConfigStore,
    load_config,
    save_config,
    list_profiles,
    get_config,
    set_config,
    set_active,
    delete_config,
    model_from_config,
    load,
    save,
    get,
    set_profile,
    delete,
)

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
