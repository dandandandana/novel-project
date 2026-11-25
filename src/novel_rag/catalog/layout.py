"""Source-path normalization for legacy and target story layouts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ..identity import (
    GraphKey,
    SHARED_STORY_ID,
    SHARED_TIMELINE_ID,
    validate_identifier,
)
from ..layout import classify_document_path
from .errors import LayoutMappingError


COMMON_TIMELINE_ID = "common"
LEGACY_COMMON_DIRS = frozenset({"canon", "registry"})
LEGACY_TIMELINE_DIRS = frozenset(
    {"history", "outline", "character-state", "world-state", "feedback", "summaries", "system-overrides"}
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
    library_root: Path | None = field(default=None, compare=False)

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
        """依赖：作品布局和 metadata。输入：来源路径及可选声明。输出：物理或旧布局归属。实现：按根定位并核对显式身份。"""
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
                library_root=self.library_root,
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
                library_root=self.library_root,
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
            if explicit_timeline not in (None, self.default_timeline_id, COMMON_TIMELINE_ID):
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
                library_root=self.library_root,
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
        """依赖：已识别的 common 路径。输入：物理位置和可选声明。输出：common 归属或冲突。实现：保留默认 timeline 和旧 common 标识。"""
        if not tail:
            raise LayoutMappingError(f"common 目录不是资料文件: {source}")
        self._check_metadata_story(metadata, story_id)
        explicit = self._metadata_timeline(metadata)
        if explicit not in (None, self.default_timeline_id, COMMON_TIMELINE_ID):
            raise LayoutMappingError(
                f"路径属于 common，但 metadata.timeline_id 指向其他 timeline: {explicit}"
            )
        relative = PurePosixPath(*tail)
        target = self.library_root / "stories" / story_id / "common" / Path(*tail)
        return NormalizedPath(source, target, "common", story_id, None, relative, legacy, self.library_root)

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
        """依赖：布局与标识校验。输入：来源、物理作品线、相对路径及声明。输出：规范归属或错误。实现：核对作品、时间线并保留真实源路径。"""
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
        return NormalizedPath(source, target, "timeline", story_id, timeline_id, relative, legacy, self.library_root)

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


def _catalog_document_root(path: Path, library_root: Path | None) -> Path | None:
    """依赖：词法布局分类。输入：绝对路径与可选库根。输出：可辨资料根或 None。实现：先检查指定根，再检查路径中正式目录前缀。"""
    if library_root is not None and path.is_relative_to(library_root):
        if classify_document_path(library_root, path, follow_symlinks=False)[0] != "unknown":
            return library_root
    for index, part in enumerate(path.parts):
        if part in {"stories", "shared"}:
            root = Path(*path.parts[:index])
            if classify_document_path(root, path, follow_symlinks=False)[0] != "unknown":
                return root
    return None


def resolve_catalog_document_path(
    path: Path,
    metadata: Mapping[str, Any] | None = None,
    *,
    library_root: Path | None = None,
) -> NormalizedPath | None:
    """依赖：现有布局分类和路径 mapper。输入：来源路径、metadata、可选指纹根。输出：已验证归属，或无物理布局的适配资料返回 None。实现：定位受控目录并复用 mapper 核验。"""
    path = path.absolute()
    library_root = library_root.absolute() if library_root is not None else None
    root = _catalog_document_root(path, library_root)
    if root is None:
        path = path.resolve(strict=False)
        root = _catalog_document_root(path, library_root)
        if root is None:
            return None
    identity = LegacyLayoutMapper(root).normalize_path(path, metadata=metadata)
    if classify_document_path(identity.library_root or root, identity.source_path, follow_symlinks=False)[0] == "unknown":
        raise LayoutMappingError(f"正式资料路径指向非资料位置: {path}")
    return identity


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
    "COMMON_TIMELINE_ID",
    "LEGACY_COMMON_DIRS",
    "LEGACY_TIMELINE_DIRS",
    "LegacyLayoutMapper",
    "NormalizedPath",
    "normalize_document_path",
    "normalize_legacy_path",
    "resolve_catalog_document_path",
]
