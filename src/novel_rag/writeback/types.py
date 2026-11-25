"""Result and error types for the history writeback step."""

from __future__ import annotations

from dataclasses import dataclass, field


class WritebackError(ValueError):
    pass


@dataclass(slots=True)
class WritebackResult:
    status: str
    writeback_id: str
    document_ids: list[str] = field(default_factory=list)
    history_path: str = ""
    state_promoted: bool = False
    retrieval_cases: int = 0
    cleaned_files: int = 0
    cleanup_warnings: list[str] = field(default_factory=list)
