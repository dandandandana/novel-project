"""UiAdapter：业务事件 → CanonicalUiState 的唯一翻译层；含 legacy 交互桥。"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .blocks import BlockStore, format_status_line
from .config import UiConfig
from .jobs import JobHandle, JobRunner
from .state import (
    JobState,
    NotificationItem,
    STATUS_FAILURE,
    STATUS_RUNNING,
    BlockView,
    MODE_COMMAND,
    UiState,
    WorkspaceState,
)

_CANCEL_TOKEN = "__CANCEL__"

_LEVEL_ORDER = {"info": 0, "warning": 1, "error": 2}


class _JobRecord:
    __slots__ = ("handle", "last_emit")

    def __init__(self, handle: JobHandle, now: float) -> None:
        self.handle = handle
        self.last_emit = now


@dataclass
class PendingAsk:
    prompt: str
    event: threading.Event
    answer: str | None = None


class ConsoleAdapter:
    """所有可变 UI 状态的单入口；线程安全；更新后触发 on_invalidate。"""

    def __init__(self, config: UiConfig,
                 on_invalidate: Callable[[], None] | None = None,
                 time_fn: Callable[[], float] = time.monotonic) -> None:
        self.config = config
        self._on_invalidate = on_invalidate or (lambda: None)
        self._time_fn = time_fn
        self._lock = threading.RLock()
        self.blocks = BlockStore(max_lines=config.max_buffer_lines)
        self.workspace = WorkspaceState()
        self.mode = MODE_COMMAND
        self.jobs: dict[str, _JobRecord] = {}
        self.notifications: list[NotificationItem] = []
        self.read_cursor = 0
        self.notify_seq = 0
        self.pending_ask: PendingAsk | None = None
        self.closing = threading.Event()
        self.block_views: list[BlockView] = []
        self.runner = JobRunner(self._on_runner_event, time_fn=time_fn)
        self._min_interval = 1.0 / max(float(config.progress_refresh_hz), 0.5)

    def invalidate(self) -> None:
        try:
            self._on_invalidate()
        except Exception:
            pass

    def set_workspace(self, **fields: Any) -> None:
        with self._lock:
            current = self.workspace
            self.workspace = WorkspaceState(
                library_root=str(fields.get("library_root", current.library_root)),
                index_root=str(fields.get("index_root", current.index_root)),
                story_id=fields.get("story_id", current.story_id),
                timeline_id=fields.get("timeline_id", current.timeline_id),
                model_profile=fields.get("model_profile", current.model_profile),
            )
        self.invalidate()

    def system_line(self, text: str) -> None:
        self.blocks.append_line(text, indent=True)
        self.invalidate()

    def notify(self, level: str, text: str) -> None:
        level = level if level in _LEVEL_ORDER else "info"
        if _LEVEL_ORDER[level] < _LEVEL_ORDER[self.config.notification_level]:
            return
        with self._lock:
            self.notify_seq += 1
            self.notifications.append(
                NotificationItem(level=level, text=text, seq=self.notify_seq))
            if len(self.notifications) > 100:
                del self.notifications[:50]
        self.invalidate()

    def mark_notifications_read(self) -> None:
        with self._lock:
            if self.notifications:
                self.read_cursor = self.notifications[-1].seq
        self.invalidate()

    def unread_count(self) -> int:
        return sum(1 for item in self.notifications if item.seq > self.read_cursor)

    def snapshot(self) -> UiState:
        with self._lock:
            active = tuple(record.handle for record in self.jobs.values()
                           if not record.handle.done)
            job_states = tuple(
                JobState(id=h.id, kind=h.kind, label=h.label, status=STATUS_RUNNING,
                         elapsed_s=h.elapsed, progress=h.progress, detail=h.detail)
                for h in active
            )
            return UiState(workspace=self.workspace,
                           blocks=tuple(self.block_views),
                           active_jobs=job_states,
                           notifications=tuple(self.notifications),
                           mode=self.mode,
                           unread=self.unread_count())

    def shutdown(self) -> None:
        self.closing.set()
        with self._lock:
            pending = self.pending_ask
        if pending is not None and not pending.event.is_set():
            pending.answer = _CANCEL_TOKEN
            pending.event.set()

    def _on_runner_event(self, event: dict) -> None:
        kind = event["type"]
        if kind == "line":
            self._event_line(event["job"], event["text"])
        elif kind == "progress":
            self._event_progress(event["job"], event.get("detail"), event.get("value"))
        elif kind == "finish":
            self._event_finish(event["job"], event["status"], event.get("error"))

    def _event_line(self, job: JobHandle, text: str) -> None:
        if job.cancelled or job.done:
            return
        self.blocks.append_line(text)
        self.invalidate()

    def _event_progress(self, job: JobHandle, detail: str | None,
                        value: float | None) -> None:
        now = self._time_fn()
        with self._lock:
            record = self.jobs.get(job.id)
            if record is None:
                record = _JobRecord(job, now)
                self.jobs[job.id] = record
            if (value is not None and value not in (0.0, 1.0)
                    and now - record.last_emit < self._min_interval):
                return
            record.last_emit = now
        job.detail = detail
        job.progress = value
        elapsed = f"{job.elapsed:.0f}s"
        bar = ""
        if value is not None:
            filled = int(max(0.0, min(1.0, value)) * 10)
            bar = "▓" * filled + "░" * (10 - filled) + " "
        live = f"   ● RUN {job.label}  {bar}{detail or ''} {elapsed}".rstrip()
        self.blocks.set_live_line(live)
        self.invalidate()

    def _event_finish(self, job: JobHandle, status: str,
                      error: BaseException | None) -> None:
        with self._lock:
            self.jobs.pop(job.id, None)
        self.blocks.set_live_line(None)
        detail = ""
        line = format_status_line(status, job.label, detail=detail)
        self.blocks.finish_live(line)
        if status == "failure" and error is not None:
            self.blocks.append_line(f"      ↳ {type(error).__name__}: {error}")
            self.notify("error", f"{job.label} 失败：{error}")
        elif status == "cancelled":
            self.system_line("   · 已取消：" + job.label)
        else:
            self.notify("info", f"{job.label} 完成")
        self.invalidate()

    def track_job(self, job: JobHandle) -> None:
        with self._lock:
            now = self._time_fn()
            self.jobs.setdefault(job.id, _JobRecord(job, now))
        self.invalidate()

    def run_flow(self, echo: str, work: Callable[[JobHandle], Any], *, kind: str,
                 label: str,
                 on_done: Callable[[JobHandle, BaseException | None], None] | None = None,
                 ) -> JobHandle:
        ts = time.strftime("%H:%M")
        seq = self.blocks.begin_block(echo, ts=ts)
        with self._lock:
            self.block_views.append(BlockView(seq=seq, ts=ts, echo=echo))
            self.block_views[:] = self.block_views[-200:]
        try:
            job = self.runner.submit(work, kind=kind, label=label, on_done=on_done)
        except Exception as exc:
            # 提交失败（如后台满额）也要给块头补上结果行，避免悬空块。
            self.blocks.append_line(format_status_line(
                STATUS_FAILURE, label, detail=f"未能启动：{exc}"))
            self.invalidate()
            raise
        self.track_job(job)
        return job

    def bridge_io(self) -> tuple[Callable[[str], str], Callable[[str], None]]:
        return self.bridge_input, self.bridge_output

    def bridge_input(self, prompt: str) -> str:
        request = PendingAsk(prompt=prompt, event=threading.Event())
        with self._lock:
            self.pending_ask = request
        self.invalidate()
        while not request.event.wait(0.2):
            if self.closing.is_set():
                with self._lock:
                    self.pending_ask = None
                raise KeyboardInterrupt(prompt)
        with self._lock:
            self.pending_ask = None
        answer = request.answer
        self.invalidate()
        if answer is None or answer == _CANCEL_TOKEN:
            raise KeyboardInterrupt(prompt)
        return answer

    def resolve_pending(self, text: str | None) -> bool:
        with self._lock:
            request = self.pending_ask
        if request is None:
            return False
        request.answer = _CANCEL_TOKEN if text is None else text
        request.event.set()
        return True

    def bridge_output(self, message: str) -> None:
        self.blocks.append_line(message)
        self.invalidate()
