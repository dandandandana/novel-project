"""JobRunner：阻塞业务调用统一进 daemon worker 线程；事件线程安全投递。"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .state import STATUS_CANCELLED, STATUS_FAILURE, STATUS_SUCCESS


@dataclass
class JobHandle:
    id: str
    kind: str
    label: str
    started: float = field(default_factory=time.monotonic)
    progress: float | None = None
    detail: str | None = None
    cancelled: bool = False
    done: bool = False

    def cancel(self) -> None:
        self.cancelled = True


class JobRunner:
    """每个任务一个守护线程；emit/progress/finish 经 sink 投递给 adapter。

    取消语义：cancel 仅置位协作标志并冻结呈现（⊘）；底层线程无法被强杀，
    后续输出被抑制。on_done 在 worker 线程回调，只允许触碰 adapter（线程安全）。
    """

    def __init__(self, sink: Callable[[dict], None], max_active: int = 8,
                 time_fn: Callable[[], float] = time.monotonic) -> None:
        self._sink = sink
        self._time_fn = time_fn
        self._max_active = max_active
        self._lock = threading.Lock()
        self._jobs: dict[str, JobHandle] = {}
        self._seq = 0

    @property
    def time_fn(self) -> Callable[[], float]:
        return self._time_fn

    def active_handles(self) -> tuple[JobHandle, ...]:
        with self._lock:
            return tuple(job for job in self._jobs.values() if not job.done)

    def all_handles(self) -> tuple[JobHandle, ...]:
        with self._lock:
            return tuple(self._jobs.values())

    def handle(self, job_id: str) -> JobHandle | None:
        with self._lock:
            return self._jobs.get(job_id)

    def submit(self, work: Callable[[JobHandle], Any], *, kind: str, label: str,
               on_done: Callable[[JobHandle, BaseException | None], None] | None = None,
               ) -> JobHandle:
        with self._lock:
            active = sum(1 for job in self._jobs.values() if not job.done)
            if active >= self._max_active:
                raise RuntimeError(f"后台任务已达上限 {self._max_active}")
            self._seq += 1
            job = JobHandle(id=f"job-{self._seq}", kind=kind, label=label)
            self._jobs[job.id] = job
        thread = threading.Thread(target=self._wrap, name=f"console-{job.id}",
                                  args=(job, work, on_done), daemon=True)
        thread.start()
        return job

    def emit(self, job: JobHandle, text: str) -> None:
        if job.cancelled or job.done:
            return
        self._sink({"type": "line", "job": job, "text": text})

    def progress(self, job: JobHandle, detail: str | None = None,
                 value: float | None = None) -> None:
        if job.cancelled or job.done:
            return
        self._sink({"type": "progress", "job": job, "detail": detail, "value": value})

    def shutdown(self) -> None:
        pass

    def _wrap(self, job: JobHandle, work: Callable[[JobHandle], Any],
              on_done: Callable[[JobHandle, BaseException | None], None] | None) -> None:
        error: BaseException | None = None
        try:
            work(job)
        except BaseException as exc:  # noqa: BLE001 - 失败定格为 ✗ 块
            error = exc
        with self._lock:
            job.done = True
        if error is not None:
            status = STATUS_CANCELLED if job.cancelled else STATUS_FAILURE
            self._sink({"type": "finish", "job": job, "status": status, "error": error})
        else:
            status = STATUS_CANCELLED if job.cancelled else STATUS_SUCCESS
            self._sink({"type": "finish", "job": job, "status": status})
        if on_done is not None:
            try:
                on_done(job, error)
            except Exception as exc:  # noqa: BLE001 - 回调失败不拖垮任务收尾
                self._sink({"type": "line", "job": job,
                            "text": f"⚠ 收尾回调失败: {exc}"})
