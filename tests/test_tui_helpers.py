# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pytest

from novel_rag.mutations import SummaryDocument
from novel_rag.tui.helpers import (
    confirm_word,
    display_width,
    list_summary_documents,
    suggest_task_id,
    truncate_display,
)


def test_confirm_word_is_case_insensitive_and_defaults_to_cancel() -> None:
    answers = iter(["yes", "NO", "", "  yEs  "])
    prompts: list[str] = []

    def feed(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)

    assert confirm_word(feed, lambda _m: None, "确认迁移", "YES") is True
    assert confirm_word(feed, lambda _m: None, "确认迁移", "YES") is False
    assert confirm_word(feed, lambda _m: None, "确认迁移", "YES") is False
    assert confirm_word(feed, lambda _m: None, "确认迁移", "YES") is True
    assert any("输入 YES 确认" in item for item in prompts)


def test_suggest_task_id_prefers_date_then_sequence(tmp_path: Path) -> None:
    assert suggest_task_id(tmp_path, "demo") == suggest_task_id(tmp_path, "demo")

    root = tmp_path / ".workflow" / "demo"
    root.mkdir(parents=True)
    first = suggest_task_id(tmp_path, "demo")
    (root / first).mkdir()
    second = suggest_task_id(tmp_path, "demo")
    assert second != first and second.startswith(first)
    (root / second).mkdir()
    third = suggest_task_id(tmp_path, "demo")
    assert third.startswith(f"{first}-")


def test_list_summary_documents_skips_unparsable_files(tmp_path: Path) -> None:
    good = SummaryDocument(
        path=tmp_path / "s1.yaml",
        document_id="chapter-summary-s1-v0.1",
        content="内容",
        metadata={"story_id": "demo", "timeline_id": "main"},
        ownership="auto",
        source_fingerprint=None,
        revision=1,
        stale=False,
    )
    good.path.write_text(
        "metadata:\n"
        "  story_id: demo\n"
        "  timeline_id: main\n"
        "  document_type: chapter-summary\n"
        "  document_id: chapter-summary-s1-v0.1\n"
        "  ownership: auto\n"
        "  revision: 1\n"
        "  stale: false\n"
        "content: 内容\n",
        encoding="utf-8",
    )
    (tmp_path / "broken.yaml").write_text(":::: 不是 YAML ::::", encoding="utf-8")
    (tmp_path / "note.txt").write_text("忽略", encoding="utf-8")

    rows = list_summary_documents(tmp_path)
    assert [row.document_id for row in rows] == [good.document_id]


def test_display_width_counts_wide_chars() -> None:
    assert display_width("中文abc") == 7
    assert display_width("") == 0


def test_truncate_display_respects_terminal_width() -> None:
    text = "中文abc"
    cut = truncate_display(text, 5)
    assert display_width(cut) <= 5 and cut.endswith("…")
    assert truncate_display(text, 100) == text
    assert truncate_display(text, 0) == ""
    assert truncate_display("ab", 1) == "…"
