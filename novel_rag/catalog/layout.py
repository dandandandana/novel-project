"""Source-path normalization for legacy and target story layouts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ..identity import (
    GraphKey,
    SHARED_STORY_ID,
    SHARED_TIMELINE_ID,
    validate_identifier,
)
from .errors import LayoutMappingError


LEGACY_COMMON_DIRS = frozenset({"canon", "registry"})
LEGACY_TIMELINE_DIRS = frozenset(
    {"history", "outline", "character-state", "world-state", "feedback", "system-overrides"}
)


@dataclass(frozen=True)
class NormalizedPath:
    """A source path and its canonical target location."""

    source_path: Path
    target_path: Path
    scope: str
    story_id: str | None
    timeline_id: str | None
    relative_path: PurePosixPath
    legacy: bool

    @property
    def canonical_path(self) -> Path:
        return self.target_path

    @property
    def graph_key(self) -> GraphKey | None:
        if self.story_id is None or self.timeline_id is None:
            return None
        return GraphKey(self.story_id, self.timeline_id)


class LegacyLayoutMapper:
    """Map the pre-``common/timelines`` root layout without moving files."""

    def __init__(self, library_root: str | Path, *, default_timeline_id: str = "main") -> None:
        self.library_root = Path(library_root).resolve()
        try:
            validate_identifier(default_timeline_id, field_name="default_timeline_id")
        except ValueError as exc:
            raise LayoutMappingError(str(exc)) from exc
        self.default_timeline_id = default_timeline_id

    def normalize_path(
        self,
        path: str | Path,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> NormalizedPath:
        source = self._inside_library(path)
        relative = source.relative_to(self.library_root)
        parts = relative.parts
        if not parts:
            raise LayoutMappingError("library 根目录不是资料文件")

        if parts[0] == "shared":
            self._check_metadata_shared(metadata)
            return NormalizedPath(
                source_path=source,
                target_path=source,
                scope="shared",
                story_id=SHARED_STORY_ID,
                timeline_id=SHARED_TIMELINE_ID,
                relative_path=PurePosixPath(*parts[1:]),
                legacy=False,
            )
        if parts[0] == "registry":
            return NormalizedPath(
                source_path=source,
                target_path=source,
                scope="global",
                story_id=None,
                timeline_id=None,
                relative_path=PurePosixPath(*parts),
                legacy=False,
            )
        if len(parts) < 2 or parts[0] != "stories":
            raise LayoutMappingError(f"不支持的资料路径: {source}")

        story_id = parts[1]
        try:
            validate_identifier(story_id, field_name="story_id")
        except ValueError as exc:
            raise LayoutMappingError(str(exc)) from exc
        tail = parts[2:]
        if not tail:
            raise LayoutMappingError(f"小说目录不是资料文件: {source}")

        if tail[0] == "common":
            return self._target_common(source, story_id, tail[1:], metadata, legacy=False)
        if tail[0] == "timelines":
            if len(tail) < 2:
                raise LayoutMappingError(f"timeline 目录缺少 timeline_id: {source}")
            timeline_id = tail[1]
            self._validate_timeline_id(timeline_id)
            if len(tail) == 2:
                raise LayoutMappingError(f"timeline 目录不是资料文件: {source}")
            return self._target_timeline(
                source, story_id, timeline_id, tail[2:], metadata, legacy=False
            )

        # Legacy story-root layout.  Canon and registry are common by default;
        # all other data belongs to the main timeline by default.
        category = tail[0]
        if category in LEGACY_COMMON_DIRS:
            explicit_timeline = self._metadata_timeline(metadata)
            if explicit_timeline and explicit_timeline != self.default_timeline_id:
                return self._target_timeline(
                    source, story_id, explicit_timeline, tail, metadata, legacy=True
                )
            return self._target_common(source, story_id, tail, metadata, legacy=True)
        if category in LEGACY_TIMELINE_DIRS or category == "retrieval-tests.yaml":
            timeline_id = self._metadata_timeline(metadata) or self.default_timeline_id
            return self._target_timeline(
                source, story_id, timeline_id, tail, metadata, legacy=True
            )
        if category == "author-preferences.txt":
            return NormalizedPath(
                source_path=source,
                target_path=source,
                scope="story-meta",
                story_id=story_id,
                timeline_id=None,
                relative_path=PurePosixPath(*tail),
                legacy=True,
            )
        raise LayoutMappingError(f"不支持的小说资料目录: {source}")

    map_path = normalize_path
    normalize = normalize_path

    def _target_common(
        self,
        source: Path,
        story_id: str,
        tail: tuple[str, ...],
        metadata: Mapping[str, Any] | None,
        *,
        legacy: bool,
    ) -> NormalizedPath:
        if not tail:
            raise LayoutMappingError(f"common 目录不是资料文件: {source}")
        self._check_metadata_story(metadata, story_id)
        explicit = self._metadata_timeline(metadata)
        if explicit and explicit != self.default_timeline_id:
            raise LayoutMappingError(
                f"路径属于 common，但 metadata.timeline_id 指向其他 timeline: {explicit}"
            )
        relative = PurePosixPath(*tail)
        target = self.library_root / "stories" / story_id / "common" / Path(*tail)
        return NormalizedPath(source, target, "common", story_id, None, relative, legacy)

    def _target_timeline(
        self,
        source: Path,
        story_id: str,
        timeline_id: str,
        tail: tuple[str, ...],
        metadata: Mapping[str, Any] | None,
        *,
        legacy: bool,
    ) -> NormalizedPath:
        self._validate_timeline_id(timeline_id)
        if not tail:
            raise LayoutMappingError(f"timeline 资料目录不是资料文件: {source}")
        self._check_metadata_story(metadata, story_id)
        explicit = self._metadata_timeline(metadata)
        if explicit and explicit != timeline_id:
            raise LayoutMappingError(
                f"路径 timeline 与 metadata.timeline_id 不一致: {timeline_id}/{explicit}"
            )
        relative = PurePosixPath(*tail)
        target = (
            self.library_root
            / "stories"
            / story_id
            / "timelines"
            / timeline_id
            / Path(*tail)
        )
        return NormalizedPath(source, target, "timeline", story_id, timeline_id, relative, legacy)

    def _inside_library(self, path: str | Path) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.library_root / candidate
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self.library_root)
        except ValueError as exc:
            raise LayoutMappingError(f"路径越出 library 根目录: {path}") from exc
        return resolved

    @staticmethod
    def _metadata_timeline(metadata: Mapping[str, Any] | None) -> str | None:
        if not metadata:
            return None
        raw = metadata.get("timeline_id")
        if raw in (None, ""):
            return None
        return str(raw)

    @staticmethod
    def _check_metadata_story(metadata: Mapping[str, Any] | None, story_id: str) -> None:
        if metadata and metadata.get("story_id") not in (None, "", story_id):
            raise LayoutMappingError(
                f"路径 story_id 与 metadata.story_id 不一致: {story_id}/{metadata.get('story_id')}"
            )

    @staticmethod
    def _check_metadata_shared(metadata: Mapping[str, Any] | None) -> None:
        if not metadata:
            return
        story_id = metadata.get("story_id")
        timeline_id = metadata.get("timeline_id")
        if story_id not in (None, "", SHARED_STORY_ID):
            raise LayoutMappingError(
                f"shared 路径与 metadata.story_id 不一致: {SHARED_STORY_ID}/{story_id}"
            )
        if timeline_id not in (None, "", SHARED_TIMELINE_ID):
            raise LayoutMappingError(
                f"shared 路径与 metadata.timeline_id 不一致: {SHARED_TIMELINE_ID}/{timeline_id}"
            )

    @staticmethod
    def _validate_timeline_id(timeline_id: str) -> None:
        try:
            validate_identifier(timeline_id, field_name="timeline_id")
        except ValueError as exc:
            raise LayoutMappingError(str(exc)) from exc


def normalize_legacy_path(
    library_root: str | Path,
    path: str | Path,
    *,
    metadata: Mapping[str, Any] | None = None,
    default_timeline_id: str = "main",
) -> NormalizedPath:
    return LegacyLayoutMapper(
        library_root,
        default_timeline_id=default_timeline_id,
    ).normalize_path(path, metadata=metadata)


normalize_document_path = normalize_legacy_path


__all__ = [
    "LEGACY_COMMON_DIRS",
    "LEGACY_TIMELINE_DIRS",
    "LegacyLayoutMapper",
    "NormalizedPath",
    "normalize_document_path",
    "normalize_legacy_path",
]
