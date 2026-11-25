"""Canonical catalog paths for target and legacy story layouts.

The source catalog has two physical layouts during migration:

* target: ``stories/<story>/common/registry`` and
  ``stories/<story>/timelines/<timeline>/registry``;
* legacy: ``stories/<story>/registry``.

Callers that need a registry file must use this module instead of embedding a
layout-specific path.  Candidate ordering is intentional: the target layout
has precedence over legacy files, while callers can still inspect every
existing candidate to detect a migration conflict.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..identity import IdentityError, validate_identifier
from .errors import LayoutMappingError


def _validate_filename(filename: str) -> str:
    value = str(filename or "").strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise LayoutMappingError(
            f"registry filename 必须是单一文件名，不能包含路径分隔符: {filename!r}"
        )
    return value


def _validate_timeline_id(value: str) -> str:
    try:
        validate_identifier(value, field_name="timeline_id")
    except IdentityError as exc:
        raise LayoutMappingError(str(exc)) from exc
    if value == "global":
        raise LayoutMappingError("global timeline 只属于 shared.db")
    return value


def _unique(paths: tuple[Path, ...] | list[Path]) -> tuple[Path, ...]:
    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(path)
    return tuple(result)


@dataclass(frozen=True)
class StoryCatalogPaths:
    """Resolve one story's registry files across both supported layouts.

    No directory is created and no file is read by this value object.  The
    ``existing_*`` methods are the read-side discovery surface; ``resolve_*``
    methods return the target-layout default when no candidate exists so write
    callers have a deterministic destination.
    """

    library_root: Path
    story_id: str
    default_timeline_id: str = "main"

    def __post_init__(self) -> None:
        root = Path(self.library_root).resolve(strict=False)
        try:
            validate_identifier(self.story_id, field_name="story_id")
            _validate_timeline_id(self.default_timeline_id)
        except (IdentityError, LayoutMappingError) as exc:
            if isinstance(exc, LayoutMappingError):
                raise
            raise LayoutMappingError(str(exc)) from exc
        object.__setattr__(self, "library_root", root)

    @property
    def story_root(self) -> Path:
        return self.library_root / "stories" / self.story_id

    @property
    def common_registry_root(self) -> Path:
        return self.story_root / "common" / "registry"

    @property
    def legacy_registry_root(self) -> Path:
        return self.story_root / "registry"

    @property
    def timelines_root(self) -> Path:
        return self.story_root / "timelines"

    def timeline_registry_root(self, timeline_id: str | None = None) -> Path:
        selected = timeline_id or self.default_timeline_id
        _validate_timeline_id(selected)
        return self.timelines_root / selected / "registry"

    def registry_roots(
        self,
        timeline_id: str | None = None,
        *,
        include_all_timelines: bool = True,
    ) -> tuple[Path, ...]:
        """Return registry roots in target-first compatibility order.

        When a timeline is supplied, its target registry is considered first,
        followed by story-common and legacy roots.  Without a timeline, the
        story-common target root is followed by every target timeline root and
        then the legacy root; this is useful for module-map discovery across a
        story while keeping target files ahead of legacy fallbacks.
        """

        roots: list[Path] = []
        if timeline_id is not None:
            roots.append(self.timeline_registry_root(timeline_id))
        if timeline_id is None:
            roots.append(self.common_registry_root)
            if include_all_timelines and self.timelines_root.is_dir():
                roots.extend(
                    child / "registry"
                    for child in sorted(self.timelines_root.iterdir())
                    if child.is_dir()
                )
            roots.append(self.legacy_registry_root)
        else:
            roots.extend((self.common_registry_root, self.legacy_registry_root))
        return _unique(roots)

    def registry_file_candidates(
        self,
        filename: str,
        *,
        timeline_id: str | None = None,
    ) -> tuple[Path, ...]:
        """Return all supported locations for one registry filename."""

        name = _validate_filename(filename)
        # timelines.yaml and version-map.yaml are story-wide/common registry
        # data.  They are never timeline-owned in the target layout.  Keeping
        # this rule explicit prevents an unrelated timeline registry from
        # shadowing the common catalog when target and legacy layouts coexist.
        if name in {"timelines.yaml", "version-map.yaml"}:
            roots = (self.common_registry_root, self.legacy_registry_root)
        else:
            roots = self.registry_roots(timeline_id)
        return tuple(root / name for root in roots)

    def existing_registry_files(
        self,
        filename: str,
        *,
        timeline_id: str | None = None,
    ) -> tuple[Path, ...]:
        return tuple(
            path for path in self.registry_file_candidates(filename, timeline_id=timeline_id)
            if path.is_file()
        )

    def find_registry_file(
        self,
        filename: str,
        *,
        timeline_id: str | None = None,
    ) -> Path | None:
        """Return the first existing target/legacy candidate, if any."""

        existing = self.existing_registry_files(filename, timeline_id=timeline_id)
        return existing[0] if existing else None

    def resolve_registry_file(
        self,
        filename: str,
        *,
        timeline_id: str | None = None,
        required: bool = False,
    ) -> Path:
        """Resolve a read path or deterministic target-layout write path."""

        candidates = self.registry_file_candidates(filename, timeline_id=timeline_id)
        existing = tuple(path for path in candidates if path.is_file())
        if existing:
            return existing[0]
        if required:
            raise FileNotFoundError(
                "registry 文件不存在；已检查: " + ", ".join(str(path) for path in candidates)
            )
        # Candidate ordering is target-first when a target layout is present.
        # A legacy-only story must keep writing its legacy registry instead of
        # silently creating a second layout.  This is the write-side half of
        # the target/legacy non-mixing rule.
        if self.common_registry_root.is_dir() or self.timelines_root.is_dir():
            return candidates[0]
        if self.legacy_registry_root.is_dir():
            return next(
                (path for path in candidates if path.parent == self.legacy_registry_root),
                candidates[-1],
            )
        return candidates[0]

    def resolve_timeline_registry_path(self, *, required: bool = False) -> Path:
        return self.resolve_registry_file("timelines.yaml", required=required)

    def resolve_module_map_path(
        self,
        timeline_id: str | None = None,
        *,
        required: bool = False,
    ) -> Path:
        return self.resolve_registry_file(
            "module-map.yaml",
            timeline_id=timeline_id or self.default_timeline_id,
            required=required,
        )

    def resolve_version_map_path(
        self,
        timeline_id: str | None = None,
        *,
        required: bool = False,
    ) -> Path:
        """Resolve the story-wide common version map.

        ``timeline_id`` remains accepted for compatibility with callers that
        used the old resolver signature; it does not change ownership of the
        map.  Version lineage is common/catalog data, unlike module-map data,
        which is selected per timeline.
        """

        return self.resolve_registry_file(
            "version-map.yaml",
            timeline_id=timeline_id or self.default_timeline_id,
            required=required,
        )


CatalogPaths = StoryCatalogPaths


def story_catalog_paths(
    library_root: str | Path,
    story_id: str,
    *,
    default_timeline_id: str = "main",
) -> StoryCatalogPaths:
    return StoryCatalogPaths(library_root, story_id, default_timeline_id)


def story_registry_roots(
    library_root: str | Path,
    story_id: str,
    *,
    timeline_id: str | None = None,
    include_all_timelines: bool = True,
) -> tuple[Path, ...]:
    return story_catalog_paths(library_root, story_id).registry_roots(
        timeline_id,
        include_all_timelines=include_all_timelines,
    )


def registry_file_candidates(
    library_root: str | Path,
    story_id: str,
    filename: str,
    *,
    timeline_id: str | None = None,
) -> tuple[Path, ...]:
    return story_catalog_paths(library_root, story_id).registry_file_candidates(
        filename,
        timeline_id=timeline_id,
    )


def resolve_registry_file(
    library_root: str | Path,
    story_id: str,
    filename: str,
    *,
    timeline_id: str | None = None,
    required: bool = False,
) -> Path:
    return story_catalog_paths(library_root, story_id).resolve_registry_file(
        filename,
        timeline_id=timeline_id,
        required=required,
    )


def resolve_timeline_registry_path(
    library_root: str | Path,
    story_id: str,
    *,
    required: bool = False,
) -> Path:
    return story_catalog_paths(library_root, story_id).resolve_timeline_registry_path(
        required=required
    )


def resolve_module_map_path(
    library_root: str | Path,
    story_id: str,
    *,
    timeline_id: str | None = None,
    required: bool = False,
) -> Path:
    return story_catalog_paths(library_root, story_id).resolve_module_map_path(
        timeline_id,
        required=required,
    )


def resolve_version_map_path(
    library_root: str | Path,
    story_id: str,
    *,
    timeline_id: str | None = None,
    required: bool = False,
) -> Path:
    return story_catalog_paths(library_root, story_id).resolve_version_map_path(
        timeline_id,
        required=required,
    )


def timeline_registry_path(
    library_root: str | Path,
    story_id: str,
    *,
    required: bool = False,
) -> Path:
    """Compatibility spelling for the story-wide timeline registry resolver."""

    return resolve_timeline_registry_path(
        library_root,
        story_id,
        required=required,
    )


def module_map_paths(
    library_root: str | Path,
    story_id: str,
    *,
    timeline_id: str | None = None,
) -> tuple[Path, ...]:
    """Return existing module maps in target-first compatibility order."""

    return story_catalog_paths(library_root, story_id).existing_registry_files(
        "module-map.yaml",
        timeline_id=timeline_id,
    )


def version_map_paths(
    library_root: str | Path,
    story_id: str,
    *,
    timeline_id: str | None = None,
) -> tuple[Path, ...]:
    """Return existing version maps in target-first compatibility order."""

    return story_catalog_paths(library_root, story_id).existing_registry_files(
        "version-map.yaml",
        timeline_id=timeline_id,
    )


def version_map_path(
    library_root: str | Path,
    story_id: str,
    *,
    timeline_id: str | None = None,
    required: bool = False,
) -> Path:
    """Compatibility spelling for the default timeline version-map resolver."""

    return resolve_version_map_path(
        library_root,
        story_id,
        timeline_id=timeline_id,
        required=required,
    )


__all__ = [
    "CatalogPaths",
    "StoryCatalogPaths",
    "registry_file_candidates",
    "module_map_paths",
    "resolve_module_map_path",
    "resolve_registry_file",
    "resolve_timeline_registry_path",
    "resolve_version_map_path",
    "story_catalog_paths",
    "story_registry_roots",
    "timeline_registry_path",
    "version_map_path",
    "version_map_paths",
]
