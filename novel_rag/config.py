from __future__ import annotations

from pathlib import Path

from .layout import STORY_DATA_DIRS, SYSTEM_DIRS

ROOT = Path(__file__).resolve().parents[1]
LIBRARY_ROOT = ROOT / "novel-rag"
INDEX_ROOT = LIBRARY_ROOT / "index"
# Kept as a compatibility alias for callers that only need the index directory.
INDEX_PATH = INDEX_ROOT

DOCUMENT_DIRS = (*STORY_DATA_DIRS, *SYSTEM_DIRS)

DOCUMENT_TYPES = {
    "canon",
    "history",
    "outline",
    "character_state",
    "world_state",
    "rule",
    "judgment_spec",
    "generator_spec",
    "audit_spec",
    "style_audit",
    "style_sample",
    "feedback",
    "registry",
    "runtime_artifact",
}
MODULE_TYPES = {"ruler", "judgment", "generator", "audit", "style", "none"}
MODULE_DOCUMENT_TYPES = {
    "rule": "ruler",
    "judgment_spec": "judgment",
    "generator_spec": "generator",
    "audit_spec": "audit",
}
MODULE_MAP_DOCUMENT_TYPES = {*MODULE_DOCUMENT_TYPES, "style_audit"}
SYSTEM_DOCUMENT_TYPES = {*MODULE_DOCUMENT_TYPES, "style_audit", "style_sample"}
STORY_DOCUMENT_TYPES = {
    "canon",
    "history",
    "outline",
    "character_state",
    "world_state",
    "feedback",
    *SYSTEM_DOCUMENT_TYPES,
}
STATUSES = {"active", "canon", "draft", "deprecated", "alternate", "archived", "runtime"}
DEFAULT_SEARCH_STATUSES = ("active", "canon")
REQUIRED_METADATA = ("story_id", "timeline_id", "document_type", "title", "status", "version")
