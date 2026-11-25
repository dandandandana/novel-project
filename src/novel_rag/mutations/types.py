"""Stable mutation and staged-build value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from ..std.hashing import fingerprint_bytes


MISSING_FINGERPRINT = "<missing>"


class MutationError(RuntimeError):
    """Base error for coordinated writes."""


class MutationConflictError(MutationError):
    """Raised when YAML changed after the change set was prepared."""


class MutationBuildError(MutationError):
    """Raised for invalid staged data or a graph build/regression failure."""


class MutationLockError(MutationError):
    """Raised when another mutation coordinator owns the lock."""


class SummaryError(MutationError):
    """Base error for summary lifecycle operations."""


class SummaryConflictError(SummaryError):
    """Raised when a summary revision no longer matches the editor request."""


class SummaryOwnershipError(SummaryError):
    """Raised when automation attempts to overwrite a user-owned summary."""


class SummaryMutationPendingError(SummaryError):
    """Raised when YAML committed but one or more graph promotions are pending."""

    def __init__(self, message: str, result: Any) -> None:
        super().__init__(message)
        self.result = result


class SummaryMutationFailedError(SummaryError):
    """Raised when a summary mutation failed before a complete promotion."""

    def __init__(self, message: str, result: Any) -> None:
        super().__init__(message)
        self.result = result


def fingerprint_file(path: Path) -> str:
    try:
        return fingerprint_bytes(path.read_bytes())
    except FileNotFoundError:
        return MISSING_FINGERPRINT


@dataclass(frozen=True, slots=True)
class ChangeSet:
    """YAML changes and the complete set of graphs they invalidate."""

    changes: Mapping[str | Path, Any] = field(default_factory=dict)
    affected_graph_keys: tuple[Any, ...] = ()
    expected_fingerprint: str | None = None
    expected_file_fingerprints: Mapping[str | Path, str] = field(default_factory=dict)
    change_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized: dict[Path, Any] = {}
        for raw_path, content in self.changes.items():
            path = Path(raw_path)
            if path in normalized:
                raise ValueError(f"ChangeSet 不能重复写入路径: {path}")
            normalized[path] = content
        expected: dict[Path, str] = {
            Path(path): str(value) for path, value in self.expected_file_fingerprints.items()
        }
        object.__setattr__(self, "changes", normalized)
        object.__setattr__(self, "affected_graph_keys", tuple(self.affected_graph_keys))
        object.__setattr__(self, "expected_file_fingerprints", expected)
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def files(self) -> tuple[Path, ...]:
        return tuple(self.changes)

    @property
    def yaml_changes(self) -> Mapping[Path, Any]:
        return self.changes

    @property
    def graph_keys(self) -> tuple[Any, ...]:
        return self.affected_graph_keys


@dataclass(frozen=True, slots=True)
class StagedChanges:
    """Validated callback input containing staged and original paths."""

    changeset: ChangeSet
    root: Path
    staged_files: Mapping[Path, Path]
    original_fingerprints: Mapping[Path, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))
        object.__setattr__(self, "staged_files", dict(self.staged_files))
        object.__setattr__(self, "original_fingerprints", dict(self.original_fingerprints))

    def staged_path(self, original: str | Path) -> Path:
        path = Path(original)
        if path in self.staged_files:
            return self.staged_files[path]
        resolved = path.resolve()
        if resolved in self.staged_files:
            return self.staged_files[resolved]
        try:
            return next(value for key, value in self.staged_files.items() if key.name == path.name)
        except StopIteration as exc:
            raise KeyError(f"没有该变更的 staged 文件: {path}") from exc

    def __getitem__(self, original: str | Path) -> Path:
        return self.staged_path(original)

    @property
    def path(self) -> Path:
        return self.root


@dataclass(frozen=True, slots=True)
class GraphBuildArtifact:
    """A temporary graph that passed construction and is ready to promote."""

    key: Any
    staged_path: Path | None = None
    target_path: Path | None = None
    promote_callback: Callable[[], Any] | None = None
    cleanup_callback: Callable[[], Any] | None = None
    regression_passed: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.staged_path is not None:
            object.__setattr__(self, "staged_path", Path(self.staged_path))
        if self.target_path is not None:
            object.__setattr__(self, "target_path", Path(self.target_path))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class GraphMutationResult:
    key: Any
    status: str
    target_path: Path | None = None
    staged_path: Path | None = None
    error: str | None = None

    @property
    def promoted(self) -> bool:
        return self.status == "promoted"

    @property
    def pending(self) -> bool:
        return self.status == "pending"

    @property
    def failed(self) -> bool:
        return self.status == "failed"


@dataclass(frozen=True, slots=True)
class MutationResult:
    """Coordinator result with an explicit state for every affected graph."""

    status: str
    graph_results: tuple[GraphMutationResult, ...] = ()
    yaml_committed: bool = False
    change_id: str = ""
    staging_root: Path | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "graph_results", tuple(self.graph_results))
        if self.staging_root is not None:
            object.__setattr__(self, "staging_root", Path(self.staging_root))

    @property
    def promoted(self) -> tuple[GraphMutationResult, ...]:
        return tuple(item for item in self.graph_results if item.promoted)

    @property
    def pending(self) -> tuple[GraphMutationResult, ...]:
        return tuple(item for item in self.graph_results if item.pending)

    @property
    def failed(self) -> tuple[GraphMutationResult, ...]:
        return tuple(item for item in self.graph_results if item.failed)

    @property
    def graphs(self) -> tuple[GraphMutationResult, ...]:
        return self.graph_results

    @property
    def by_graph(self) -> dict[str, GraphMutationResult]:
        return {repr(item.key): item for item in self.graph_results}

    @property
    def all_promoted(self) -> bool:
        return self.yaml_committed and not self.pending and not self.failed


__all__ = [
    "ChangeSet",
    "GraphBuildArtifact",
    "GraphMutationResult",
    "MISSING_FINGERPRINT",
    "MutationBuildError",
    "MutationConflictError",
    "MutationError",
    "MutationLockError",
    "MutationResult",
    "StagedChanges",
    "SummaryConflictError",
    "SummaryError",
    "SummaryMutationFailedError",
    "SummaryMutationPendingError",
    "SummaryOwnershipError",
    "fingerprint_bytes",
    "fingerprint_file",
]
