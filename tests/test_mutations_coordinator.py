from __future__ import annotations

from pathlib import Path

import pytest

from novel_rag.identity import GraphKey
from novel_rag.mutations import (
    ChangeSet,
    FileMutationLock,
    GraphBuildArtifact,
    MutationConflictError,
    MutationCoordinator,
    MutationLockError,
    SummaryConflictError,
    SummaryEditor,
    SummaryOwnershipError,
    SummaryStore,
    SummaryUpdate,
    SummaryWriter,
    summary_usable_in_context,
)
from novel_rag.mutations.types import fingerprint_file


def test_coordinator_builds_all_before_yaml_commit_and_promotes_independently(tmp_path: Path) -> None:
    library = tmp_path / "library"
    library.mkdir()
    source = library / "timeline.yaml"
    source.write_text("version: old\n", encoding="utf-8")
    graph_target = tmp_path / "graphs" / "story-main.db"
    logs: list[str] = []

    def validate(staged):
        logs.append("validate")
        assert staged.staged_path(source).read_text(encoding="utf-8") == "version: new\n"
        assert source.read_text(encoding="utf-8") == "version: old\n"

    def build(key, staged):
        logs.append(f"build:{key.timeline_id}")
        assert source.read_text(encoding="utf-8") == "version: old\n"
        staged_graph = staged.root / f"{key.timeline_id}.db"
        staged_graph.write_text("graph-new", encoding="utf-8")
        return GraphBuildArtifact(key, staged_graph, graph_target)

    def regression(key, artifact, _staged):
        logs.append(f"regression:{key.timeline_id}")
        assert artifact.staged_path.read_text(encoding="utf-8") == "graph-new"

    key = GraphKey("story", "main")
    result = MutationCoordinator(
        library_root=library,
        validate_staged=validate,
        graph_builder=build,
        retrieval_regression=regression,
    ).commit(ChangeSet({source: "version: new\n"}, (key,), change_id="one"))

    assert result.status == "promoted"
    assert result.yaml_committed is True
    assert result.all_promoted is True
    assert result.promoted[0].key == key
    assert source.read_text(encoding="utf-8") == "version: new\n"
    assert graph_target.read_text(encoding="utf-8") == "graph-new"
    assert logs == ["validate", "build:main", "regression:main"]


def test_build_failure_never_commits_yaml(tmp_path: Path) -> None:
    source = tmp_path / "source.yaml"
    source.write_text("old", encoding="utf-8")
    key_a = GraphKey("story", "main")
    key_b = GraphKey("story", "branch")

    def build(key, staged):
        if key == key_b:
            raise RuntimeError("regression failure")
        staged_path = staged.root / "main.db"
        staged_path.write_text("accepted", encoding="utf-8")
        return GraphBuildArtifact(key, staged_path, tmp_path / "main.db")

    result = MutationCoordinator(
        library_root=tmp_path,
        graph_builder=build,
    ).commit(ChangeSet({source: "new"}, (key_a, key_b)))

    assert result.status == "failed"
    assert result.yaml_committed is False
    assert all(item.failed for item in result.graph_results)
    assert source.read_text(encoding="utf-8") == "old"
    assert not (tmp_path / "main.db").exists()


def test_pending_graph_is_retained_and_can_be_retried(tmp_path: Path) -> None:
    source = tmp_path / "source.yaml"
    source.write_text("old", encoding="utf-8")
    target = tmp_path / "graph.db"
    attempts = {"count": 0}

    def promote():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise PermissionError("Windows file is locked")
        target.write_text("promoted", encoding="utf-8")

    def build(key, staged):
        staged_path = staged.root / "graph.db"
        staged_path.write_text("staged", encoding="utf-8")
        return GraphBuildArtifact(key, staged_path, target, promote_callback=promote)

    coordinator = MutationCoordinator(library_root=tmp_path, graph_builder=build)
    result = coordinator.commit(ChangeSet({source: "new"}, (GraphKey("story", "main"),)))
    assert result.status == "pending"
    assert result.yaml_committed is True
    assert result.pending[0].staged_path is not None
    assert result.pending[0].staged_path.exists()
    retried = coordinator.retry_pending(result)
    assert retried.status == "promoted"
    assert retried.all_promoted is True
    assert target.read_text(encoding="utf-8") == "promoted"


def test_external_yaml_edit_is_rejected_before_commit(tmp_path: Path) -> None:
    source = tmp_path / "source.yaml"
    source.write_text("old", encoding="utf-8")

    def build(_key, _staged):
        source.write_text("external", encoding="utf-8")
        return GraphBuildArtifact(GraphKey("story", "main"), tmp_path / "stage.db", tmp_path / "graph.db")

    coordinator = MutationCoordinator(library_root=tmp_path, graph_builder=build)
    with pytest.raises(MutationConflictError, match="外部修改"):
        coordinator.commit(ChangeSet({source: "new"}, (GraphKey("story", "main"),)))
    assert source.read_text(encoding="utf-8") == "external"


def test_expected_file_fingerprint_and_file_lock_are_enforced(tmp_path: Path) -> None:
    source = tmp_path / "source.yaml"
    source.write_text("old", encoding="utf-8")
    lock_path = tmp_path / "mutation.lock"
    held = FileMutationLock(lock_path)
    held.acquire()
    try:
        coordinator = MutationCoordinator(library_root=tmp_path, lock_path=lock_path)
        with pytest.raises(MutationLockError):
            coordinator.commit(
                ChangeSet(
                    {source: "new"},
                    expected_file_fingerprints={source: fingerprint_file(source)},
                )
            )
    finally:
        held.release()


def test_summary_ai_user_revision_and_stale_context_gate(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.yaml"
    writer = SummaryWriter(tmp_path)
    first = writer.write_ai(
        summary_path,
        "自动摘要",
        document_id="summary-1",
        source_fingerprint="sha256:source-1",
        metadata={"story_id": "story", "timeline_id": "main", "document_type": "chapter-summary"},
    )
    assert first.ownership == "auto"
    assert first.revision == 1
    assert summary_usable_in_context(first, source_fingerprint="sha256:source-1") is True

    editor = SummaryEditor(tmp_path)
    updated = editor.update(SummaryUpdate("summary-1", expected_revision=1, content="用户整理摘要"))
    assert updated.ownership == "user"
    assert updated.revision == 2
    assert SummaryStore(tmp_path).find("summary-1").content == "用户整理摘要"

    with pytest.raises(SummaryConflictError):
        editor.update(SummaryUpdate("summary-1", expected_revision=1, content="旧版本覆盖"))
    with pytest.raises(SummaryOwnershipError):
        writer.write_ai(summary_path, "自动任务不能覆盖", source_fingerprint="sha256:source-2")
    assert summary_usable_in_context(updated, source_fingerprint="sha256:source-2") is False

