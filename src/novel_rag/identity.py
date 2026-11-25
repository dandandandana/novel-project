"""Stable identities used by catalog, projection, and retrieval layers.

This module deliberately has no dependency on the legacy layout helpers.  The
old helpers are still used by the compatibility surface, while new code can
construct graph paths only after a :class:`GraphKey` has validated both path
components.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,127})$")
SHARED_STORY_ID = "__shared__"
SHARED_TIMELINE_ID = "global"


class IdentityError(ValueError):
    """Raised when a stable identity or coordinate is unsafe or malformed."""


def validate_identifier(
    value: str,
    *,
    field_name: str = "identifier",
    allow_shared: bool = False,
) -> str:
    """Validate a path-safe story or timeline identifier.

    Story and timeline IDs intentionally use the same conservative alphabet as
    the existing story layout: lowercase ASCII letters, digits, and hyphens.
    The one reserved identity used by the shared projection is accepted only
    when ``allow_shared`` is explicit.
    """

    if not isinstance(value, str):
        raise IdentityError(f"{field_name} 必须是字符串")
    if allow_shared and value == SHARED_STORY_ID:
        return value
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise IdentityError(
            f"{field_name} 只能使用小写字母、数字和连字符，且必须以字母或数字开头: {value!r}"
        )
    return value


@dataclass(frozen=True, order=True)
class GraphKey:
    """The immutable identity of one story/timeline graph projection."""

    story_id: str
    timeline_id: str

    def __post_init__(self) -> None:
        validate_identifier(self.story_id, field_name="story_id", allow_shared=True)
        validate_identifier(self.timeline_id, field_name="timeline_id")
        if self.story_id == SHARED_STORY_ID and self.timeline_id != SHARED_TIMELINE_ID:
            raise IdentityError(
                f"共享图必须使用 timeline_id={SHARED_TIMELINE_ID!r}"
            )
        if self.timeline_id == SHARED_TIMELINE_ID and self.story_id != SHARED_STORY_ID:
            raise IdentityError(
                f"timeline_id={SHARED_TIMELINE_ID!r} 只属于共享图"
            )

    @property
    def is_shared(self) -> bool:
        return self.story_id == SHARED_STORY_ID

    def as_dict(self) -> dict[str, str]:
        """Return a JSON-friendly representation for manifest adapters."""

        return {"story_id": self.story_id, "timeline_id": self.timeline_id}

    def graph_path(self, index_root: str | Path) -> Path:
        """Return the only supported physical path for this graph.

        This method never creates directories.  A builder owns creation and a
        reader can use the result without accidentally granting write access.
        """

        root = Path(index_root)
        if self.is_shared:
            return root / "shared.db"
        return root / "graphs" / self.story_id / f"{self.timeline_id}.db"

    # These aliases make the contract convenient for callers without creating
    # a second path policy.
    database_path = graph_path
    path = graph_path

    @classmethod
    def shared(cls) -> "GraphKey":
        return cls(SHARED_STORY_ID, SHARED_TIMELINE_ID)


_COORDINATE_PATTERN = re.compile(
    r"^\s*volume-(?P<volume>\d+)"
    r"(?:(?:[/\\]|-)chapter-(?P<chapter>\d+)"
    r"(?:(?:[/\\]|-)scene-(?P<scene>\d+))?)?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, order=True)
class StoryCoordinate:
    """Comparable volume/chapter/scene coordinate.

    Missing chapter or scene values are represented as ``0``.  This gives
    partial coordinates useful upper bounds while retaining normal tuple-like
    ordering (volume, then chapter, then scene).
    """

    volume: int
    chapter: int = 0
    scene: int = 0

    def __post_init__(self) -> None:
        for name, value in (
            ("volume", self.volume),
            ("chapter", self.chapter),
            ("scene", self.scene),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise IdentityError(f"{name} 必须是非负整数")
            if value < 0:
                raise IdentityError(f"{name} 必须是非负整数")
        if self.scene and not self.chapter:
            raise IdentityError("scene 不能在缺少 chapter 时单独出现")

    @property
    def is_complete(self) -> bool:
        return self.chapter > 0 and self.scene > 0

    @classmethod
    def from_value(cls, value: Any) -> "StoryCoordinate":
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            try:
                return cls(
                    int(value.get("volume", 0)),
                    int(value.get("chapter", 0)),
                    int(value.get("scene", 0)),
                )
            except (TypeError, ValueError) as exc:
                raise IdentityError(f"坐标映射无效: {value!r}") from exc
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            if not 1 <= len(value) <= 3:
                raise IdentityError("坐标序列必须包含 1 到 3 个整数")
            try:
                numbers = [int(item) for item in value]
            except (TypeError, ValueError) as exc:
                raise IdentityError(f"坐标序列无效: {value!r}") from exc
            return cls(*numbers, *([0] * (3 - len(numbers))))
        if isinstance(value, str):
            match = _COORDINATE_PATTERN.fullmatch(value)
            if not match:
                raise IdentityError(
                    "坐标必须形如 volume-04/chapter-24/scene-03"
                )
            return cls(
                int(match.group("volume")),
                int(match.group("chapter") or 0),
                int(match.group("scene") or 0),
            )
        raise IdentityError(f"无法解析坐标: {value!r}")

    @classmethod
    def from_metadata(cls, metadata: Mapping[str, Any]) -> "StoryCoordinate | None":
        values = [metadata.get(name) for name in ("volume", "chapter", "scene")]
        if all(value in (None, "") for value in values):
            return None
        return cls.from_value({name: value or 0 for name, value in zip(("volume", "chapter", "scene"), values)})

    def as_path(self, *, padded: bool = False) -> str:
        if padded:
            return f"volume-{self.volume:02d}/chapter-{self.chapter:03d}/scene-{self.scene:03d}"
        parts = [f"volume-{self.volume}"]
        if self.chapter:
            parts.append(f"chapter-{self.chapter}")
        if self.scene:
            parts.append(f"scene-{self.scene}")
        return "/".join(parts)

    def __str__(self) -> str:
        return self.as_path()


def parse_story_coordinate(value: Any) -> StoryCoordinate:
    """Compatibility function for code that prefers a parser-style API."""

    return StoryCoordinate.from_value(value)


__all__ = [
    "GraphKey",
    "IdentityError",
    "IDENTIFIER_PATTERN",
    "SHARED_STORY_ID",
    "SHARED_TIMELINE_ID",
    "StoryCoordinate",
    "parse_story_coordinate",
    "validate_identifier",
]
