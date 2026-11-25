# -*- coding: utf-8 -*-
from __future__ import annotations

import builtins

import pytest

from novel_rag.tui import session as tui_session
from novel_rag.tui.helpers import Input
from novel_rag.tui.session import _CompleterRouter, create_interactive_io


def test_plain_mode_returns_builtin_pair() -> None:
    input_fn, output_fn = create_interactive_io(mode="plain")
    assert input_fn is builtins.input
    assert output_fn is print


def test_auto_mode_degrades_without_tty(monkeypatch) -> None:
    monkeypatch.setattr(tui_session, "_stdin_is_interactive", lambda: False)
    input_fn, output_fn = create_interactive_io(mode="auto")
    assert input_fn is builtins.input
    assert output_fn is print


def test_prompt_toolkit_mode_uses_session(tmp_path) -> None:
    pytest.importorskip("prompt_toolkit")
    history = tmp_path / "history"
    captured: dict = {}

    class _FakeSession:
        def __init__(self, history_path) -> None:
            self.history_path = history_path

        def prompt(self, text, completer=None):
            captured["text"] = text
            captured["completer"] = completer
            return "demo"

    input_fn, _ = create_interactive_io(
        mode="prompt_toolkit",
        history_path=history / "tui-history",
        candidates_provider=lambda: ["alpha"],
        session_factory=lambda target: _FakeSession(target),
    )
    assert input_fn is not builtins.input
    assert (history / "tui-history").parent.is_dir()
    assert input_fn("选择: ") == "demo"
    assert captured["completer"] is not None


def test_router_routes_path_and_word_prompts() -> None:
    pytest.importorskip("prompt_toolkit")
    router = _CompleterRouter(candidates_provider=lambda: ["alpha", "beta"])

    path_completer = router.completer_for("大纲文本或 UTF-8 文件路径: ")
    from prompt_toolkit.completion import PathCompleter, WordCompleter

    assert isinstance(path_completer, PathCompleter)
    word_completer = router.completer_for("选择: ")
    assert isinstance(word_completer, WordCompleter)
    plain_router = _CompleterRouter(candidates_provider=None)
    assert plain_router.completer_for("任意提问: ") is None


def test_router_without_candidates_has_no_word_completer() -> None:
    pytest.importorskip("prompt_toolkit")
    router = _CompleterRouter(candidates_provider=None)
    assert router.completer_for("选择: ") is None


def test_input_annotation_still_importable() -> None:
    assert Input is not None
