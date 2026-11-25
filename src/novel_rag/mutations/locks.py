"""Small process/thread lock adapters for coordinated writes."""

from __future__ import annotations

import os
import errno
import json
import secrets
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ..std.locks import AdvisoryFileLock
from .types import MutationLockError


class MutationLock(Protocol):
    def acquire(self) -> None: ...

    def release(self) -> None: ...


class ThreadMutationLock:
    """In-process lock useful for tests and single-process applications."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def acquire(self) -> None:
        self._lock.acquire()

    def release(self) -> None:
        self._lock.release()

    def __enter__(self) -> "ThreadMutationLock":
        self.acquire()
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.release()


class FileMutationLock:
    """Inspectible O_EXCL metadata protected by a stable local OS guard.

    The adjacent ``.guard`` file is never removed or replaced. Its advisory lock
    is held throughout ownership, including stale recovery and metadata removal.
    Old schema-1 metadata still requires the same host, age and definitely-dead
    PID before removal. Unknown metadata fails closed. Older binaries do not
    participate in the guard protocol and must not write concurrently.
    """

    schema_version = 1

    def __init__(self, path: str | Path, *, stale_after: float | None = 3600.0) -> None:
        """依赖：Path/AdvisoryFileLock。输入：元数据路径及过期秒数。输出：未持有实例。实现：配置稳定guard及原schema恢复策略。"""

        self.path = Path(path)
        if stale_after is not None and stale_after < 0:
            raise ValueError("stale_after 不能为负数")
        self.stale_after = float(stale_after) if stale_after is not None else None
        self._owned = False
        self._token: str | None = None
        self._owner: dict[str, Any] | None = None
        self._guard = AdvisoryFileLock(self.path.with_name(self.path.name + ".guard"))
        self._state_lock = threading.RLock()

    @property
    def owner_metadata(self) -> dict[str, Any] | None:
        """Return a copy of this instance's owner metadata, if acquired."""

        return dict(self._owner) if self._owner is not None else None

    @classmethod
    def read_owner(cls, path: str | Path) -> dict[str, Any] | None:
        """Read lock metadata without changing or recovering the lock.

        ``None`` means the file is absent.  Malformed JSON is reported as a
        ``MutationLockError`` so callers cannot accidentally treat an unknown
        owner as safe to remove.
        """

        target = Path(path)
        try:
            raw = target.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise MutationLockError(f"无法读取 MutationCoordinator 锁: {target}: {exc}") from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MutationLockError(f"MutationCoordinator 锁元数据损坏: {target}") from exc
        if not isinstance(value, dict):
            raise MutationLockError(f"MutationCoordinator 锁元数据无效: {target}")
        return value

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        """依赖：OS/Windows只读进程查询。输入：owner PID。输出：存活或未知为True。实现：Windows用OpenProcess/GetExitCodeProcess并释放handle，避免os.kill(pid,0)终止进程。"""

        if pid == os.getpid():
            return True
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.GetExitCodeProcess.restype = wintypes.BOOL
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return ctypes.get_last_error() != 87
            try:
                code = wintypes.DWORD()
                return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
            finally:
                kernel.CloseHandle(handle)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # The process exists but this user cannot signal it.
            return True
        except OSError as exc:
            # ESRCH is the POSIX/Windows-compatible no-process answer.  Other
            # errors are deliberately treated as alive/unknown for safety.
            if getattr(exc, "errno", None) == errno.ESRCH:
                return False
            # ``os.kill(pid, 0)`` on Windows reports an invalid/nonexistent PID
            # as ERROR_INVALID_PARAMETER/ERROR_INVALID_HANDLE rather than
            # raising ProcessLookupError.
            if getattr(exc, "winerror", None) in {6, 87, 1168}:
                return False
            return True
        return True

    @classmethod
    def _stale_owner(cls, owner: dict[str, Any], stale_after: float | None) -> bool:
        """依赖：时钟/主机/PID查询。输入：旧元数据及过期阈值。输出：可证明过期的布尔值。实现：沿schema、同主机、年龄和死亡条件保守判定。"""

        if stale_after is None:
            return False
        if owner.get("schema_version") != cls.schema_version:
            return False
        hostname = owner.get("hostname")
        pid = owner.get("pid")
        token = owner.get("token")
        acquired = owner.get("acquired_at_epoch")
        if hostname != socket.gethostname() or not isinstance(pid, int) or pid <= 0:
            return False
        if not isinstance(token, str) or not token:
            return False
        if not isinstance(acquired, (int, float)):
            return False
        if time.time() - float(acquired) <= stale_after:
            return False
        return not cls._pid_alive(pid)

    def recover_stale(self) -> bool:
        """依赖：稳定OS guard/原过期策略。输入：实例锁路径。输出：已移除为True或MutationLockError。实现：锁住读、判定、删除全程，竞争者不能换入新owner。"""

        with self._state_lock:
            if self._owned or self.stale_after is None:
                return False
            try:
                self._guard.acquire()
            except (BlockingIOError, FileNotFoundError):
                return False
            except OSError as exc:
                raise MutationLockError(f"无法锁定 MutationCoordinator guard: {self.path}: {exc}") from exc
            try:
                return self._recover_stale_locked()
            finally:
                self._release_guard()

    def _recover_stale_locked(self) -> bool:
        """依赖：调用方已持guard/read_owner。输入：实例路径和策略。输出：移除结果或MutationLockError。实现：在同一guard内检查旧owner并删除。"""

        owner = self.read_owner(self.path)
        if owner is None or not self._stale_owner(owner, self.stale_after):
            return False
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError as exc:
            raise MutationLockError(f"无法恢复 stale MutationCoordinator 锁: {self.path}: {exc}") from exc

    def acquire(self) -> None:
        """依赖：OS guard/O_EXCL/原元数据。输入：实例路径。输出：持锁或MutationLockError。实现：先独占guard，再恢复旧锁及创建owner，失败释放guard。"""

        with self._state_lock:
            if self._owned:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._guard.acquire()
            except BlockingIOError as exc:
                raise MutationLockError(f"MutationCoordinator 锁已被占用: {self.path}") from exc
            except OSError as exc:
                raise MutationLockError(f"无法锁定 MutationCoordinator guard: {self.path}: {exc}") from exc
            try:
                owner = {
                    "schema_version": self.schema_version,
                    "pid": os.getpid(),
                    "hostname": socket.gethostname(),
                    "acquired_at": datetime.now(timezone.utc).isoformat(),
                    "acquired_at_epoch": time.time(),
                    "token": secrets.token_hex(16),
                }
                payload = (json.dumps(owner, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
                try:
                    self._create_owner(payload)
                except FileExistsError:
                    if not self._recover_stale_locked():
                        raise MutationLockError(f"MutationCoordinator 锁已被占用: {self.path}")
                    self._create_owner(payload)
                self._owned = True
                self._token = str(owner["token"])
                self._owner = owner
            except OSError as exc:
                raise MutationLockError(f"无法创建 MutationCoordinator 锁: {self.path}: {exc}") from exc
            finally:
                if not self._owned:
                    self._release_guard()

    def _release_guard(self) -> None:
        """依赖：AdvisoryFileLock。输入：本实例guard。输出：释放或MutationLockError。实现：保留基础库资源释放语义并适配业务异常。"""

        try:
            self._guard.release()
        except OSError as exc:
            raise MutationLockError(f"无法释放 MutationCoordinator guard: {self.path}: {exc}") from exc

    def _create_owner(self, payload: bytes) -> None:
        """依赖：调用方已持guard/os。输入：原schema字节。输出：已落盘文件或OSError。实现：O_EXCL创建、完整写入并fsync，失败清理自己的未完成文件。"""

        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        flags |= getattr(os, "O_BINARY", 0)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            try:
                with os.fdopen(descriptor, "wb", closefd=False) as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                os.close(descriptor)
        except BaseException:
            self.path.unlink(missing_ok=True)
            raise

    def release(self) -> None:
        """依赖：已持guard/read_owner。输入：实例token。输出：释放或MutationLockError。实现：核验token后删除元数据，异常也释放guard与实例状态。"""

        with self._state_lock:
            if not self._owned:
                return
            try:
                owner = self.read_owner(self.path)
                if owner is not None:
                    if not self._token or owner.get("token") != self._token:
                        raise MutationLockError(
                            f"MutationCoordinator 锁所有权已变化，拒绝删除: {self.path}"
                        )
                    self.path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise MutationLockError(f"无法释放 MutationCoordinator 锁: {self.path}: {exc}") from exc
            finally:
                self._owned = False
                self._token = None
                self._owner = None
                self._release_guard()

    def __enter__(self) -> "FileMutationLock":
        """依赖：acquire。输入：实例。输出：持锁实例。实现：取得业务锁后返回自身。"""

        self.acquire()
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        """依赖：release。输入：上下文退出信息。输出：无。实现：退出时释放业务锁。"""

        self.release()


__all__ = ["FileMutationLock", "MutationLock", "ThreadMutationLock"]
