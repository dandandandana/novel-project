"""Novel scene generation pipeline.

The generation pipeline takes a request, outline, author preferences, and
reference material, then produces a draft through staged model calls:
normalize, reference_profile, decide_behavior, derive_result, render_prose,
polish, validate, and repair.
"""

from __future__ import annotations

from ..generation_schema import GenerationResult
from .types import GenerationError, PreferenceRequired, Model, STAGE_INSTRUCTIONS
from .helpers import (
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
from .pipeline import generate

__all__ = [
    "GenerationError",
    "PreferenceRequired",
    "Model",
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