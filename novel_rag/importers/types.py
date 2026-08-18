"""Error classes, dataclasses, and constants for import."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class RagImportError(RuntimeError):
    """导入、版本冲突或事务回滚失败。"""


_DESTINATIONS = {
    "canon": "canon/imported",
    "outline": "outline/chapters",
    "feedback": "feedback/imported",
}
_VERSION_RE = re.compile(r"^\d+(?:\.\d+)+$")
_VERSION_SUFFIX_RE = re.compile(r"-v\d+(?:\.\d+)+$", re.IGNORECASE)
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


@dataclass(frozen=True)
class ImportPreview:
    status: str
    path: Path
    document_id: str
    document_type: str
    version: str
    document_family: str
    supersedes: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    source_sha256: str = ""

    @property
    def ready(self) -> bool:
        return self.status in {"ready", "noop"} and not self.conflicts


@dataclass(frozen=True)
class ImportResult:
    status: str
    path: Path
    document_id: str
    document_family: str = ""
    version: str = ""
    supersedes: tuple[str, ...] = ()
    changed_paths: tuple[Path, ...] = field(default_factory=tuple)
    retrieval_cases: int = 0


@dataclass(frozen=True)
class _PreparedImport:
    preview: ImportPreview
    text: str
    document: "RagDocument"
    target: Path
    version_rows: list[dict[str, Any]]
    version_map_path: Path
    old_paths: tuple[Path, ...]