"""Console TUI 的规范 UI 状态（CanonicalUiState）与状态常量。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .blocks import STATUS_SYMBOLS, STATUS_WORDS

STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_WARNING = "warning"
STATUS_FAILURE = "failure"
STATUS_CANCELLED = "cancelled"
STATUS_TIMEOUT = "timeout"

JOB_STATUSES = frozenset(
    {STATUS_RUNNING, STATUS_SUCCESS, STATUS_WARNING, STATUS_FAILURE,
     STATUS_CANCELLED, STATUS_TIMEOUT}
)

MODE_NORMAL = "normal"
MODE_COMMAND = "command"
MODE_OVERLAY = "overlay"

LEVEL_INFO = "info"
LEVEL_WARNING = "warning"
LEVEL_ERROR = "error"

NOTIFICATION_LEVELS = ("info", "warning", "error")


@dataclass(frozen=True)
class WorkspaceState:
    library_root: str = ""
    index_root: str = ""
    story_id: str | None = None
    timeline_id: str | None = None
    model_profile: str | None = None


@dataclass(frozen=True)
class JobState:
    id: str
    kind: str
    label: str
    status: str = STATUS_RUNNING
    elapsed_s: float = 0.0
    progress: float | None = None
    detail: str | None = None


@dataclass(frozen=True)
class BlockView:
    seq: int
    ts: str
    echo: str
    live_status: str | None = None


@dataclass(frozen=True)
class NotificationItem:
    level: str
    text: str
    seq: int


@dataclass(frozen=True)
class UiState:
    workspace: WorkspaceState
    blocks: tuple[BlockView, ...] = ()
    active_jobs: tuple[JobState, ...] = ()
    notifications: tuple[NotificationItem, ...] = ()
    mode: str = MODE_COMMAND
    unread: int = 0


def status_symbol(status: str) -> str:
    """状态符号唯一来源是 blocks.STATUS_SYMBOLS；此处仅作投影。"""

    return STATUS_SYMBOLS.get(status, "?")


def status_word(status: str) -> str:
    return STATUS_WORDS.get(status, "??")
