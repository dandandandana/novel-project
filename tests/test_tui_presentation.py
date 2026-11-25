# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

from novel_rag.tui.helpers import (
    Input,
    Output,
    display_width,
    pick_file_from_directory,
    render_rows,
)


def _drive(answers: list[str]) -> tuple[Input, Output, list[str]]:
    pending = iter(answers)
    transcript: list[str] = []

    def feed(_prompt: str) -> str:
        return next(pending)

    def emit(message: str) -> None:
        transcript.append(message)

    return feed, emit, transcript


def _note(row: object) -> str:
    value = row["summary"] if isinstance(row, dict) else row.summary
    return "（空）" if value is None else str(value)


def test_render_rows_aligns_mixed_scripts_and_truncates() -> None:
    rows = [
        SimpleNamespace(title="第一章 风起", author="Alice", summary="短摘要"),
        SimpleNamespace(title="Chapter Two", author="鲍勃", summary="很" * 60),
        {"title": "映射行", "author": "Carol", "summary": None},
    ]
    rendered = render_rows(
        rows,
        [("标题", "title"), ("作者", "author"), ("备注", _note)],
    )
    lines = rendered.splitlines()
    assert len(lines) == 2 + len(rows)
    assert all(name in lines[0] for name in ("标题", "作者", "备注"))
    assert set(lines[1]) == {"-", " "}

    second_column_offset = lines[1].index("  ") + 2
    assert any(line.rstrip().endswith("…") for line in lines[2:])
    for row, line in zip(rows, lines[2:]):
        author = row["author"] if isinstance(row, dict) else row.author
        assert display_width(line[:line.index(author)]) == second_column_offset

    assert render_rows([], [("标题", "title")]) == "（无记录）"


def test_pick_file_navigates_directories_and_files(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "x.txt").write_text("x", encoding="utf-8")
    (tmp_path / "a" / "y.md").write_text("y", encoding="utf-8")
    (tmp_path / "a" / "z.py").write_text("z", encoding="utf-8")

    feed, emit, transcript = _drive(["1", "3"])
    selected = pick_file_from_directory(feed, emit, start=tmp_path)
    assert selected == (tmp_path / "a" / "y.md").resolve()
    listing = "\n".join(transcript)
    assert "a/" in listing and "b/" in listing
    assert "x.txt" in listing and "y.md" in listing and "z.py" not in listing

    feed, emit, transcript = _drive(["1", "..", "nope.txt", ""])
    assert pick_file_from_directory(feed, emit, start=tmp_path) is None
    assert any("路径不存在" in message and "nope.txt" in message for message in transcript)

    feed, emit, _ = _drive([str(tmp_path / "a" / "z.py")])
    picked = pick_file_from_directory(feed, emit, start=tmp_path)
    assert picked == (tmp_path / "a" / "z.py").resolve()
