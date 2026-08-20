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
    """An O_EXCL lock with conservative, inspectable owner metadata.

    The lock file is deliberately created with ``O_EXCL`` instead of relying on
    advisory locking APIs.  This works for the local filesystems used by the
    application on both Windows and POSIX.  A stale lock is removed only when
    all of the following are true: the metadata is valid, it belongs to this
    host, it is older than ``stale_after``, and the recorded PID is definitely
    dead.  Unknown or malformed metadata is treated as an occupied lock; it is
    never guessed away.
    """

    schema_version = 1

    def __init__(self, path: str | Path, *, stale_after: float | None = 3600.0) -> None:
        self.path = Path(path)
        if stale_after is not None and stale_after < 0:
            raise ValueError("stale_after 不能为负数")
        self.stale_after = float(stale_after) if stale_after is not None else None
        self._owned = False
        self._token: str | None = None
        self._owner: dict[str, Any] | None = None

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
        """Return false only when the OS positively reports a missing PID."""

        if pid == os.getpid():
            return True
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
        """Remove this lock only when its owner is provably stale.

        A second read immediately before unlinking closes the common race where
        another process replaced the lock while it was being inspected.  If a
        competing process wins the subsequent create, ``acquire`` loops and
        reports that live owner rather than deleting it.
        """

        if self.stale_after is None:
            return False
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise MutationLockError(f"无法读取 MutationCoordinator 锁: {self.path}: {exc}") from exc
        try:
            owner = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MutationLockError(f"MutationCoordinator 锁元数据损坏: {self.path}") from exc
        if not isinstance(owner, dict) or not self._stale_owner(owner, self.stale_after):
            return False
        try:
            if self.path.read_bytes() != raw:
                return False
            self.path.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError as exc:
            raise MutationLockError(f"无法恢复 stale MutationCoordinator 锁: {self.path}: {exc}") from exc

    def acquire(self) -> None:
        if self._owned:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        owner = {
            "schema_version": self.schema_version,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "acquired_at": datetime.now(timezone.utc).isoformat(),
            "acquired_at_epoch": time.time(),
            "token": secrets.token_hex(16),
        }
        payload = (json.dumps(owner, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        flags |= getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(self.path, flags, 0o600)
            try:
                os.write(descriptor, payload)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self._owned = True
            self._token = str(owner["token"])
            self._owner = owner
            return
        except FileExistsError as exc:
            try:
                recovered = self.recover_stale()
            except MutationLockError:
                raise
            if recovered:
                return self.acquire()
            raise MutationLockError(f"MutationCoordinator 锁已被占用: {self.path}") from exc
        except OSError as exc:
            raise MutationLockError(f"无法创建 MutationCoordinator 锁: {self.path}: {exc}") from exc

    def release(self) -> None:
        if not self._owned:
            return
        try:
            owner = self.read_owner(self.path)
            if owner is None:
                self._owned = False
                self._token = None
                self._owner = None
                return
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

    def __enter__(self) -> "FileMutationLock":
        self.acquire()
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.release()


__all__ = ["FileMutationLock", "MutationLock", "ThreadMutationLock"]
