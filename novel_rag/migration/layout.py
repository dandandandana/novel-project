"""Read-only planning and copy-only execution for legacy story layouts.

The migration deliberately leaves every legacy source in place.  A plan can
therefore be inspected and rerun before a later coordinator decides whether
the copied target layout is ready for promotion.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..identity import validate_identifier

LEGACY_COMMON_DIRS = frozenset({"canon", "registry"})
LEGACY_TIMELINE_DIRS = frozenset(
    {
        "history",
        "outline",
        "character-state",
        "world-state",
        "feedback",
        "system-overrides",
    }
)
LEGACY_ROOT_FILES = frozenset({"retrieval-tests.yaml"})
LEGACY_METADATA_FILES = frozenset({".gitkeep"})
DEFAULT_TIMELINE_ID = "main"
_COMMON_SCOPE_VALUES = frozenset({"common", "story-common", "story_common", "global"})
_TIMELINE_SCOPE_VALUES = frozenset({"timeline", "story-timeline", "story_timeline"})


class MigrationError(RuntimeError):
    """Base class for safe legacy-layout migration failures."""


@dataclass(frozen=True)
class MigrationConflict:
    source: Path | None
    destination: Path | None
    reason: str


class MigrationConflictError(MigrationError):
    """Raised before execution when any source cannot be copied safely."""

    def __init__(self, conflicts: tuple[MigrationConflict, ...] | list[MigrationConflict]):
        self.conflicts = tuple(conflicts)
        message = "；".join(conflict.reason for conflict in self.conflicts)
        super().__init__(message or "legacy migration has conflicts")


@dataclass(frozen=True)
class MigrationOperation:
    source: Path
    destination: Path
    status: str
    reason: str = ""

    @property
    def is_copy(self) -> bool:
        return self.status == "copy"


@dataclass(frozen=True)
class LegacyLayoutMigrationPlan:
    library_root: Path
    story_ids: tuple[str, ...]
    operations: tuple[MigrationOperation, ...] = ()
    conflicts: tuple[MigrationConflict, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def is_safe(self) -> bool:
        return not self.conflicts

    @property
    def copy_operations(self) -> tuple[MigrationOperation, ...]:
        return tuple(operation for operation in self.operations if operation.is_copy)

    def as_dict(self) -> dict[str, Any]:
        return {
            "library_root": str(self.library_root),
            "story_ids": list(self.story_ids),
            "safe": self.is_safe,
            "operations": [
                {
                    "source": str(operation.source),
                    "destination": str(operation.destination),
                    "status": operation.status,
                    "reason": operation.reason,
                }
                for operation in self.operations
            ],
            "conflicts": [
                {
                    "source": str(conflict.source) if conflict.source else None,
                    "destination": str(conflict.destination) if conflict.destination else None,
                    "reason": conflict.reason,
                }
                for conflict in self.conflicts
            ],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class MigrationResult:
    plan: LegacyLayoutMigrationPlan
    copied: tuple[MigrationOperation, ...]
    skipped: tuple[MigrationOperation, ...]
    dry_run: bool

    @property
    def copied_count(self) -> int:
        return len(self.copied)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


def _inside(root: Path, path: Path) -> Path:
    resolved_root = root.resolve(strict=False)
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise MigrationError(f"路径越出 library 根目录: {path}") from exc
    return resolved


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _same_content(first: Path, second: Path) -> bool:
    try:
        return first.is_file() and second.is_file() and _file_digest(first) == _file_digest(second)
    except OSError:
        return False


def _read_metadata(path: Path) -> tuple[dict[str, Any], str | None]:
    if path.suffix.casefold() not in {".yaml", ".yml"}:
        return {}, None
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return {}, f"无法读取或解析 YAML: {exc}"
    if value is None:
        return {}, None
    if not isinstance(value, Mapping):
        return {}, None
    metadata = value.get("metadata")
    if metadata is None:
        return {}, None
    if not isinstance(metadata, Mapping):
        return {}, "metadata 必须是映射"
    return dict(metadata), None


def _metadata_target(
    metadata: Mapping[str, Any],
    *,
    story_id: str,
    category: str,
) -> tuple[str, str, str | None]:
    raw_story_id = metadata.get("story_id")
    if raw_story_id not in (None, "", story_id):
        return "", "", f"metadata.story_id 与物理 story 不一致: {raw_story_id!r}/{story_id}"

    timeline_raw = metadata.get("timeline_id")
    timeline_id = str(timeline_raw).strip() if timeline_raw not in (None, "") else ""
    if timeline_id:
        try:
            validate_identifier(timeline_id, field_name="timeline_id")
        except ValueError as exc:
            return "", "", str(exc)
        if timeline_id == "global":
            return "", "", "story 文档不得使用 timeline_id=global"

    scope_raw = metadata.get("scope", metadata.get("catalog_scope"))
    scope = str(scope_raw).strip().casefold() if scope_raw not in (None, "") else ""
    if scope and scope not in _COMMON_SCOPE_VALUES and scope not in _TIMELINE_SCOPE_VALUES:
        return "", "", f"不支持的 metadata.scope: {scope_raw!r}"

    if scope in _COMMON_SCOPE_VALUES or timeline_id == "common":
        if timeline_id not in {"", "common", DEFAULT_TIMELINE_ID}:
            return "", "", "metadata.scope=common 与非默认 timeline_id 冲突"
        return "common", DEFAULT_TIMELINE_ID, None

    if scope in _TIMELINE_SCOPE_VALUES:
        if timeline_id == "common":
            return "", "", "metadata.scope=timeline 必须指向具体 timeline_id"
        return "timeline", timeline_id or DEFAULT_TIMELINE_ID, None

    if category in LEGACY_COMMON_DIRS and timeline_id not in {"", DEFAULT_TIMELINE_ID}:
        return "timeline", timeline_id, None
    return ("common", DEFAULT_TIMELINE_ID, None) if category in LEGACY_COMMON_DIRS else (
        "timeline",
        timeline_id or DEFAULT_TIMELINE_ID,
        None,
    )


def _target_path(
    library_root: Path,
    story_id: str,
    category: str,
    relative: Path,
    metadata: Mapping[str, Any],
) -> tuple[Path | None, str | None]:
    scope, timeline_id, error = _metadata_target(
        metadata,
        story_id=story_id,
        category=category,
    )
    if error:
        return None, error
    story_root = library_root / "stories" / story_id
    if scope == "common":
        return story_root / "common" / category / relative, None
    return story_root / "timelines" / timeline_id / category / relative, None


def _operation_for(
    source: Path,
    destination: Path,
    *,
    reason: str = "",
) -> tuple[MigrationOperation, MigrationConflict | None]:
    if source.is_symlink():
        conflict = MigrationConflict(source, destination, "不迁移符号链接")
        return MigrationOperation(source, destination, "conflict", conflict.reason), conflict
    if not source.is_file():
        conflict = MigrationConflict(source, destination, "源路径不是普通文件")
        return MigrationOperation(source, destination, "conflict", conflict.reason), conflict
    if destination.is_symlink():
        conflict = MigrationConflict(source, destination, "目标路径是符号链接，不覆盖")
        return MigrationOperation(source, destination, "conflict", conflict.reason), conflict
    if destination.exists():
        if destination.is_file() and _same_content(source, destination):
            return MigrationOperation(source, destination, "unchanged", "目标内容已一致"), None
        conflict = MigrationConflict(source, destination, "目标已存在且内容不同，不覆盖")
        return MigrationOperation(source, destination, "conflict", conflict.reason), conflict
    return MigrationOperation(source, destination, "copy", reason), None


def _iter_legacy_files(story_root: Path) -> tuple[tuple[str, Path, Path], ...]:
    files: list[tuple[str, Path, Path]] = []
    categories = (*sorted(LEGACY_COMMON_DIRS), *sorted(LEGACY_TIMELINE_DIRS))
    for category in categories:
        source_root = story_root / category
        if not source_root.is_dir() or source_root.is_symlink():
            continue
        for source in sorted(source_root.rglob("*")):
            if source.name in LEGACY_METADATA_FILES:
                continue
            if source.is_dir():
                continue
            files.append((category, source, source.relative_to(source_root)))
    for name in sorted(LEGACY_ROOT_FILES):
        source = story_root / name
        if source.exists():
            files.append(("", source, Path(name)))
    return tuple(files)


def plan_legacy_migration(
    library_root: str | Path,
    *,
    story_id: str | None = None,
) -> LegacyLayoutMigrationPlan:
    """Build a read-only migration plan without creating target paths."""

    root = Path(library_root).resolve(strict=False)
    stories_root = root / "stories"
    if story_id is not None:
        validate_identifier(story_id, field_name="story_id")
        candidates = (stories_root / story_id,)
    elif stories_root.is_dir():
        candidates = tuple(sorted(path for path in stories_root.iterdir() if path.is_dir()))
    else:
        candidates = ()

    operations: list[MigrationOperation] = []
    conflicts: list[MigrationConflict] = []
    warnings: list[str] = []
    selected_story_ids: list[str] = []
    destinations: dict[Path, Path] = {}

    for story_root in candidates:
        if not story_root.is_dir():
            warnings.append(f"小说目录不存在，跳过: {story_root}")
            continue
        current_story_id = story_root.name
        try:
            validate_identifier(current_story_id, field_name="story_id")
            story_root = _inside(root, story_root)
        except (ValueError, MigrationError) as exc:
            conflicts.append(MigrationConflict(story_root, None, str(exc)))
            continue
        selected_story_ids.append(current_story_id)

        for category, source, relative in _iter_legacy_files(story_root):
            metadata, metadata_error = _read_metadata(source)
            if metadata_error:
                conflict = MigrationConflict(source, None, metadata_error)
                conflicts.append(conflict)
                operations.append(MigrationOperation(source, source, "conflict", metadata_error))
                continue
            destination, target_error = _target_path(
                root,
                current_story_id,
                category,
                relative,
                metadata,
            )
            if target_error or destination is None:
                conflict = MigrationConflict(source, None, target_error or "无法推导目标路径")
                conflicts.append(conflict)
                operations.append(MigrationOperation(source, source, "conflict", conflict.reason))
                continue
            destination = _inside(root, destination)
            previous = destinations.get(destination)
            if previous is not None:
                reason = f"多个 legacy 源映射到同一目标: {previous}"
                conflict = MigrationConflict(source, destination, reason)
                conflicts.append(conflict)
                operations.append(MigrationOperation(source, destination, "conflict", reason))
                continue
            destinations[destination] = source
            operation, conflict = _operation_for(source, destination)
            operations.append(operation)
            if conflict is not None:
                conflicts.append(conflict)

        preferences = story_root / "author-preferences.txt"
        if preferences.exists():
            warnings.append(f"保留 story-meta 文件，不迁移: {preferences}")

    return LegacyLayoutMigrationPlan(
        library_root=root,
        story_ids=tuple(selected_story_ids),
        operations=tuple(operations),
        conflicts=tuple(conflicts),
        warnings=tuple(warnings),
    )


def _preflight(plan: LegacyLayoutMigrationPlan) -> tuple[MigrationOperation, ...]:
    conflicts: list[MigrationConflict] = []
    for operation in plan.copy_operations:
        refreshed, conflict = _operation_for(operation.source, operation.destination)
        if conflict is not None:
            conflicts.append(conflict)
    if conflicts:
        raise MigrationConflictError(tuple(conflicts))
    return plan.copy_operations


def _copy_exclusive(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        descriptor = os.open(destination, flags)
        created = True
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_stream:
            shutil.copyfileobj(input_stream, output)
        try:
            shutil.copystat(source, destination)
        except OSError:
            pass
    except FileExistsError as exc:
        raise MigrationConflictError(
            (MigrationConflict(source, destination, "目标在执行期间已存在，不覆盖"),)
        ) from exc
    except Exception:
        if created:
            try:
                destination.unlink()
            except OSError:
                pass
        raise


def execute_migration(
    plan: LegacyLayoutMigrationPlan,
    *,
    dry_run: bool = True,
) -> MigrationResult:
    """Execute a safe copy plan; sources are never deleted or overwritten."""

    if plan.conflicts:
        raise MigrationConflictError(plan.conflicts)
    copy_operations = _preflight(plan)
    skipped = tuple(operation for operation in plan.operations if not operation.is_copy)
    if dry_run:
        return MigrationResult(plan, copy_operations, skipped, True)
    for operation in copy_operations:
        _copy_exclusive(operation.source, operation.destination)
    return MigrationResult(plan, copy_operations, skipped, False)


plan_legacy_layout_migration = plan_legacy_migration
execute_legacy_layout_migration = execute_migration


__all__ = [
    "LegacyLayoutMigrationPlan",
    "MigrationConflict",
    "MigrationConflictError",
    "MigrationError",
    "MigrationOperation",
    "MigrationResult",
    "execute_legacy_layout_migration",
    "execute_migration",
    "plan_legacy_layout_migration",
    "plan_legacy_migration",
]
