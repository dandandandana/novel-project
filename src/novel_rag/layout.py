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
    """Return the first catalog registry root for compatibility callers.

    The plural catalog resolver is authoritative.  This singular spelling is
    retained for external callers that still expect one ``Path`` and does not
    create or select a second legacy-only layout.
    """

    roots = story_registry_roots(library_root, story_id)
    existing = tuple(root for root in roots if root.is_dir())
    # Preserve the historical legacy destination for a legacy-only library;
    # once a target root exists, target-first ordering wins.
    return existing[0] if existing else roots[-1]


def story_registry_roots(library_root: Path, story_id: str) -> tuple[Path, ...]:
    """Return catalog registry roots in target-first compatibility order."""

    from .catalog.paths import story_registry_roots as resolve_story_registry_roots

    return resolve_story_registry_roots(library_root, story_id)


def timeline_registry_path(library_root: Path, story_id: str) -> Path:
    """Resolve the story-wide timeline registry target-first."""

    from .catalog.paths import timeline_registry_path as resolve_timeline_registry_path

    return resolve_timeline_registry_path(library_root, story_id)


def module_map_paths(library_root: Path, story_id: str) -> tuple[Path, ...]:
    """Return existing module maps through the catalog path resolver."""

    from .catalog.paths import module_map_paths as resolve_module_map_paths

    return resolve_module_map_paths(library_root, story_id)


def index_root(library_root: Path) -> Path:
    return library_root / "index"


def shared_index_path(index_directory: Path) -> Path:
    return index_directory / "shared.db"


def story_graph_path(index_directory: Path, story_id: str, timeline_id: str = "main") -> Path:
    """Return the canonical story/timeline graph path.

    New callers should prefer :class:`novel_rag.identity.GraphKey` and its
    ``graph_path`` method.  This small layout helper exists for the CLI and
    compatibility façade, and deliberately performs the same conservative ID
    validation before constructing a path.
    """

    validate_story_id(story_id)
    validate_story_id(timeline_id)
    if timeline_id == SHARED_TIMELINE_ID:
        raise ValueError("global timeline 只属于 shared.db")
    return index_directory / "graphs" / story_id / f"{timeline_id}.db"


def legacy_story_index_path(index_directory: Path, story_id: str) -> Path:
    """Return the pre-GraphKey path used by the migration-only shim."""

    validate_story_id(story_id)
    return index_directory / "stories" / f"{story_id}.db"


def story_index_path(index_directory: Path, story_id: str, timeline_id: str | None = None) -> Path:
    """Compatibility path helper.

    The two-argument form retains the old ``stories/<story>.db`` location for
    callers that explicitly operate on a legacy database.  Supplying a
    timeline selects the canonical GraphKey location.  New code should use
    :func:`story_graph_path` or ``GraphKey.graph_path`` directly.
    """

    if timeline_id is None:
        return legacy_story_index_path(index_directory, story_id)
    return story_graph_path(index_directory, story_id, timeline_id)


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
        # Target v2 layout: stable common material and timeline-owned
        # documents are physically separated under the story directory.
        if parts[2] == "common" and len(parts) >= 4 and parts[3] in {"canon"}:
            return "story", story_id
        if parts[2] == "timelines" and len(parts) >= 5:
            if parts[4] in STORY_DATA_DIRS or parts[4] in {"summaries", "system-overrides"}:
                return "story", story_id
    return "unknown", None
