from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .identity import StoryCoordinate
from .layout import STORY_DATA_DIRS, SYSTEM_DIRS

ROOT = Path(__file__).resolve().parents[1]
LIBRARY_ROOT = ROOT / "novel-rag"
INDEX_ROOT = LIBRARY_ROOT / "index"
# Kept as a compatibility alias for callers that only need the index directory.
INDEX_PATH = INDEX_ROOT

TARGET_COMMON_DIRS = ("canon", "registry")
TARGET_TIMELINE_DIRS = (
    "canon",
    "history",
    "outline",
    "character-state",
    "world-state",
    "feedback",
    "summaries",
    "system-overrides",
    "registry",
)
DEFAULT_TIMELINE_ID = "main"

DOCUMENT_DIRS = (*STORY_DATA_DIRS, *SYSTEM_DIRS)

SUMMARY_DOCUMENT_TYPES = {
    "summary",
    "scene-summary",
    "chapter-summary",
    "volume-summary",
}
SUMMARY_OWNERSHIPS = {"auto", "user"}
SUMMARY_REQUIRED_METADATA = ("ownership",)

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
    *SUMMARY_DOCUMENT_TYPES,
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
    *SUMMARY_DOCUMENT_TYPES,
}
STATUSES = {"active", "canon", "draft", "deprecated", "alternate", "archived", "runtime"}
DEFAULT_SEARCH_STATUSES = ("active", "canon")
REQUIRED_METADATA = ("story_id", "timeline_id", "document_type", "title", "status", "version")

_SOURCE_FINGERPRINT_PATTERN = re.compile(r"sha256:[0-9a-fA-F]{64}")
_COVERAGE_PATTERN = re.compile(
    r"^(?:volume-\d+(?:(?:[/\\-])chapter-\d+(?:(?:[/\\-])scene-\d+)?)?"
    r"|chapter-\d+(?:(?:[/\\-])scene-\d+)?|scene-\d+)$",
    re.IGNORECASE,
)


def validate_summary_metadata(metadata: Mapping[str, Any]) -> list[str]:
    """Validate lifecycle metadata shared by AI and user summaries.

    ``ownership`` is the only mandatory summary-specific field for backward
    compatibility with existing generated summaries. Optional coverage,
    fingerprint, revision, and generator fields are validated whenever they
    are present.
    """

    document_type = str(metadata.get("document_type") or "")
    if document_type not in SUMMARY_DOCUMENT_TYPES:
        return []

    errors: list[str] = []
    ownership = metadata.get("ownership")
    if ownership in (None, ""):
        errors.append("summary 必须包含 metadata.ownership")
    elif ownership not in SUMMARY_OWNERSHIPS:
        errors.append(
            f"summary metadata.ownership 必须为 'auto' 或 'user': {ownership!r}"
        )

    if "covers_documents" in metadata:
        values = metadata.get("covers_documents")
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
            errors.append("summary metadata.covers_documents 必须是文档 ID 列表")
        elif any(not isinstance(item, str) or not item.strip() for item in values):
            errors.append("summary metadata.covers_documents 只能包含非空字符串")

    if "covers_through" in metadata:
        value = metadata.get("covers_through")
        if value in (None, ""):
            errors.append("summary metadata.covers_through 不能为空")
        elif isinstance(value, str) and not _COVERAGE_PATTERN.fullmatch(value.strip()):
            errors.append(f"summary metadata.covers_through 无效: {value!r}")
        else:
            if not isinstance(value, str):
                try:
                    StoryCoordinate.from_value(value)
                except ValueError as exc:
                    errors.append(f"summary metadata.covers_through 无效: {exc}")

    if "source_fingerprint" in metadata:
        fingerprint = metadata.get("source_fingerprint")
        if not isinstance(fingerprint, str) or not _SOURCE_FINGERPRINT_PATTERN.fullmatch(fingerprint):
            errors.append(
                "summary metadata.source_fingerprint 必须是 sha256:<64位十六进制>"
            )

    if "revision" in metadata:
        revision = metadata.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            errors.append("summary metadata.revision 必须是正整数")

    if "generated_by" in metadata:
        generated_by = metadata.get("generated_by")
        if not isinstance(generated_by, str) or not generated_by.strip():
            errors.append("summary metadata.generated_by 必须是非空字符串")

    return errors
