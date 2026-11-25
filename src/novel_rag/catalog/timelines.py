"""Timeline registry parsing, lineage, and divergence-bound validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..identity import IdentityError, StoryCoordinate, validate_identifier
from .errors import CatalogValidationError


@dataclass(frozen=True)
class TimelineEntry:
    story_id: str
    timeline_id: str
    parent_timeline_id: str | None = None
    divergence_at: StoryCoordinate | None = None
    divergence_snapshot: str | None = None
    status: str = "active"
    name: str = ""

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        expected_story_id: str | None = None,
        index: int = 0,
        snapshot_root: str | Path | None = None,
        root: str | Path | None = None,
    ) -> "TimelineEntry":
        issues: list[str] = []
        resolved_snapshot_root = _coalesce_snapshot_root(snapshot_root, root)
        story_id = str(value.get("story_id") or "")
        timeline_id = str(value.get("timeline_id") or "")
        try:
            validate_identifier(story_id, field_name="story_id")
        except IdentityError as exc:
            issues.append(f"timelines[{index}].story_id: {exc}")
        if expected_story_id and story_id != expected_story_id:
            issues.append(
                f"timelines[{index}].story_id 必须为 {expected_story_id}: {story_id!r}"
            )
        try:
            validate_identifier(timeline_id, field_name="timeline_id")
        except IdentityError as exc:
            issues.append(f"timelines[{index}].timeline_id: {exc}")

        parent_raw = value.get("parent_timeline_id")
        parent_id = str(parent_raw) if parent_raw not in (None, "") else None
        if parent_id is not None:
            try:
                validate_identifier(parent_id, field_name="parent_timeline_id")
            except IdentityError as exc:
                issues.append(f"timelines[{index}].parent_timeline_id: {exc}")
            if parent_id == timeline_id:
                issues.append(f"timelines[{index}] 不能把自己作为 parent_timeline_id")

        divergence_raw = value.get("divergence_at")
        divergence_at: StoryCoordinate | None = None
        if divergence_raw not in (None, ""):
            try:
                divergence_at = StoryCoordinate.from_value(divergence_raw)
            except IdentityError as exc:
                issues.append(f"timelines[{index}].divergence_at: {exc}")

        snapshot_raw = value.get("divergence_snapshot")
        divergence_snapshot = str(snapshot_raw) if snapshot_raw not in (None, "") else None
        if divergence_snapshot is not None:
            snapshot_error = _snapshot_validation_error(
                divergence_snapshot,
                resolved_snapshot_root,
            )
            if snapshot_error:
                issues.append(f"timelines[{index}].divergence_snapshot: {snapshot_error}")

        if parent_id is None:
            if divergence_at is not None:
                issues.append(f"timelines[{index}] 根 timeline 不得设置 divergence_at")
            if divergence_snapshot is not None:
                issues.append(
                    f"timelines[{index}] 根 timeline 不得设置 divergence_snapshot"
                )
        else:
            if divergence_at is None:
                issues.append(f"timelines[{index}] 分支 timeline 必须设置 divergence_at")
            elif not divergence_at.is_complete:
                issues.append(
                    f"timelines[{index}].divergence_at 必须精确到 scene"
                )
            if divergence_snapshot is None:
                issues.append(
                    f"timelines[{index}] 分支 timeline 必须设置 divergence_snapshot"
                )

        if issues:
            raise CatalogValidationError(issues)
        return cls(
            story_id=story_id,
            timeline_id=timeline_id,
            parent_timeline_id=parent_id,
            divergence_at=divergence_at,
            divergence_snapshot=divergence_snapshot,
            status=str(value.get("status") or "active"),
            name=str(value.get("name") or ""),
        )

    def snapshot_path(self, root: str | Path) -> Path:
        """Resolve this entry's relative snapshot path below ``root``."""

        if self.divergence_snapshot is None:
            raise CatalogValidationError(
                f"timeline {self.timeline_id} 没有 divergence_snapshot"
            )
        return resolve_divergence_snapshot(self.divergence_snapshot, root)


def _relative_snapshot_error(value: str) -> str | None:
    """Return an error for an unsafe divergence snapshot path."""

    if not value.strip():
        return "不能为空"
    candidate = value.replace("\\", "/")
    if "\x00" in candidate:
        return "不得包含 NUL 字符"
    path = Path(candidate)
    if path.is_absolute() or (len(candidate) >= 2 and candidate[1] == ":"):
        return "必须是相对路径"
    parts = tuple(part for part in candidate.split("/") if part not in ("", "."))
    if not parts:
        return "必须是非空相对路径"
    if any(part == ".." for part in parts):
        return "不得包含 .. 路径穿越"
    return None


