"""Regression checks for the domain-independent OS advisory guard."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from novel_rag.std.locks import AdvisoryFileLock


def test_advisory_lock_keeps_stable_file_and_closes_failed_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """依赖：真实OS锁/描述符观测。输入：同路径双实例。输出：互斥且失败无泄漏。实现：占用时捕捉第二描述符并验证已关闭、释放后复用原文件。"""

    path = tmp_path / "stable.guard"
    held = AdvisoryFileLock(path)
    competing = AdvisoryFileLock(path)
    opened: list[int] = []
    original_open = os.open

    def observe_open(*args, **kwargs) -> int:
        """依赖：原os.open。输入：打开参数。输出：原描述符。实现：记录真实打开结果供关闭验证。"""

        descriptor = original_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    with held:
        identity = path.stat().st_ino
        monkeypatch.setattr(os, "open", observe_open)
        with pytest.raises(BlockingIOError):
            competing.acquire()
        assert len(opened) == 1
        with pytest.raises(OSError):
            os.fstat(opened[0])
    assert path.exists()
    assert path.stat().st_ino == identity
    with competing:
        assert path.stat().st_ino == identity


def test_advisory_context_releases_on_caller_failure(tmp_path: Path) -> None:
    """依赖：真实OS锁。输入：上下文内异常。输出：异常传播且后续可获取。实现：主动抛错后用另一实例重取相同稳定文件。"""

    path = tmp_path / "stable.guard"
    with pytest.raises(ValueError, match="caller failure"):
        with AdvisoryFileLock(path):
            raise ValueError("caller failure")
    with AdvisoryFileLock(path):
        assert path.exists()


def test_advisory_unlock_failure_still_closes_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """依赖：OS锁/原生解锁故障注入。输入：解锁API报错。输出：错误传播但描述符关闭。实现：只替换解锁一次，随后另一实例仍能取得锁。"""

    path = tmp_path / "stable.guard"
    held = AdvisoryFileLock(path)
    held.acquire()
    if os.name == "nt":
        import msvcrt as native

        operation, unlock = "locking", native.LK_UNLCK
    else:
        import fcntl as native

        operation, unlock = "flock", native.LOCK_UN
    original = getattr(native, operation)

    def fail_unlock(descriptor: int, mode: int, *args) -> None:
        """依赖：原生锁API。输入：描述符与模式。输出：解锁错误或原结果。实现：仅解锁分支注入失败。"""

        if mode == unlock:
            raise OSError("injected unlock failure")
        return original(descriptor, mode, *args)

    monkeypatch.setattr(native, operation, fail_unlock)
    with pytest.raises(OSError, match="injected unlock failure"):
        held.release()
    monkeypatch.setattr(native, operation, original)
    with AdvisoryFileLock(path):
        assert path.exists()
