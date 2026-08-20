from __future__ import annotations

import sys
import types
from pathlib import Path

from novel_rag.identity import GraphKey
from novel_rag.mutations import ChangeSet, MutationResult
from novel_rag.state_review import approve_state_proposal
from novel_rag.writeback import confirm_runtime

from test_generation import make_library as generation_library
from test_state_review import _library as state_library, _runtime as state_runtime
from test_writeback import make_runtime as writeback_runtime


class RecordingCoordinator:
    def __init__(self) -> None:
        self.changeset: ChangeSet | None = None

    def commit(self, changeset: ChangeSet) -> MutationResult:
        self.changeset = changeset
        return MutationResult(status="promoted", yaml_committed=True)


def test_state_default_uses_mutation_composition_root(monkeypatch, tmp_path: Path) -> None:
    library, index = state_library(tmp_path)
    runtime = state_runtime(tmp_path, library)
    coordinator = RecordingCoordinator()
    calls: list[dict[str, Path | str]] = []
    module = types.ModuleType("novel_rag.composition")

    def build_mutation_coordinator(library_root: Path, *, index_directory: Path | None = None):
        calls.append({"library_root": library_root, "index_directory": index_directory})
        return coordinator

    module.build_mutation_coordinator = build_mutation_coordinator
    monkeypatch.setitem(sys.modules, "novel_rag.composition", module)

    result = approve_state_proposal(runtime, library_root=library, index_root=index)

    assert result.status == "promoted"
    assert calls[0]["library_root"] == library
    assert calls[0]["index_directory"] == index
    assert coordinator.changeset is not None
    assert coordinator.changeset.affected_graph_keys == (GraphKey("demo", "main"),)


def test_writeback_default_uses_mutation_composition_root(monkeypatch, tmp_path: Path) -> None:
    library, index = generation_library(tmp_path)
    runtime = writeback_runtime(tmp_path)
    coordinator = RecordingCoordinator()
    calls: list[dict[str, Path | str]] = []
    module = types.ModuleType("novel_rag.composition")

    def build_mutation_coordinator(library_root: Path, *, index_directory: Path | None = None):
        calls.append({"library_root": library_root, "index_directory": index_directory})
        return coordinator

    module.build_mutation_coordinator = build_mutation_coordinator
    monkeypatch.setitem(sys.modules, "novel_rag.composition", module)

    result = confirm_runtime(
        runtime,
        library_root=library,
        index_root=index,
        confirmed=True,
        volume=1,
        chapter=2,
        scene=1,
    )

    assert result.status == "committed"
    assert calls[0]["library_root"] == library
    assert calls[0]["index_directory"] == index
    assert coordinator.changeset is not None
    assert coordinator.changeset.affected_graph_keys == (GraphKey("demo", "main"),)