def _coalesce_snapshot_root(
    snapshot_root: str | Path | None,
    root: str | Path | None,
) -> Path | None:
    """Normalize the explicit snapshot root and its compatibility alias."""

    if snapshot_root is not None and root is not None:
        first = Path(snapshot_root).resolve(strict=False)
        second = Path(root).resolve(strict=False)
        if first != second:
            raise CatalogValidationError(
                f"snapshot_root 与 root 不一致: {first} != {second}"
            )
        return first
    selected = snapshot_root if snapshot_root is not None else root
    return Path(selected).resolve(strict=False) if selected is not None else None


def resolve_divergence_snapshot(value: str, root: str | Path) -> Path:
    """Resolve a safe relative snapshot path below ``root``.

    Resolution is intentionally separate from YAML validation so callers can
    use the same path policy when they later load the frozen snapshot.
    """

    error = _relative_snapshot_error(value)
    if error:
        raise CatalogValidationError(f"divergence_snapshot: {error}")
    root_path = Path(root).resolve(strict=False)
    candidate = value.replace("\\", "/")
    resolved = (root_path / Path(candidate)).resolve(strict=False)
    try:
        resolved.relative_to(root_path)
    except ValueError as exc:
        raise CatalogValidationError(
            f"divergence_snapshot 解析后越出 root: {value}"
        ) from exc
    return resolved


def _snapshot_validation_error(value: str, root: Path | None) -> str | None:
    """Validate snapshot syntax and, when configured, its YAML source."""

    syntax_error = _relative_snapshot_error(value)
    if syntax_error:
        return syntax_error
    if root is None:
        return None
    try:
        path = resolve_divergence_snapshot(value, root)
    except CatalogValidationError as exc:
        return str(exc)
    if not path.is_file():
        return f"文件不存在或不是普通文件: {path}"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return f"文件不可读: {path}: {exc}"
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return f"YAML 无法解析: {path}: {exc}"
    if not isinstance(parsed, Mapping):
        return f"YAML 根节点必须是映射: {path}"
    return None


