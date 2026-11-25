from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from novel_rag.tui import run_tui
from novel_rag.importers import ImportPreview
from novel_rag.model_config import ModelConfigStore


def _single_story(monkeypatch) -> None:
    monkeypatch.setattr("novel_rag.tui.menu.registered_story_ids", lambda _root: {"demo"})
    monkeypatch.setattr("novel_rag.tui.menu.timeline_ids", lambda _root, _story: ["main"])


def test_tui_can_exit_without_side_effects(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    answers = iter(["q"])
    output: list[str] = []

    assert run_tui(tmp_path / "library", input_fn=lambda _prompt: next(answers), output=output.append) == 0
    assert output[-1] == "已退出。"


def test_tui_generate_maps_simple_form_to_existing_runtime(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    monkeypatch.setenv("NOVEL_RAG_MODEL", "writer")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    captured = {}

    def fake_generate(request, model, **kwargs):
        captured.update(request=request, model=model, kwargs=kwargs)
        return SimpleNamespace(
            status="pass", warnings=[], text="生成正文",
            extensions={"runtime_dir": str(tmp_path / "outputs" / ".workflow" / "demo" / "task-1")},
        )

    answers = iter(["1", "写一章", "", "", "", "", "", "", "task-1", "q"])
    assert run_tui(
        tmp_path / "library", input_fn=lambda _prompt: next(answers), output=lambda _text: None,
        generate_fn=fake_generate,
    ) == 0

    assert captured["request"]["story_id"] == "demo"
    assert captured["request"]["timeline_id"] == "main"
    assert captured["request"]["outline"] == "写一章"
    assert captured["kwargs"]["task_id"] == "task-1"


def test_tui_confirm_requires_yes_and_forwards_coordinates(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    runtime = tmp_path / "outputs" / ".workflow" / "demo" / "task"
    captured = {}

    def fake_confirm(path, **kwargs):
        captured.update(path=path, kwargs=kwargs)
        return SimpleNamespace(status="committed", history_path="history/scene-001.yaml")

    answers = iter(["4", str(runtime), "", "2", "", "YES", "q"])
    assert run_tui(
        tmp_path / "library", input_fn=lambda _prompt: next(answers), output=lambda _text: None,
        confirm_fn=fake_confirm,
    ) == 0

    assert captured["path"] == runtime
    assert captured["kwargs"]["confirmed"] is True
    assert captured["kwargs"]["volume"] == 1
    assert captured["kwargs"]["chapter"] == 2
    assert captured["kwargs"]["scene"] == 1


def test_tui_uploads_outline_and_remembers_it(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    source = tmp_path / "outline.txt"
    source.write_text("大纲", encoding="utf-8")
    imported = tmp_path / "library" / "stories" / "demo" / "outline" / "imported" / "outline.yaml"
    captured = {}

    def fake_import(path, **kwargs):
        captured.update(path=path, kwargs=kwargs)
        return SimpleNamespace(status="imported", path=imported)

    monkeypatch.setattr("novel_rag.tui.menu.import_outline", fake_import)
    monkeypatch.setattr("novel_rag.tui.menu.preview_outline", lambda *_args, **_kwargs: ImportPreview(
        "ready", imported, "outline-v1.0", "outline", "1.0", "outline-demo-main-v01-c002"
    ))
    answers = iter(["6", str(source), "", "", "2", "", "IMPORT", "q"])
    assert run_tui(
        tmp_path / "library", input_fn=lambda _prompt: next(answers), output=lambda _text: None,
    ) == 0
    assert captured["path"] == source
    assert captured["kwargs"]["chapter"] == 2


def test_tui_task_conflict_requires_new_id(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    monkeypatch.setenv("NOVEL_RAG_MODEL", "writer")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    existing = tmp_path / "outputs" / ".workflow" / "demo" / "task-1"
    existing.mkdir(parents=True)
    (existing / "result.json").write_text("{}", encoding="utf-8")
    captured = {}

    def fake_generate(_request, _model, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="pass", warnings=[], text="正文",
                               extensions={"runtime_dir": str(existing.parent / "task-2")})

    answers = iter(["1", "写一章", "", "", "", "", "", "", "task-1", "NEW", "task-2", "q"])
    assert run_tui(tmp_path / "library", input_fn=lambda _prompt: next(answers),
                   output=lambda _text: None, generate_fn=fake_generate) == 0
    assert captured["task_id"] == "task-2"


def test_confirm_review_shows_full_text_and_collects_metadata(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    runtime = tmp_path / "outputs" / ".workflow" / "demo" / "task"
    runtime.mkdir(parents=True)
    (runtime / "contract.json").write_text(
        '{"request":{"story_id":"demo","timeline_id":"main"}}', encoding="utf-8")
    (runtime / "result.json").write_text(
        '{"status":"pass_with_warnings","attempts":1,"warnings":["长度偏长"],'
        '"validation":{"issues":[{"severity":"warning","message":"长度偏长"}]}}', encoding="utf-8")
    (runtime / "final.txt").write_text("这是需要完整复核的正文。", encoding="utf-8")
    captured = {}
    output: list[str] = []

    def fake_confirm(_path, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="committed", history_path="history.yaml", cleaned_files=4)

    answers = iter(["4", str(runtime), "", "2", "", "标题", "主角", "a,b", "home", "YES", "q"])
    assert run_tui(tmp_path / "library", input_fn=lambda _prompt: next(answers), output=output.append,
                   confirm_fn=fake_confirm) == 0
    assert any("这是需要完整复核的正文" in item for item in output)
    assert captured["title"] == "标题"
    assert captured["character_ids"] == ["a", "b"]


def test_tui_reviews_and_approves_state_proposal(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    runtime = tmp_path / "outputs" / ".workflow" / "demo" / "task"
    captured = {}

    def inspect(path, **_kwargs):
        return {"runtime": str(path), "status": "needs_review", "character_ids": ["hero"]}

    def approve(path, **kwargs):
        captured.update(path=path, kwargs=kwargs)
        return SimpleNamespace(status="promoted")

    answers = iter(["5", str(runtime), "APPROVE", "已核对", "", "q"])
    assert run_tui(tmp_path / "library", input_fn=lambda _prompt: next(answers),
                   output=lambda _text: None, state_inspect_fn=inspect,
                   state_approve_fn=approve) == 0
    assert captured["path"] == runtime
    assert captured["kwargs"]["note"] == "已核对"


def test_tui_continues_guidance_as_child_runtime(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    monkeypatch.setenv("NOVEL_RAG_MODEL", "writer")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    runtime = tmp_path / "outputs" / ".workflow" / "demo" / "task"
    runtime.mkdir(parents=True)
    (runtime / "result.json").write_text(
        '{"status":"user_guidance_required","warnings":[],"text":"旧稿"}', encoding="utf-8")
    captured = {}

    def resume(path, guidance, _model, **kwargs):
        captured.update(path=path, guidance=guidance, kwargs=kwargs)
        return SimpleNamespace(status="pass", warnings=[], text="新稿",
                               extensions={"runtime_dir": str(runtime.parent / "task-guided")})

    answers = iter(["3", str(runtime), "保留结局，补足动机", "task-guided", "", "q"])
    assert run_tui(tmp_path / "library", input_fn=lambda _prompt: next(answers),
                   output=lambda _text: None, resume_fn=resume) == 0
    assert captured["guidance"] == "保留结局，补足动机"
    assert captured["kwargs"]["task_id"] == "task-guided"


def test_tui_previews_rag_before_import(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    source = tmp_path / "canon.yaml"
    captured = {}
    preview = ImportPreview("ready", tmp_path / "target.yaml", "canon-v1.0", "canon", "1.0", "canon")
    monkeypatch.setattr("novel_rag.tui.menu.preview_rag_yaml", lambda *_args, **_kwargs: preview)
    monkeypatch.setattr(
        "novel_rag.tui.menu.import_rag_yaml",
        lambda path, **kwargs: captured.update(path=path, kwargs=kwargs)
        or SimpleNamespace(status="imported", path=tmp_path / "target.yaml"),
    )
    answers = iter(["7", str(source), "IMPORT", "q"])
    assert run_tui(tmp_path / "library", input_fn=lambda _prompt: next(answers),
                   output=lambda _text: None) == 0
    assert captured["path"] == source


def test_tui_creates_feedback_from_simple_form(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(path="feedback.yaml")

    monkeypatch.setattr("novel_rag.tui.menu.create_feedback", fake_create)
    answers = iter(["12", "1", "对白太快", "需要留出反应", "后续章节", "补足动作反馈",
                    "", "runtime", "task-1", "FEEDBACK", "q"])
    assert run_tui(tmp_path / "library", input_fn=lambda _prompt: next(answers),
                   output=lambda _text: None) == 0
    assert captured["issue"] == "对白太快"
    assert captured["correction_rule"] == ["补足动作反馈"]


def test_tui_feedback_requires_explicit_confirmation(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    called = False

    def fake_create(**_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("novel_rag.tui.menu.create_feedback", fake_create)
    answers = iter(["12", "1", "问题", "意见", "后续", "修正", "", "runtime", "task", "取消", "q"])
    assert run_tui(tmp_path / "library", input_fn=lambda _prompt: next(answers),
                   output=lambda _text: None) == 0
    assert called is False


def test_empty_library_runs_story_and_preference_wizard(tmp_path: Path) -> None:
    library = tmp_path / "novel-rag"
    answers = iter([
        "demo", "示例小说", "", "", "", "CREATE",
        "", "", "", "", "", "", "", "", "", "SAVE", "q",
    ])
    assert run_tui(library, input_fn=lambda _prompt: next(answers), output=lambda _text: None) == 0
    preferences = library / "stories" / "demo" / "author-preferences.txt"
    assert preferences.is_file()
    assert "【未指定】" in preferences.read_text(encoding="utf-8")


def test_tui_uses_active_local_model_profile_without_environment(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    monkeypatch.delenv("NOVEL_RAG_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = tmp_path / "model-api.json"
    store = ModelConfigStore(config)
    store.set_profile("local", {"base_url": "http://127.0.0.1:1234/v1", "model": "writer",
                                "mode": "chat", "no_auth": True})
    store.set_active("local")
    captured = {}

    def fake_generate(_request, model, **kwargs):
        captured.update(model=model, kwargs=kwargs)
        return SimpleNamespace(status="pass", warnings=[], text="正文",
                               extensions={"runtime_dir": str(tmp_path / "outputs/.workflow/demo/task")})

    answers = iter(["1", "写一章", "", "", "", "", "", "", "task", "q"])
    assert run_tui(tmp_path / "library", input_fn=lambda _prompt: next(answers),
                   output=lambda _text: None, generate_fn=fake_generate,
                   model_config_path=config) == 0
    assert captured["model"].model == "writer"
    assert captured["model"].api_key is None


def test_tui_can_save_local_api_profile(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    config = tmp_path / "model-api.json"
    answers = iter(["11", "1", "local", "http://localhost:8000/v1", "writer", "chat",
                    "yes", "", "", "", "SAVE", "q"])
    assert run_tui(tmp_path / "library", input_fn=lambda _prompt: next(answers),
                   output=lambda _text: None, model_config_path=config) == 0
    profile = ModelConfigStore(config).get()
    assert profile is not None
    assert profile.name == "local"
    assert profile.no_auth is True


def test_tui_can_save_advanced_api_fields(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    config = tmp_path / "model-api.json"
    answers = iter(["11", "1", "local", "http://localhost:8000/v1", "writer", "chat",
                    "yes", "30", "2", "4096", "SAVE", "q"])
    assert run_tui(tmp_path / "library", input_fn=lambda _prompt: next(answers),
                   output=lambda _text: None, model_config_path=config) == 0
    profile = ModelConfigStore(config).get()
    assert profile is not None
    assert profile.timeout == 30.0
    assert profile.retries == 2
    assert profile.max_output_tokens == 4096


def test_tui_lowercase_confirmation_still_confirms(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    called = False

    def fake_create(**kwargs):
        nonlocal called
        called = True
        return SimpleNamespace(path="feedback.yaml")

    monkeypatch.setattr("novel_rag.tui.menu.create_feedback", fake_create)
    answers = iter(["12", "1", "对白太快", "需要留出反应", "后续章节", "补足动作反馈",
                    "", "runtime", "task-1", "feedback", "q"])
    assert run_tui(tmp_path / "library", input_fn=lambda _prompt: next(answers),
                   output=lambda _text: None) == 0
    assert called is True


def test_tui_confirm_accepts_lowercase_yes(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    runtime = tmp_path / "outputs" / ".workflow" / "demo" / "task"
    captured = {}

    def fake_confirm(path, **kwargs):
        captured.update(path=path, kwargs=kwargs)
        return SimpleNamespace(status="committed", history_path="history/scene-001.yaml")

    answers = iter(["4", str(runtime), "", "2", "", "yes", "q"])
    assert run_tui(
        tmp_path / "library", input_fn=lambda _prompt: next(answers), output=lambda _text: None,
        confirm_fn=fake_confirm,
    ) == 0

    assert captured["path"] == runtime
    assert captured["kwargs"]["confirmed"] is True
    assert captured["kwargs"]["volume"] == 1
    assert captured["kwargs"]["chapter"] == 2
    assert captured["kwargs"]["scene"] == 1


def test_tui_ctrl_c_during_action_returns_to_menu(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    monkeypatch.setenv("NOVEL_RAG_MODEL", "writer")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    captured: dict = {}
    phase = {"generated": False, "interrupting": False}

    def wrapped_generate(_request, _model, **kwargs):
        captured.update(kwargs)
        phase["generated"] = True
        return SimpleNamespace(status="pass", warnings=[], text="t",
                               extensions={"runtime_dir": str(tmp_path / "r")})

    def scripted_input(prompt: str) -> str:
        if prompt.startswith("选择"):
            if not phase["generated"]:
                return "1"
            if not phase["interrupting"]:
                phase["interrupting"] = True
                return "1"
            return "q"
        if phase["interrupting"]:
            raise KeyboardInterrupt
        if prompt.startswith("大纲文本"):
            return "写一章"
        return ""

    output: list[str] = []

    assert run_tui(tmp_path / "library", input_fn=scripted_input,
                   output=output.append, generate_fn=wrapped_generate) == 0
    assert re.fullmatch(r"\d{8}", captured["task_id"])
    assert any("已取消当前操作" in item for item in output)
    assert any(item.strip() == "已退出。" for item in output)


def test_tui_exit_tokens(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)

    for token in ("0", "QUIT"):
        output: list[str] = []
        assert run_tui(
            tmp_path / "library",
            input_fn=lambda _prompt, _token=token: _token,
            output=output.append,
        ) == 0
        assert output[-1] == "已退出。"


def test_tui_search_renders_rows(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    rows = [
        SimpleNamespace(score=0.9, document_type="canon", status="active",
                        document_id="d1", title="标题一"),
        SimpleNamespace(score=0.5, document_type="history", status="active",
                        document_id="d2", title="t2"),
    ]
    captured = {}
    monkeypatch.setattr(
        "novel_rag.tui.menu.search_graph",
        lambda *_args, **kwargs: captured.update(kwargs) or rows,
    )
    output: list[str] = []
    answers = iter(["9", "查询词", "", "", "", "q"])

    assert run_tui(
        tmp_path / "library", input_fn=lambda _prompt: next(answers),
        output=output.append,
    ) == 0
    text = "\n".join(output)
    assert "d1" in text
    assert "canon" in text
    assert '"score"' not in text


def test_tui_banner_shows_current_context(tmp_path: Path, monkeypatch) -> None:
    _single_story(monkeypatch)
    output: list[str] = []

    assert run_tui(tmp_path / "library", input_fn=lambda _prompt: "q", output=output.append) == 0
    assert any(
        "作品: demo" in item and "时间线: main" in item
        for item in output
    )
    assert any("库:" in item for item in output)
    assert any("最近任务:" in item for item in output)
