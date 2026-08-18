"""Local, editable configuration for OpenAI-compatible model endpoints.

The model settings deliberately live outside the RAG library and workflow
outputs.  A small JSON file is easier for an author to inspect and edit than
environment variables, while :class:`ModelConfigStore` keeps persistence and
model construction in one place for the CLI and TUI.

The package is split by responsibility: ``types`` holds the error type,
schema constants, and the immutable :class:`ModelProfile`; ``store`` holds
the JSON persistence layer and the CRUD helpers.
"""

from __future__ import annotations

from .types import (
    CONFIG_SCHEMA_VERSION,
    DEFAULT_CONFIG_PATH,
    ModelConfigError,
    ModelProfile,
    default_config_path,
)
from .store import (
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