@dataclass(frozen=True)
class TimelineRegistry:
    story_id: str
    entries: tuple[TimelineEntry, ...]
    validation_issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_identifier(self.story_id, field_name="story_id")
        ids = [entry.timeline_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise CatalogValidationError("timeline_id 重复")

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        expected_story_id: str | None = None,
        strict: bool = True,
        snapshot_root: str | Path | None = None,
        root: str | Path | None = None,
    ) -> "TimelineRegistry":
        issues: list[str] = []
        resolved_snapshot_root = _coalesce_snapshot_root(snapshot_root, root)
        if not isinstance(value, Mapping):
            raise CatalogValidationError("timelines registry 根节点必须是映射")
        rows = value.get("timelines")
        if not isinstance(rows, list):
            raise CatalogValidationError("timelines 必须是列表")
        parsed: list[TimelineEntry] = []
        seen: set[str] = set()
        inferred_story = expected_story_id or ""
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                issues.append(f"timelines[{index}] 必须是映射")
                continue
            row_story = str(row.get("story_id") or "")
            if not inferred_story and row_story:
                inferred_story = row_story
            try:
                entry = TimelineEntry.from_mapping(
                    row,
                    expected_story_id=expected_story_id or inferred_story or None,
                    index=index,
                    snapshot_root=resolved_snapshot_root,
                )
            except CatalogValidationError as exc:
                issues.extend(exc.issues)
                continue
            if entry.timeline_id in seen:
                issues.append(f"timelines[{index}].timeline_id 重复: {entry.timeline_id}")
                continue
            seen.add(entry.timeline_id)
            parsed.append(entry)

        story_id = expected_story_id or inferred_story
        if not story_id:
            issues.append("无法从 timelines registry 推断 story_id")
        else:
            try:
                validate_identifier(story_id, field_name="story_id")
            except IdentityError as exc:
                issues.append(str(exc))

        by_id = {entry.timeline_id: entry for entry in parsed}
        for entry in parsed:
            parent = entry.parent_timeline_id
            if parent is None:
                continue
            if parent not in by_id:
                issues.append(
                    f"timeline {entry.timeline_id} 的 parent_timeline_id 不存在: {parent}"
                )
                continue
            parent_entry = by_id[parent]
            if (
                parent_entry.divergence_at is not None
                and entry.divergence_at is not None
                and entry.divergence_at <= parent_entry.divergence_at
            ):
                issues.append(
                    f"timeline {entry.timeline_id} 的 divergence_at 必须晚于 parent "
                    f"{parent}: {entry.divergence_at} <= {parent_entry.divergence_at}"
                )

        issues.extend(_cycle_issues(by_id))
        if not parsed:
            issues.append("timelines registry 至少需要一个 timeline")
        if strict and issues:
            raise CatalogValidationError(issues)
        if not story_id:
            # Keep the object constructible in non-strict diagnostic mode.
            story_id = "invalid"
        return cls(
            story_id=story_id,
            entries=tuple(parsed),
            validation_issues=tuple(issues),
        )

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        expected_story_id: str | None = None,
        strict: bool = True,
        snapshot_root: str | Path | None = None,
        root: str | Path | None = None,
    ) -> "TimelineRegistry":
        source = Path(path)
        try:
            value = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise CatalogValidationError(f"无法读取 timeline registry {source}: {exc}") from exc
        return cls.from_mapping(
            value,
            expected_story_id=expected_story_id,
            strict=strict,
            snapshot_root=snapshot_root,
            root=root,
        )

    def validate(self) -> tuple[str, ...]:
        """Return an empty tuple for a valid already-parsed registry.

        Parsing in strict mode performs validation eagerly.  This method is
        useful to callers that want a uniform validator interface.
        """

        return self.validation_issues

    def get(self, timeline_id: str) -> TimelineEntry:
        for entry in self.entries:
            if entry.timeline_id == timeline_id:
                return entry
        raise CatalogValidationError(f"未注册 timeline_id: {self.story_id}/{timeline_id}")

    def lineage(self, timeline_id: str) -> tuple[TimelineEntry, ...]:
        """Return root-to-target entries after validating parent links."""

        current = self.get(timeline_id)
        result: list[TimelineEntry] = []
        visited: set[str] = set()
        while True:
            if current.timeline_id in visited:
                raise CatalogValidationError("timeline lineage 存在循环")
            visited.add(current.timeline_id)
            result.append(current)
            if current.parent_timeline_id is None:
                break
            current = self.get(current.parent_timeline_id)
        result.reverse()
        return tuple(result)

    get_lineage = lineage
    lineage_for = lineage

    def cutoffs(self, timeline_id: str) -> dict[str, StoryCoordinate | None]:
        """Return each lineage segment's upper bound for the target graph.

        The root has no upper bound.  For every child segment, its parent's
        content is visible only through the child's ``divergence_at``.
        """

        lineage = self.lineage(timeline_id)
        result: dict[str, StoryCoordinate | None] = {lineage[0].timeline_id: None}
        for child in lineage[1:]:
            result[child.parent_timeline_id or ""] = child.divergence_at
            result[child.timeline_id] = None
        return result

    lineage_cutoffs = cutoffs
    cutoffs_for = cutoffs

    def allowed_timeline_ids(self, timeline_id: str) -> tuple[str, ...]:
        return tuple(entry.timeline_id for entry in self.lineage(timeline_id))


def _cycle_issues(entries: Mapping[str, TimelineEntry]) -> list[str]:
    issues: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(timeline_id: str) -> None:
        if timeline_id in visiting:
            issues.append(f"timeline lineage 存在循环: {timeline_id}")
            return
        if timeline_id in visited:
            return
        visiting.add(timeline_id)
        parent = entries[timeline_id].parent_timeline_id
        if parent in entries:
            visit(parent)
        visiting.remove(timeline_id)
        visited.add(timeline_id)

    for timeline_id in entries:
        visit(timeline_id)
    return issues


def load_timeline_registry(
    path: str | Path,
    *,
    expected_story_id: str | None = None,
    snapshot_root: str | Path | None = None,
    root: str | Path | None = None,
) -> TimelineRegistry:
    return TimelineRegistry.from_path(
        path,
        expected_story_id=expected_story_id,
        snapshot_root=snapshot_root,
        root=root,
    )


__all__ = [
    "TimelineEntry",
    "TimelineRegistry",
    "load_timeline_registry",
    "resolve_divergence_snapshot",
]
