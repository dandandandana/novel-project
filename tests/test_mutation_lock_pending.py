from __future__ import annotations

import json
import multiprocessing
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from novel_rag.cli import build_parser
from novel_rag.identity import GraphKey
from novel_rag.mutations import (
    ChangeSet,
    FileMutationLock,
    GraphBuildArtifact,
    MutationCoordinator,
    MutationLockError,
)


def _lock_worker(path: str, ready: str, release: str) -> None:
    """依赖：FileMutationLock/文件信号。输入：锁与信号路径。输出：子进程成功退出。实现：持锁等待父进程放行后释放。"""
    lock = FileMutationLock(path, stale_after=0)
    lock.acquire()
    Path(ready).write_text("ready", encoding="ascii")
    deadline = time.monotonic() + 10
    while not Path(release).exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    lock.release()


def test_stale_recovery_cannot_delete_a_new_owner_during_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """依赖：真实文件锁/线程事件。输入：旧锁与删除前暂停。输出：竞争者不能越过恢复临界区。实现：在unlink前放行第二写者并检查互斥。"""

    path = tmp_path / "mutation.lock"
    path.write_text(json.dumps({
        "schema_version": 1, "pid": 2_000_000_000,
        "hostname": socket.gethostname(), "acquired_at_epoch": 1.0,
        "token": "dead-owner",
    }), encoding="utf-8")
    recovery = FileMutationLock(path, stale_after=0)
    competing = FileMutationLock(path, stale_after=0)
    at_unlink = threading.Event()
    continue_unlink = threading.Event()
    outcome: list[bool | BaseException] = []
    original_unlink = Path.unlink

    def pause_unlink(target: Path, *args, **kwargs):
        """依赖：事件/原unlink。输入：目标路径。输出：原删除结果。实现：只暂停恢复线程在真实删除前的窗口。"""

        if target == path and threading.current_thread() is worker:
            at_unlink.set()
            if not continue_unlink.wait(10):
                raise TimeoutError("recovery test did not release unlink")
        return original_unlink(target, *args, **kwargs)

    def recover() -> None:
        """依赖：恢复对象。输入：闭包锁。输出：结果或原错误写入列表。实现：线程调用公开恢复入口。"""

        try:
            outcome.append(recovery.recover_stale())
        except BaseException as exc:
            outcome.append(exc)

    worker = threading.Thread(target=recover)
    monkeypatch.setattr(Path, "unlink", pause_unlink)
    worker.start()
    try:
        assert at_unlink.wait(10), "recovery did not reach the vulnerable window"
        with pytest.raises(MutationLockError):
            competing.acquire()
        assert FileMutationLock.read_owner(path)["token"] == "dead-owner"
    finally:
        continue_unlink.set()
        worker.join(timeout=10)
        competing.release()
    assert not worker.is_alive()
    assert outcome == [True]
    competing.acquire()
    try:
        assert FileMutationLock.read_owner(path)["token"] == competing.owner_metadata["token"]
    finally:
        competing.release()


