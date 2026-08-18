from pathlib import Path

import pytest

from novel_rag.onboarding import render_author_preferences, save_author_preferences


def test_preferences_are_free_text_sections_and_overwrite_is_backed_up(tmp_path: Path) -> None:
    story = tmp_path / "stories" / "demo"
    story.mkdir(parents=True)
    first = render_author_preferences({"POV": "第三人称有限", "禁忌": "不要 RP"})
    path = save_author_preferences(tmp_path, "demo", first)
    assert "【POV】\n第三人称有限" in path.read_text(encoding="utf-8")

    with pytest.raises(FileExistsError):
        save_author_preferences(tmp_path, "demo", "新偏好")

    save_author_preferences(tmp_path, "demo", "【POV】\n第一人称\n", overwrite=True)
    assert path.with_suffix(".txt.bak").read_text(encoding="utf-8") == first


def test_empty_preference_answers_use_explicit_default() -> None:
    assert "【未指定】" in render_author_preferences({})
