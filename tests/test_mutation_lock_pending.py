from __future__ import annotations

import json
import multiprocessing
import os
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
    lock = FileMutationLock(path, stale_after=0)
    lock.acquire()
    Path(ready).write_text("ready", encoding="ascii")
    deadline = time.monotonic() + 10
    while not Path(release).exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    lock.release()


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