@pytest.mark.parametrize("filename", ["mutation.lock", ".writer.lock"])
@pytest.mark.parametrize("shutdown", ["crash", "release"])
def test_real_process_ownership_and_crash_recovery(tmp_path: Path, filename: str, shutdown: str) -> None:
    """依赖：独立Python进程/真实OS锁。输入：源锁或workspace锁及退出模式。输出：实际owner互斥、死亡恢复及清理。实现：核child自报PID与os._exit/正常退出后的元数据。"""

    path = tmp_path / filename
    ready = tmp_path / "child-ready"
    child = subprocess.Popen([
        sys.executable, "-c",
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "from novel_rag.mutations.locks import FileMutationLock\n"
        "lock = FileMutationLock(sys.argv[1], stale_after=0)\n"
        "lock.acquire()\n"
        "try:\n"
        "    ready = Path(sys.argv[2])\n"
        "    staging = ready.with_suffix('.tmp')\n"
        "    staging.write_text(json.dumps({'pid': os.getpid()}), encoding='ascii')\n"
        "    staging.replace(ready)\n"
        "    if sys.stdin.buffer.readline() == b'crash\\n':\n"
        "        os._exit(73)\n"
        "finally:\n"
        "    lock.release()\n",
        str(path), str(ready),
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    request_sent = False
    owner_pid: int | None = None
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < deadline:
            if child.poll() is not None:
                request_sent = True
                pytest.fail(f"lock child exited before acquiring: {child.communicate(timeout=10)!r}")
            time.sleep(0.02)
        assert ready.exists(), "child did not acquire the lock"
        original = path.read_bytes()
        # Windows venv python.exe may be a launcher; only the actual holder's
        # handshake and lock metadata identify the process under test.
        owner_pid = json.loads(ready.read_text(encoding="ascii"))["pid"]
        assert isinstance(owner_pid, int) and owner_pid != os.getpid()
        assert FileMutationLock.read_owner(path)["pid"] == owner_pid
        assert FileMutationLock._pid_alive(owner_pid) is True
        competing = FileMutationLock(path, stale_after=0)
        with pytest.raises(MutationLockError):
            competing.acquire()
        assert competing.recover_stale() is False
        assert child.poll() is None
        assert path.read_bytes() == original
        request_sent = True
        stdout, stderr = child.communicate(input=f"{shutdown}\n".encode("ascii"), timeout=10)
        assert child.returncode == (73 if shutdown == "crash" else 0), (stdout, stderr)
        assert FileMutationLock._pid_alive(owner_pid) is False
        if shutdown == "crash":
            assert path.read_bytes() == original, "forced process exit must leave owner evidence"
        else:
            assert not path.exists(), "failure-path cleanup must release the real holder's lock"
        competing.acquire()
        try:
            assert FileMutationLock.read_owner(path)["pid"] == os.getpid()
        finally:
            competing.release()
        assert not path.exists()
    finally:
        # On an earlier assertion failure the same actual Python process reads
        # release/EOF, exits its finally block and releases the lock. Never kill
        # a venv launcher and infer that its worker must have died as well.
        child.communicate(input=None if request_sent else b"release\n", timeout=10)
        if owner_pid is not None:
            assert FileMutationLock._pid_alive(owner_pid) is False


@pytest.mark.parametrize("policy", ["disabled", "foreign-host", "unknown-schema", "live", "young", "malformed"])
def test_guard_does_not_weaken_conservative_stale_policy(tmp_path: Path, policy: str) -> None:
    """依赖：真实锁文件及原恢复策略。输入：不可证明过期的元数据。输出：拒绝且字节不变。实现：逐类试取并核公共恢复入口。"""

    path = tmp_path / "mutation.lock"
    owner = {
        "schema_version": 1, "pid": 2_000_000_000,
        "hostname": socket.gethostname(), "acquired_at_epoch": 1.0,
        "token": "preserve-owner",
    }
    if policy == "foreign-host":
        owner["hostname"] = "other-host"
    elif policy == "unknown-schema":
        owner["schema_version"] = 2
    elif policy == "live":
        owner["pid"] = os.getpid()
    elif policy == "young":
        owner["acquired_at_epoch"] = time.time() + 3600
    raw = b"{" if policy == "malformed" else json.dumps(owner).encode("utf-8")
    path.write_bytes(raw)
    lock = FileMutationLock(path, stale_after=None if policy == "disabled" else 0)
    with pytest.raises(MutationLockError):
        lock.acquire()
    if policy == "malformed":
        with pytest.raises(MutationLockError):
            lock.recover_stale()
    else:
        assert lock.recover_stale() is False
    assert path.read_bytes() == raw


def test_failed_metadata_write_releases_guard_and_allows_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """依赖：真实文件及fsync故障注入。输入：owner持久化失败。输出：无残留owner且可重取。实现：失败后恢复fsync并由另一实例获取。"""

    path = tmp_path / "mutation.lock"
    original_fsync = os.fsync

    def fail_fsync(_descriptor: int) -> None:
        """依赖：OSError。输入：描述符。输出：注入错误。实现：模拟已创建owner后的磁盘失败。"""

        raise OSError("injected fsync failure")

    monkeypatch.setattr(os, "fsync", fail_fsync)
    failed = FileMutationLock(path)
    with pytest.raises(MutationLockError, match="injected fsync failure"):
        failed.acquire()
    assert failed.owner_metadata is None
    assert not path.exists()
    monkeypatch.setattr(os, "fsync", original_fsync)
    with FileMutationLock(path):
        assert path.exists()


def test_release_preserves_changed_owner_and_releases_os_guard(tmp_path: Path) -> None:
    """依赖：真实FileMutationLock/标准库guard。输入：持锁时元数据被替换。输出：拒绝删除且释放OS资源。实现：改变token后释放并直接验证guard可重取。"""

    from novel_rag.std.locks import AdvisoryFileLock

    path = tmp_path / "mutation.lock"
    held = FileMutationLock(path)
    held.acquire()
    replacement = {**held.owner_metadata, "token": "external-replacement"}
    raw = json.dumps(replacement).encode("utf-8")
    path.write_bytes(raw)
    with pytest.raises(MutationLockError, match="所有权已变化"):
        held.release()
    assert held.owner_metadata is None
    assert path.read_bytes() == raw
    with AdvisoryFileLock(path.with_name(path.name + ".guard")):
        assert path.read_bytes() == raw


def test_live_guard_remains_exclusive_when_metadata_disappears(tmp_path: Path) -> None:
    """依赖：真实OS guard。输入：持锁中元数据被外部删除。输出：第二写者仍被拒绝。实现：移除owner文件验证guard持有期覆盖整个业务锁生命周期。"""

    path = tmp_path / "mutation.lock"
    held = FileMutationLock(path, stale_after=0)
    held.acquire()
    try:
        path.unlink()
        competing = FileMutationLock(path, stale_after=0)
        with pytest.raises(MutationLockError):
            competing.acquire()
        assert competing.recover_stale() is False
    finally:
        held.release()
    with FileMutationLock(path):
        assert path.exists()


def test_failed_stale_unlink_releases_guard_for_later_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """依赖：真实旧锁/删除错误注入。输入：恢复时unlink失败。输出：旧证据保留且后续可恢复。实现：第一次删除拒绝后恢复文件API并由新实例重试。"""

    path = tmp_path / "mutation.lock"
    raw = json.dumps({
        "schema_version": 1, "pid": 2_000_000_000,
        "hostname": socket.gethostname(), "acquired_at_epoch": 1.0,
        "token": "dead-owner",
    }).encode("utf-8")
    path.write_bytes(raw)
    original_unlink = Path.unlink

    def fail_unlink(target: Path, *args, **kwargs):
        """依赖：原unlink。输入：路径。输出：指定owner删除错误或原返回。实现：仅对测试元数据拒绝删除。"""

        if target == path:
            raise PermissionError("injected unlink failure")
        return original_unlink(target, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    with pytest.raises(MutationLockError, match="injected unlink failure"):
        FileMutationLock(path, stale_after=0).recover_stale()
    assert path.read_bytes() == raw
    monkeypatch.setattr(Path, "unlink", original_unlink)
    with FileMutationLock(path, stale_after=0):
        assert FileMutationLock.read_owner(path)["pid"] == os.getpid()


def test_file_lock_writes_owner_metadata_and_does_not_remove_live_owner(tmp_path: Path) -> None:
    path = tmp_path / "mutation.lock"
    held = FileMutationLock(path, stale_after=0)
    held.acquire()
    try:
        owner = json.loads(path.read_text(encoding="utf-8"))
        assert owner["schema_version"] == 1
        assert owner["pid"] == os.getpid()
        assert owner["hostname"]
        assert owner["token"]
        assert held.owner_metadata["token"] == owner["token"]

        competing = FileMutationLock(path, stale_after=0)
        with pytest.raises(MutationLockError):
            competing.acquire()
        assert path.exists(), "active owner must never be deleted as stale"
    finally:
        held.release()
    assert not path.exists()


def test_file_lock_recovers_only_a_provably_dead_stale_owner(tmp_path: Path) -> None:
    path = tmp_path / "mutation.lock"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pid": 2_000_000_000,
                "hostname": __import__("socket").gethostname(),
                "acquired_at": "2000-01-01T00:00:00+00:00",
                "acquired_at_epoch": 1.0,
                "token": "dead-owner",
            }
        ),
        encoding="utf-8",
    )
    lock = FileMutationLock(path, stale_after=0)
    lock.acquire()
    try:
        owner = json.loads(path.read_text(encoding="utf-8"))
        assert owner["pid"] == os.getpid()
        assert owner["token"] != "dead-owner"
    finally:
        lock.release()


