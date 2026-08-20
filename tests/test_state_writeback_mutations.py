import json
from pathlib import Path

from novel_rag.identity import GraphKey
from novel_rag.mutations import ChangeSet, GraphMutationResult, MutationResult
from novel_rag.state_review import approve_state_proposal
from novel_rag.writeback import confirm_runtime

from test_state_review import _library as state_library, _runtime as state_runtime
from test_writeback import make_runtime as writeback_runtime
from test_generation import make_library as generation_library


class RecordingCoordinator:
    def __init__(self, result: MutationResult | None = None) -> None:
        self.result = result or MutationResult(status="promoted", yaml_committed=True)
        self.changeset = None

    def commit(self, changeset: ChangeSet) -> MutationResult:
        self.changeset = changeset
        return self.result


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

