"""Compatibility shim: re-exports from the ``generation`` package."""

from __future__ import annotations

from .generation.types import GenerationError, PreferenceRequired, Model, STAGE_INSTRUCTIONS
from .generation import GenerationResult
from .generation.helpers import (
    author_preferences_path,
    read_author_preferences,
    build_contract,
    retrieve_context,
    build_reference_profiles,
    load_scene_state,
    execute_scene,
    validate_draft,
    _payload,
    _safe_task_id,
)
from .generation.pipeline import generate

__all__ = [
    "GenerationError",
    "PreferenceRequired",
    "Model",
    "STAGE_INSTRUCTIONS",
    "GenerationResult",
    "author_preferences_path",
    "read_author_preferences",
    "build_contract",
    "retrieve_context",
    "build_reference_profiles",
    "load_scene_state",
    "execute_scene",
    "validate_draft",
    "_payload",
    "_safe_task_id",
    "generate",
]