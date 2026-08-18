from __future__ import annotations

import re
from pathlib import Path


LAYOUT_VERSION = "2.0"
SHARED_STORY_ID = "__shared__"
SHARED_TIMELINE_ID = "global"

STORY_DATA_DIRS = (
    "canon",
    "history",
    "outline",
    "character-state",
    "world-state",
    "feedback",
)

SYSTEM_DIRS = (
    "rules",
    "judgment",
    "generator",
    "audit",
    "style-audit",
)

STORY_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def registry_root(library_root: Path) -> Path:
    return library_root / "registry"


def shared_root(library_root: Path) -> Path:
    return library_root / "shared"


def shared_registry_root(library_root: Path) -> Path:
    return shared_root(library_root) / "registry"


def stories_root(library_root: Path) -> Path:
    return library_root / "stories"


def story_root(library_root: Path, story_id: str) -> Path:
    validate_story_id(story_id)
    return stories_root(library_root) / story_id


def story_registry_root(library_root: Path, story_id: str) -> Path:
    return story_root(library_root, story_id) / "registry"


def index_root(library_root: Path) -> Path:
    return library_root / "index"


def shared_index_path(index_directory: Path) -> Path:
    return index_directory / "shared.db"


def story_index_path(index_directory: Path, story_id: str) -> Path:
    validate_story_id(story_id)
    return index_directory / "stories" / f"{story_id}.db"


def validate_story_id(story_id: str) -> None:
    if not STORY_ID_PATTERN.fullmatch(story_id):
        raise ValueError("story_id 只能使用小写字母、数字和连字符，且必须以字母或数字开头")


def relative_parts(library_root: Path, path: Path) -> tuple[str, ...]:
    return path.resolve().relative_to(library_root.resolve()).parts


def classify_document_path(library_root: Path, path: Path) -> tuple[str, str | None]:
    parts = relative_parts(library_root, path)
    if len(parts) >= 2 and parts[0] == "shared" and parts[1] in SYSTEM_DIRS:
        return "shared", None
    if len(parts) >= 3 and parts[0] == "stories":
        story_id = parts[1]
        if parts[2] in STORY_DATA_DIRS or parts[2] == "system-overrides":
            return "story", story_id
    return "unknown", None
