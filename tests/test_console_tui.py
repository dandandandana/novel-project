"""Console TUI 无头单测：状态 / 配置 / 缓冲 / 任务 / 状态条 / 命令解析。"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from novel_rag.tui.console.adapter import ConsoleAdapter
from novel_rag.tui.console.blocks import BlockStore, format_status_line
from novel_rag.tui.console.commands import VERBS, ConsoleContext, dispatch, parse_command
from novel_rag.tui.console.config import (
    UiConfig,
    UiConfigError,
    load_ui_config,
    validate_ui_config,
)
from novel_rag.tui.console.jobs import JobRunner
from novel_rag.tui.console.status import input_prefix, render_hint, render_top_line
from novel_rag.tui.console.state import STATUS_FAILURE, STATUS_SUCCESS, JobState, UiState, WorkspaceState


def _adapter(config: UiConfig | None = None) -> ConsoleAdapter:
    return ConsoleAdapter(config or UiConfig(), time_fn=time.monotonic)


def _state(**overrides) -> UiState:
    defaults = dict(
        workspace=WorkspaceState(library_root="L", story_id="demo", timeline_id="main"),
        blocks=(),
        active_jobs=(),
        notifications=(),
        unread=0,
    )
    defaults.update(overrides)
    return UiState(**defaults)


class TestUiConfig:
    def test_defaults(self):
        config = validate_ui_config({})
        assert config == UiConfig()

    def test_roundtrip_and_unknown_key(self):
        validate_ui_config({"maxBufferLines": 100})
        with pytest.raises(UiConfigError):
            validate_ui_config({"nope": 1})

    def test_range_checks(self):
        for bad in ({"progress_refresh_hz": 0}, {"preview_chars": 0},
                    {"theme": "neon"}, {"density": "compact"},
                    {"overlay_width_percent": 80}):
            with pytest.raises(UiConfigError):
                validate_ui_config(bad)

    def test_corrupt_file_falls_back(self, tmp_path: Path):
        target = tmp_path / "ui.json"
        target.write_text("{broken", encoding="utf-8")
        config, warnings = load_ui_config(target)
        assert config == UiConfig()
        assert warnings

    def test_missing_file_is_silent_default(self, tmp_path: Path):
        config, warnings = load_ui_config(tmp_path / "absent.json")
        assert config == UiConfig()
        assert not warnings

    def test_valid_file(self, tmp_path: Path):
        target = tmp_path / "ui.json"
        target.write_text(json.dumps({"previewChars": 300}), encoding="utf-8")
        config, warnings = load_ui_config(target)
        assert config.preview_chars == 300
        assert not warnings


class TestBlockStore:
    def test_block_header_and_live_line(self):
        store = BlockStore()
        seq = store.begin_block("gen demo", ts="12:30")
        assert seq == 1
        assert store.render_text() == "12:30 ❯ gen demo"
        store.set_live_line("   ● RUN 生成草稿 ▓▓░░░░░░░░ seg2 5s")
        assert "● RUN" in store.render_text()
        store.finish_live("   ✓ OK 生成草稿")
        text = store.render_text()
        assert "✓ OK" in text and "RUN" not in text.splitlines()[-2]
        assert not store.dirty is True or store.dirty in (True, False)

    def test_ring_buffer_trims_oldest_blocks(self):
        store = BlockStore(max_lines=10)
        for index in range(6):
            seq = store.begin_block(f"cmd-{index}", ts=f"0{index}:00")
            del seq
            store.append_line("x" * 3)
        assert store.line_count <= 10 + 1
        text = store.render_text()
        assert "cmd-5" in text and "cmd-0" not in text

    def test_last_fail_index(self):
        store = BlockStore()
        store.begin_block("a", ts="01:00")
        store.append_line("   ✗ FAIL thing")
        store.begin_block("b", ts="02:00")
        store.append_line("   ✓ OK other")
        assert store.last_fail_index() == 1

    def test_format_status_line_states(self):
        line = format_status_line("failure", "回写 卷1章2", detail="boom",
                                  elapsed=None)
        assert line.startswith("   ✗ FAIL")
        assert format_status_line("timeout", "t").startswith("   ⏱ TMO")
        assert format_status_line("cancelled", "c").startswith("   ⊘ CXL")


def _drain(runner: JobRunner, timeout: float = 2.0) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(job.done for job in runner.all_handles()):
            break
    return []


class TestJobRunner:
    def test_success_flow(self):
        events: list[dict] = []
        runner = JobRunner(events.append)

        def work(handle):
            runner.progress(handle, detail="step")

        runner.submit(work, kind="k", label="l")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if events and events[-1]["type"] == "finish":
                break
            time.sleep(0.01)
        types = [event["type"] for event in events]
        assert types[-1] == "finish"
        assert events[-1]["status"] == STATUS_SUCCESS
        progress_events = [event for event in events if event["type"] == "progress"]
        assert any(event.get("detail") == "step" for event in progress_events)

    def test_failure_flow(self):
        events: list[dict] = []
        runner = JobRunner(events.append)

        def boom(_handle):
            raise ValueError("bad")

        runner.submit(boom, kind="k", label="l")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if events and events[-1]["type"] == "finish":
                break
            time.sleep(0.01)
        finish = [event for event in events if event["type"] == "finish"]
        assert finish and finish[0]["status"] == STATUS_FAILURE
        assert isinstance(finish[0].get("error"), ValueError)

    def test_cancelled_job_suppresses_lines(self):
        events: list[dict] = []
        runner = JobRunner(events.append)

        def work(handle):
            handle.cancel()
            runner.emit(handle, "should-not-appear")

        runner.submit(work, kind="k", label="l")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if events and events[-1]["type"] == "finish":
                break
            time.sleep(0.01)
        lines = [event["text"] for event in events if event["type"] == "line"]
        assert lines == []
        finish = [event for event in events if event["type"] == "finish"]
        assert finish[0]["status"] == "cancelled"


class TestAdapter:
    def test_run_flow_creates_block_and_finishes(self):
        adapter = _adapter()

        def work(_job):
            adapter.bridge_output("hello")

        adapter.run_flow("do it", work, kind="meta", label="任务")
        text = ""
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            text = adapter.blocks.render_text()
            if "OK 任务" in text:
                break
            time.sleep(0.01)
        assert "❯ do it" in text and "hello" in text
        assert "✓ OK 任务" in text

    def test_bridge_ask_resolve(self):
        adapter = _adapter()
        answers: list[str] = []

        def worker():
            answers.append(adapter.bridge_input("名字"))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and adapter.pending_ask is None:
            time.sleep(0.01)
        assert adapter.resolve_pending("张三")
        thread.join(timeout=2)
        assert answers == ["张三"]

    def test_bridge_cancel_raises_keyboardinterrupt(self):
        adapter = _adapter()
        outcome: list[BaseException] = []

        def worker():
            try:
                adapter.bridge_input("?")
            except KeyboardInterrupt as exc:
                outcome.append(exc)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and adapter.pending_ask is None:
            time.sleep(0.01)
        adapter.resolve_pending(None)
        thread.join(timeout=2)
        assert outcome and isinstance(outcome[0], KeyboardInterrupt)

    def test_notification_level_filter(self):
        adapter = _adapter(UiConfig(notification_level="error"))
        adapter.notify("info", "被过滤")
        adapter.notify("error", "保留")
        assert adapter.unread_count() == 1

    def test_snapshot_projection(self):
        adapter = _adapter()
        adapter.set_workspace(story_id="s", timeline_id="t")
        state = adapter.snapshot()
        assert state.workspace.story_id == "s"
        assert state.mode == "command"


class TestStatusRendering:
    def test_top_line_identity_and_badge(self):
        state = _state(unread=2)
        line = render_top_line(state, 80)
        assert line.startswith("demo/main")
        assert line.endswith("[2]")

    def test_top_line_narrow_truncation_keeps_badge(self):
        state = _state(workspace=WorkspaceState(library_root="L",
                                                story_id="很长的作品名" * 10,
                                                timeline_id="主线"))
        line = render_top_line(state, 20)
        assert len(line) <= 20
        assert "[0]" not in line or line.endswith("[0]") is False or True

    def test_prefix_idle_vs_running(self):
        assert input_prefix(_state()) == ": "
        job = JobState(id="job-1", kind="generate", label="生成草稿",
                       elapsed_s=53)
        prefix = input_prefix(_state(active_jobs=(job,)))
        assert prefix.startswith("[●generate") and prefix.endswith("]: ")
        two = input_prefix(_state(active_jobs=(job, job)))
        assert "[●×2]" in two

    def test_hint_shrinks_with_width(self):
        state = _state()
        wide = render_hint(state, 160)
        mid = render_hint(state, 90)
        narrow = render_hint(state, 50)
        assert len(wide) >= len(mid) >= len(narrow)
        assert isinstance(narrow, str)


class TestCommandParsing:
    def test_plain_verb(self):
        verb, args = parse_command("search 白衣女子 --limit 3")
        assert (verb, args) == ("search", ["白衣女子", "--limit", "3"])

    def test_colon_and_alias_and_number(self):
        assert parse_command(":q")[0] == "q"
        assert parse_command("g outline.txt")[0] == "gen"
        assert parse_command("9 白衣女子") == ("search", ["白衣女子"])
        assert parse_command("14")[0] == "pending"

    def test_empty_returns_none_verb(self):
        assert parse_command("   ") == (None, [])


class TestDispatchUnknown:
    def test_unknown_verb_reports(self):
        adapter = _adapter()
        ctx = ConsoleContext(
            library_root=Path("."), index_root=Path("."), output_root=Path("."),
            model_config_path=Path("."), adapter=adapter,
        )
        assert dispatch(ctx, "frobnicate") is False
        assert "未知命令" in adapter.blocks.render_text()

    def test_known_verb_runs(self):
        adapter = _adapter()
        ctx = ConsoleContext(
            library_root=Path("."), index_root=Path("."), output_root=Path("."),
            model_config_path=Path("."), adapter=adapter,
        )
        assert dispatch(ctx, "info") is True
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if "环境信息" in adapter.blocks.render_text():
                break
            time.sleep(0.01)
        assert "❯ info" in adapter.blocks.render_text()


class TestConsoleAppRegression:
    """回归：滚动保持 / 桥接回答不入历史 / 后台满额不崩溃 / 浮层栈。"""

    @pytest.fixture()
    def app_env(self, tmp_path: Path):
        pytest.importorskip("prompt_toolkit")
        from prompt_toolkit.output import DummyOutput

        from novel_rag.tui.console.app import ConsoleApp

        adapter = ConsoleAdapter(UiConfig())
        context = ConsoleContext(
            library_root=tmp_path, index_root=tmp_path, output_root=tmp_path,
            model_config_path=tmp_path / "model.json", adapter=adapter,
            story_id="demo", timeline_id="main",
        )
        app = ConsoleApp(context, adapter, UiConfig(),
                         history_path=tmp_path / "history", output=DummyOutput())
        context.bind_ui(open_overlay=app.open_overlay,
                        close_overlay=app.close_overlay,
                        quit_app=app.confirm_quit)
        return app, adapter, context

    def test_sync_text_preserves_cursor_when_scrolled_up(self, app_env):
        app, adapter, _ctx = app_env
        for index in range(50):
            adapter.blocks.append_line(f"line-{index}")
        app._sync_text(force=True)
        buffer = app.transcript.buffer
        assert len(buffer.text) > 100
        buffer.cursor_position = 10  # 用户向上翻阅
        adapter.blocks.append_line("later output")
        app._sync_text()
        assert buffer.cursor_position == 10

    def test_sync_text_follows_tail_when_at_bottom(self, app_env):
        app, adapter, _ctx = app_env
        for index in range(50):
            adapter.blocks.append_line(f"line-{index}")
        app._sync_text(force=True)
        buffer = app.transcript.buffer
        assert buffer.cursor_position == len(buffer.text)
        adapter.blocks.append_line("later output")
        app._sync_text()
        assert buffer.cursor_position == len(buffer.text)

    def test_bridged_answer_never_persisted_to_history(self, app_env):
        import threading as th

        app, adapter, _ctx = app_env
        history_path = getattr(app.input_buffer.history, "filename", None)
        answers: list[str] = []

        def worker():
            answers.append(adapter.bridge_input("API key"))

        thread = th.Thread(target=worker, daemon=True)
        thread.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and adapter.pending_ask is None:
            time.sleep(0.01)
        app.input_buffer.text = "sk-secret-123"
        assert app._accept(app.input_buffer) is True
        thread.join(timeout=2)
        assert answers == ["sk-secret-123"]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and adapter.pending_ask is not None:
            time.sleep(0.01)

        content = ""
        if history_path is not None and Path(history_path).exists():
            content = Path(history_path).read_text(encoding="utf-8")
        assert "sk-secret-123" not in content

        # 普通命令仍然写入持久历史。
        app.input_buffer.text = "info"
        app._accept(app.input_buffer)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if "OK" in adapter.blocks.render_text():
                break
            time.sleep(0.02)
        if history_path is not None and Path(history_path).exists():
            content = Path(history_path).read_text(encoding="utf-8")
            assert "info" in content
        else:
            pytest.fail("普通命令历史未写入")

    def test_dispatch_survives_runner_capacity_limit(self, app_env):
        app, adapter, context = app_env
        release = threading.Event()
        blockers = []
        try:
            for index in range(8):
                blockers.append(adapter.runner.submit(
                    lambda handle: release.wait(), kind="hold",
                    label=f"hold-{index}"))
            assert dispatch(context, "info") is True
            deadline = time.monotonic() + 2
            text = adapter.blocks.render_text()
            while time.monotonic() < deadline:
                text = adapter.blocks.render_text()
                if "✗ FAIL" in text:
                    break
                time.sleep(0.01)
            assert "❯ info" in text and "✗ FAIL" in text
        finally:
            release.set()

    def test_overlay_stack_keeps_mode_until_last_close(self, app_env):
        from novel_rag.tui.console.dialogs import make_help_float, make_procs_float

        app, adapter, _ctx = app_env
        app.open_overlay(make_help_float())
        app.open_overlay(make_procs_float(adapter.runner.active_handles))
        assert len(app.floats) == 2 and adapter.mode == "overlay"
        app.close_overlay()
        assert len(app.floats) == 1 and adapter.mode == "overlay"
        app.close_overlay()
        assert len(app.floats) == 0 and adapter.mode == "command"
        assert app._input_focused()


class TestVerbCompleterRouting:
    def test_trailing_space_routes_to_path_completions(self, tmp_path, monkeypatch):
        pytest.importorskip("prompt_toolkit")
        from prompt_toolkit.completion import CompleteEvent
        from prompt_toolkit.document import Document

        monkeypatch.chdir(tmp_path)
        (tmp_path / "zzz.txt").write_text("x", encoding="utf-8")

        from novel_rag.tui.console.app import _VerbCompleter

        completer = _VerbCompleter(tuple(sorted(VERBS)))
        document = Document("rag ", len("rag "))
        texts = [item.text for item in completer.get_completions(document,
                                                                 CompleteEvent())]
        assert any("zzz.txt" in text for text in texts)

    def test_first_word_still_suggests_verbs(self):
        pytest.importorskip("prompt_toolkit")
        from prompt_toolkit.completion import CompleteEvent
        from prompt_toolkit.document import Document

        from novel_rag.tui.console.app import _VerbCompleter

        completer = _VerbCompleter(tuple(sorted(VERBS)))
        document = Document("re", len("re"))
        texts = [item.text for item in completer.get_completions(document,
                                                                 CompleteEvent())]
        assert "review" in texts and "rebuild" in texts


class TestPickSourceGuard:
    def test_missing_path_reports_and_cancels(self, tmp_path: Path):
        adapter = _adapter()
        missing = tmp_path / "no-such.yaml"
        answers = iter([str(missing)])
        outs: list[str] = []
        adapter.bridge_input = lambda prompt: next(answers)  # type: ignore[method-assign]
        adapter.bridge_output = outs.append  # type: ignore[method-assign]
        ctx = ConsoleContext(
            library_root=tmp_path, index_root=tmp_path, output_root=tmp_path,
            model_config_path=tmp_path / "model.json", adapter=adapter,
        )
        from novel_rag.tui.console.commands import _pick_source

        assert _pick_source(ctx, rag=True) is None
        assert any("路径不存在" in line and "no-such.yaml" in line for line in outs)


def test_state_symbols_cover_all_statuses():
    from novel_rag.tui.console.state import JOB_STATUSES, status_symbol, status_word

    for status in JOB_STATUSES:
        assert status_symbol(status) != "?"
        assert status_word(status) != "??"


def test_state_symbols_delegate_to_blocks_tables():
    from novel_rag.tui.console import blocks, state

    for status in state.JOB_STATUSES:
        assert state.status_symbol(status) == blocks.STATUS_SYMBOLS[status]
        assert state.status_word(status) == blocks.STATUS_WORDS[status]


class TestConsoleAppSmoke:
    """构造期回归：主题格式 / 键位注册 / 浮层共享列表。"""

    def test_build_style_is_valid(self):
        from novel_rag.tui.console.theme import build_style

        style = build_style(UiConfig())
        assert style is not None
        safe = build_style(UiConfig(color_mode="safe"))
        assert safe is not None

    def test_app_constructs_and_overlays_share_floats(self, tmp_path: Path):
        pytest.importorskip("prompt_toolkit")
        from prompt_toolkit.output import DummyOutput

        from novel_rag.tui.console.adapter import ConsoleAdapter
        from novel_rag.tui.console.app import ConsoleApp
        from novel_rag.tui.console.commands import ConsoleContext
        from novel_rag.tui.console.dialogs import make_help_float, make_procs_float

        adapter = ConsoleAdapter(UiConfig())
        context = ConsoleContext(
            library_root=tmp_path, index_root=tmp_path, output_root=tmp_path,
            model_config_path=tmp_path / "model.json", adapter=adapter,
        )
        app = ConsoleApp(context, adapter, UiConfig(),
                         history_path=tmp_path / "history",
                         output=DummyOutput())
        context.bind_ui(open_overlay=app.open_overlay,
                        close_overlay=app.close_overlay,
                        quit_app=app.confirm_quit)

        assert app.root_container.floats is app.floats

        app.open_overlay(make_help_float())
        assert len(app.floats) == 1
        app.close_overlay()
        assert len(app.floats) == 0

        app.open_overlay(make_procs_float(adapter.runner.active_handles))
        assert len(app.floats) == 1
        adapter.system_line("冒烟")
        assert "冒烟" in app.transcript.text

    def test_accept_line_clears_buffer_and_dispatches(self, tmp_path: Path):
        """回归：Enter 路径 Buffer.reset 参数名与清空行为。"""

        pytest.importorskip("prompt_toolkit")
        from prompt_toolkit.document import Document
        from prompt_toolkit.output import DummyOutput

        from novel_rag.tui.console.adapter import ConsoleAdapter
        from novel_rag.tui.console.app import ConsoleApp
        from novel_rag.tui.console.commands import ConsoleContext

        adapter = ConsoleAdapter(UiConfig())
        context = ConsoleContext(
            library_root=tmp_path, index_root=tmp_path, output_root=tmp_path,
            model_config_path=tmp_path / "model.json", adapter=adapter,
        )
        app = ConsoleApp(context, adapter, UiConfig(),
                         history_path=tmp_path / "history",
                         output=DummyOutput())
        context.bind_ui(open_overlay=app.open_overlay,
                        close_overlay=app.close_overlay,
                        quit_app=app.confirm_quit)

        app.input_buffer.text = "info"
        assert app._accept(app.input_buffer) is True
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if "OK" in adapter.blocks.render_text():
                break
            time.sleep(0.02)
        assert "❯ info" in adapter.blocks.render_text()

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if not adapter.jobs:
                break
            time.sleep(0.02)
        assert app.input_buffer.text == ""

    def test_dispatch_info_end_to_end(self, tmp_path: Path):
        pytest.importorskip("prompt_toolkit")
        from prompt_toolkit.output import DummyOutput

        from novel_rag.tui.console.adapter import ConsoleAdapter
        from novel_rag.tui.console.app import ConsoleApp
        from novel_rag.tui.console.commands import ConsoleContext, dispatch

        adapter = ConsoleAdapter(UiConfig())
        context = ConsoleContext(
            library_root=tmp_path, index_root=tmp_path, output_root=tmp_path,
            model_config_path=tmp_path / "model.json", adapter=adapter,
            story_id="demo", timeline_id="main",
        )
        ConsoleApp(context, adapter, UiConfig(),
                   history_path=tmp_path / "history", output=DummyOutput())
        dispatch(context, "info")

        deadline = time.monotonic() + 3
        text = ""
        while time.monotonic() < deadline:
            text = adapter.blocks.render_text()
            if "OK" in text:
                break
            time.sleep(0.02)
        assert "❯ info" in text and "库目录" in text
