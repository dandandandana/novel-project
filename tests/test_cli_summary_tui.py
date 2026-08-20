from __future__ import annotations

import json
from pathlib import Path

import yaml

from novel_rag.cli import build_parser
from novel_rag.cli import commands as cli_commands
from novel_rag.mutations import MutationResult
from novel_rag.scaffold import create_story
from novel_rag.tui import menu as tui_menu
from novel_rag.tui.helpers import timeline_ids
from novel_rag.tui.menu import run_tui


class RecordingCoordinator:
    def __init__(self) -> None:
        self.changeset = None

    def commit(self, changeset):
        self.changeset = changeset
        for path, value in changeset.changes.items():
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        return MutationResult(status="promoted", yaml_committed=True)


def _target_library(tmp_path: Path) -> tuple[Path, Path, Path]:
    library = tmp_path / "library"
    (library / "registry").mkdir(parents=True)
    (library / "registry" / "layout.yaml").write_text(
        yaml.safe_dump({"layout_version": "2.0"}), encoding="utf-8"
    )
    (library / "registry" / "stories.yaml").write_text(
        yaml.safe_dump({"stories": []}), encoding="utf-8"
    )
    story = create_story(library, story_id="demo", title="Demo")
    summary_root = story / "timelines" / "main" / "summaries"
    summary_root.mkdir(parents=True, exist_ok=True)
    summary_path = summary_root / "chapter-001.yaml"
    summary_path.write_text(
        yaml.safe_dump(
            {
                "metadata": {
                    "document_id": "summary-1",
                    "story_id": "demo",
                    "timeline_id": "main",
                    "document_type": "chapter-summary",
                    "title": "第一章摘要",
                    "status": "active",
                    "version": "1.0",
                    "ownership": "auto",
                    "revision": 1,
                },
                "content": "自动摘要",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return library, library / "index", summary_path


def test_summary_cli_list_show_edit_and_ai_write_use_target_root(tmp_path, monkeypatch, capsys):
    library, index, summary_path = _target_library(tmp_path)
    coordinator = RecordingCoordinator()
    monkeypatch.setattr(cli_commands, "build_mutation_coordinator", lambda *a, **k: coordinator)

    parser = build_parser()
    list_args = parser.parse_args(
        [
            "--library", str(library), "--index", str(index), "summary",
            "--story", "demo", "--timeline", "main", "list",
        ]
    )
    assert list_args.func(list_args) == 0
    assert json.loads(capsys.readouterr().out)[0]["document_id"] == "summary-1"

    show_args = parser.parse_args(
        [
            "--library", str(library), "summary", "--story", "demo",
            "show", "--document-id", "summary-1",
        ]
    )
    assert show_args.func(show_args) == 0
    assert json.loads(capsys.readouterr().out)["content"] == "自动摘要"

    edit_args = parser.parse_args(
        [
            "--library", str(library), "--index", str(index), "summary",
            "--story", "demo", "edit", "--document-id", "summary-1",
            "--expected-revision", "1", "--content", "用户整理摘要",
        ]
    )
    assert edit_args.func(edit_args) == 0
    edited = json.loads(capsys.readouterr().out)
    assert edited["ownership"] == "user"
    assert edited["revision"] == 2
    assert coordinator.changeset.metadata["summary_update"] is True

    ai_args = parser.parse_args(
        [
            "--library", str(library), "summary", "--story", "demo",
            "write-ai", "--path", "chapter-002.yaml", "--content", "AI 摘要",
        ]
    )
    assert ai_args.func(ai_args) == 0
    written = json.loads(capsys.readouterr().out)
    assert written["ownership"] == "auto"
    assert (summary_path.parent / "chapter-002.yaml").is_file()


def test_summary_cli_edit_uses_real_composition_coordinator(tmp_path, capsys):
    library, index, summary_path = _target_library(tmp_path)
    parser = build_parser()
    args = parser.parse_args(
        [
            "--library", str(library), "--index", str(index), "summary",
            "--story", "demo", "edit", "--document-id", "summary-1",
            "--expected-revision", "1", "--content", "生产组合根摘要",
        ]
    )
    assert args.func(args) == 0
    capsys.readouterr()
    value = yaml.safe_load(summary_path.read_text(encoding="utf-8"))
    assert value["content"] == "生产组合根摘要"
    assert value["metadata"]["ownership"] == "user"


def test_tui_summary_entry_uses_target_scaffold_and_expected_revision(tmp_path, monkeypatch):
    library, index, summary_path = _target_library(tmp_path)
    coordinator = RecordingCoordinator()
    monkeypatch.setattr(tui_menu, "build_mutation_coordinator", lambda *a, **k: coordinator)
    answers = iter(["13", "3", "summary-1", "1", "用户编辑摘要", "7"])

    assert run_tui(
        library,
        index,
        input_fn=lambda _prompt: next(answers),
        output=lambda _text: None,
    ) == 0
    value = yaml.safe_load(summary_path.read_text(encoding="utf-8"))
    assert value["metadata"]["ownership"] == "user"
    assert value["metadata"]["revision"] == 2


def test_tui_target_registry_wins_over_legacy_registry(tmp_path):
    library, _index, _summary = _target_library(tmp_path)
    legacy = library / "stories" / "demo" / "registry"
    legacy.mkdir(parents=True)
    (legacy / "timelines.yaml").write_text(
        yaml.safe_dump(
            {
                "timelines": [
                    {"story_id": "demo", "timeline_id": "legacy-only"}
                ]
            }
        ),
        encoding="utf-8",
    )
    assert timeline_ids(library, "demo") == ["main"]


def test_tui_index_and_search_use_composition_entry_points(tmp_path, monkeypatch):
    library, index, _summary = _target_library(tmp_path)
    monkeypatch.setattr(tui_menu, "build_mutation_coordinator", lambda *a, **k: RecordingCoordinator())
    monkeypatch.setattr(tui_menu, "load_valid_documents", lambda *_a, **_k: ([], []))
    calls: dict[str, object] = {}

    def fake_rebuild(*args, **kwargs):
        calls["index"] = (args, kwargs)
        return []

    def fake_search(*args, **kwargs):
        calls["search"] = (args, kwargs)
        return []

    monkeypatch.setattr(tui_menu, "rebuild_graph_projections", fake_rebuild)
    answers = iter(["6", "14", "query", "7"])
    assert run_tui(
        library,
        index,
        input_fn=lambda _prompt: next(answers),
        output=lambda _text: None,
        search_fn=fake_search,
    ) == 0
    assert "index" in calls
    assert "search" in calls
