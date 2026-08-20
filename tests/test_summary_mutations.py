from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
import yaml

from novel_rag.identity import GraphKey
from novel_rag.mutations import (
    GraphMutationResult,
    MutationResult,
    SummaryEditor,
    SummaryError,
    SummaryMutationFailedError,
    SummaryMutationPendingError,
    SummaryUpdate,
    SummaryWriter,
)


class RecordingCoordinator:
    graph_builder = staticmethod(lambda *_args: None)

    def __init__(self, result: MutationResult | None = None) -> None:
        self.changes = []
        self.result = result or MutationResult(
            status="promoted",
            yaml_committed=True,
            graph_results=(GraphMutationResult(GraphKey("demo", "main"), "promoted"),),
        )

    def commit(self, changes):
        self.changes.append(changes)
        return self.result


def _summary_path(tmp_path: Path) -> Path:
    return tmp_path / "library" / "stories" / "demo" / "timelines" / "main" / "summaries" / "scene.yaml"


def _write_summary(path: Path, *, revision: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "metadata": {
                    "document_id": "scene-summary-v1.0",
                    "story_id": "demo",
                    "timeline_id": "main",
                    "document_type": "chapter-summary",
                    "ownership": "auto",
                    "revision": revision,
                },
                "content": "旧摘要",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_summary_writer_default_uses_lazy_composition_and_canonical_key(
    monkeypatch, tmp_path: Path
) -> None:
    seen: dict[str, Path] = {}
    coordinator = RecordingCoordinator()
    module = types.ModuleType("novel_rag.composition")

    def build_mutation_coordinator(*, library_root: Path, index_directory: Path):
        seen.update(library_root=library_root, index_directory=index_directory)
        return coordinator

    module.build_mutation_coordinator = build_mutation_coordinator
    monkeypatch.setitem(sys.modules, "novel_rag.composition", module)

    path = _summary_path(tmp_path)
    result = SummaryWriter(path.parent).write_ai(
        path,
        "自动摘要",
        metadata={"story_id": "demo", "timeline_id": "main"},
    )

    assert result.ownership == "auto"
    assert seen == {
        "library_root": (tmp_path / "library").resolve(),
        "index_directory": (tmp_path / "library" / "index").resolve(),
    }
    assert coordinator.changes[0].affected_graph_keys == (GraphKey("demo", "main"),)


def test_summary_missing_graph_key_fails_closed_with_injected_coordinator(tmp_path: Path) -> None:
    path = tmp_path / "summaries" / "scene.yaml"
    coordinator = RecordingCoordinator()

    with pytest.raises(SummaryError, match="GraphKey"):
        SummaryWriter(path.parent, coordinator=coordinator).write_ai(path, "摘要")
    assert coordinator.changes == []


def test_summary_pending_and_failed_statuses_are_not_hidden_by_yaml_commit(tmp_path: Path) -> None:
    path = _summary_path(tmp_path)
    _write_summary(path)
    pending_result = MutationResult(
        status="pending",
        yaml_committed=True,
        graph_results=(GraphMutationResult(GraphKey("demo", "main"), "pending", error="promotion delayed"),),
    )
    pending = RecordingCoordinator(pending_result)
    editor = SummaryEditor(path.parent, coordinator=pending)
    with pytest.raises(SummaryMutationPendingError) as pending_exc:
        editor.update(SummaryUpdate("scene-summary-v1.0", 1, "用户摘要"))
    assert pending_exc.value.result is pending_result
    assert "pending" in str(pending_exc.value)

    failed_result = MutationResult(
        status="failed",
        yaml_committed=False,
        graph_results=(GraphMutationResult(GraphKey("demo", "main"), "failed", error="graph failed"),),
        error="graph failed",
    )
    failed = RecordingCoordinator(failed_result)
    editor = SummaryEditor(path.parent, coordinator=failed)
    with pytest.raises(SummaryMutationFailedError) as failed_exc:
        editor.update(SummaryUpdate("scene-summary-v1.0", 1, "用户摘要"))
    assert failed_exc.value.result is failed_result
    assert "failed" in str(failed_exc.value)