def test_file_lock_uses_windows_safe_exclusive_create_across_processes(tmp_path: Path) -> None:
    path = tmp_path / "mutation.lock"
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    process = multiprocessing.Process(target=_lock_worker, args=(str(path), str(ready), str(release)))
    process.start()
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            if not process.is_alive():
                pytest.fail("lock worker exited before acquiring the lock")
            time.sleep(0.02)
        assert ready.exists()
        competing = FileMutationLock(path, stale_after=0)
        with pytest.raises(MutationLockError):
            competing.acquire()
        release.write_text("release", encoding="ascii")
        process.join(timeout=10)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            release.write_text("release", encoding="ascii")
            process.terminate()
            process.join(timeout=5)


def test_pending_manifest_survives_coordinator_restart_and_retries_path_artifact(tmp_path: Path) -> None:
    source = tmp_path / "source.yaml"
    source.write_text("old", encoding="utf-8")
    target = tmp_path / "blocked-target"
    target.mkdir()
    key = GraphKey("story", "main")

    def build(graph_key, staged):
        staged_path = staged.root / "graph.db"
        staged_path.write_text("accepted", encoding="utf-8")
        return GraphBuildArtifact(graph_key, staged_path, target)

    first = MutationCoordinator(library_root=tmp_path, graph_builder=build)
    result = first.commit(ChangeSet({source: "new"}, (key,), change_id="restartable"))
    assert result.status == "pending"
    assert first.list_pending()[0]["status"] == "pending"
    assert result.pending[0].staged_path is not None
    assert result.pending[0].staged_path.exists()

    target.rmdir()
    second = MutationCoordinator(library_root=tmp_path)
    retried = second.retry_persisted_pending()
    assert len(retried) == 1
    assert retried[0].status == "promoted"
    assert target.read_text(encoding="utf-8") == "accepted"
    assert second.list_pending() == []


def test_production_coordinator_has_library_owned_lock_and_staging_paths(tmp_path: Path) -> None:
    from novel_rag.composition import build_mutation_coordinator

    coordinator = build_mutation_coordinator(tmp_path)
    assert coordinator.lock.path == (tmp_path / ".novel-rag" / "mutation.lock").resolve()
    assert coordinator.staging_root == (tmp_path / ".novel-rag" / "staging").resolve()
    assert coordinator.pending_root == (tmp_path / ".novel-rag" / "pending").resolve()


def test_pending_cli_entry_points_are_reachable() -> None:
    parser = build_parser()
    assert parser.parse_args(["pending", "list"]).pending_action == "list"
    assert parser.parse_args(["pending", "retry"]).pending_action == "retry"

