import json
from pathlib import Path

import pytest

from novel_rag.documents import read_yaml_mapping
from novel_rag.identity import GraphKey
from novel_rag.mutations import ChangeSet, GraphMutationResult, MutationResult
from novel_rag.state_review import StateReviewError, approve_state_proposal
from novel_rag.writeback import WritebackError, confirm_runtime

from test_state_review import _library as state_library, _runtime as state_runtime
from test_writeback import make_runtime as writeback_runtime
from test_generation import make_library as generation_library
from writer_fixtures import write_yaml


class RecordingCoordinator:
    def __init__(self, result: MutationResult | None = None) -> None:
        self.result = result or MutationResult(status="promoted", yaml_committed=True)
        self.changeset = None

    def commit(self, changeset: ChangeSet) -> MutationResult:
        self.changeset = changeset
        return self.result


@pytest.mark.parametrize("operation", ["confirm", "approve"])
def test_legacy_child_cannot_reassign_existing_parent_source(tmp_path: Path, operation: str) -> None:
    """依赖：旧版共用夹具和记录型 Coordinator。输入：同一 legacy 物理槽位上的父资料与子操作。输出：拒绝、无提交、原件字节不变。实现：分别经过确认/状态晋升的实际入口。"""
    library, index = state_library(tmp_path)
    proposal = state_runtime(tmp_path, library)
    book = library / "stories/demo"
    write_yaml(book / "snapshots/branch.yaml", {"state": "test"})
    write_yaml(book / "registry/timelines.yaml", {"timelines": [
        {"story_id": "demo", "timeline_id": "main"},
        {"story_id": "demo", "timeline_id": "child", "parent_timeline_id": "main",
         "divergence_at": "volume-01/chapter-01/scene-01", "divergence_snapshot": "snapshots/branch.yaml"},
    ]})
    history = book / "history/volume-01/chapter-001/scene-001.yaml"
    source = read_yaml_mapping(history)
    coordinator = RecordingCoordinator()
    if operation == "confirm":
        runtime = writeback_runtime(tmp_path / "child-run")
        source["content"] = (runtime / "final.txt").read_text(encoding="utf-8")
        protected = history
    else:
        runtime = proposal
        source["metadata"]["timeline_id"] = "child"
        protected = book / "character-state/current/jia.yaml"
    write_yaml(history, source)
    contract_path = runtime / "contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["request"]["timeline_id"] = "child"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    before = protected.read_bytes()
    if operation == "confirm":
        with pytest.raises(WritebackError, match="scope_denied"):
            confirm_runtime(runtime, library_root=library, index_root=index, confirmed=True,
                            volume=1, chapter=1, scene=1, coordinator=coordinator)
    else:
        with pytest.raises(StateReviewError, match="scope_denied"):
            approve_state_proposal(runtime, library_root=library, index_root=index, coordinator=coordinator)
    assert coordinator.changeset is None
    assert protected.read_bytes() == before


def test_state_approval_submits_changeset_to_injected_coordinator(tmp_path: Path) -> None:
    library, index = state_library(tmp_path)
    runtime = state_runtime(tmp_path, library)
    coordinator = RecordingCoordinator()

    result = approve_state_proposal(
        runtime,
        library_root=library,
        index_root=index,
        coordinator=coordinator,
    )

    assert result.status == "promoted"
    assert isinstance(coordinator.changeset, ChangeSet)
    assert coordinator.changeset.affected_graph_keys == (GraphKey("demo", "main"),)
    assert any(path.name == "jia.yaml" for path in coordinator.changeset.files)


def test_writeback_submits_history_changeset_to_injected_coordinator(tmp_path: Path) -> None:
    library, index = generation_library(tmp_path)
    runtime = writeback_runtime(tmp_path)
    coordinator = RecordingCoordinator()

    result = confirm_runtime(
        runtime,
        library_root=library,
        index_root=index,
        confirmed=True,
        volume=1,
        chapter=2,
        scene=1,
        coordinator=coordinator,
    )

    assert result.status == "committed"
    assert isinstance(coordinator.changeset, ChangeSet)
    assert coordinator.changeset.affected_graph_keys == (GraphKey("demo", "main"),)
    assert any(path.name == "scene-001.yaml" for path in coordinator.changeset.files)


def test_writeback_surfaces_pending_graph_promotion(tmp_path: Path) -> None:
    library, index = generation_library(tmp_path)
    runtime = writeback_runtime(tmp_path)
    key = GraphKey("demo", "main")
    coordinator = RecordingCoordinator(
        MutationResult(
            status="pending",
            yaml_committed=True,
            graph_results=(GraphMutationResult(key, "pending", error="file locked"),),
        )
    )

    result = confirm_runtime(
        runtime,
        library_root=library,
        index_root=index,
        confirmed=True,
        volume=1,
        chapter=2,
        scene=1,
        coordinator=coordinator,
    )

    assert result.status == "pending"
    proposal = json.loads((runtime / "state-writeback-proposal.json").read_text(encoding="utf-8"))
    assert proposal["status"] == "pending"

