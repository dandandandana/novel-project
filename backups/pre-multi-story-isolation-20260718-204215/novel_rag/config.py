from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBRARY_ROOT = ROOT / "novel-rag"
INDEX_PATH = LIBRARY_ROOT / "index" / "rag.db"

DOCUMENT_DIRS = (
    "canon",
    "history",
    "outline",
    "character-state",
    "world-state",
    "rules",
    "judgment",
    "generator",
    "audit",
    "style-audit",
    "feedback",
)

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
STATUSES = {"active", "canon", "draft", "deprecated", "alternate", "archived", "runtime"}
DEFAULT_SEARCH_STATUSES = ("active", "canon")
REQUIRED_METADATA = ("story_id", "timeline_id", "document_type", "title", "status", "version")
