"""Local advisory locks whose stable files are never removed by the owner."""

from __future__ import annotations

import errno
import os
from pathlib import Path
import threading


class AdvisoryFileLock:
    """Nonblocking local-process lock; every participant must keep the file stable.

    The OS releases the lock when its descriptor closes or its process dies.
    Metadata, stale policies and business errors belong to callers. The file
    must not be deleted or replaced, including while the lock is unoccupied.
    """

    def __init__(self, path: str | Path) -> None:
        """依赖：Path/threading。输入：稳定锁文件路径。输出：未持有锁实例。实现：延迟打开文件并串行化本实例状态转换。"""

        self.path = Path(path)
        self._descriptor: int | None = None
        self._state_lock = threading.Lock()

    def acquire(self) -> None:
        """依赖：OS及msvcrt/fcntl。输入：实例路径。输出：成功或OSError。实现：非阻塞锁定稳定文件，失败立即关闭描述符。"""

        with self._state_lock:
            if self._descriptor is not None:
                return
            descriptor = os.open(
                self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0), 0o600,
            )
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                os.close(descriptor)
                if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise BlockingIOError(errno.EAGAIN, "lock is occupied", str(self.path)) from exc
                raise
            except BaseException:
                os.close(descriptor)
                raise
            self._descriptor = descriptor

    def release(self) -> None:
        """依赖：OS及msvcrt/fcntl。输入：已持有描述符。输出：释放或OSError。实现：解锁并总是关闭描述符，保留稳定文件。"""

        with self._state_lock:
            descriptor = self._descriptor
            if descriptor is None:
                return
            self._descriptor = None
            try:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def __enter__(self) -> "AdvisoryFileLock":
        """依赖：acquire。输入：实例。输出：持锁实例。实现：取得锁后返回自身。"""

        self.acquire()
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        """依赖：release。输入：上下文退出信息。输出：无。实现：正常及异常退出均释放锁。"""

        self.release()


__all__ = ["AdvisoryFileLock"]
