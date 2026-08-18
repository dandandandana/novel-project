from __future__ import annotations

import shutil
from pathlib import Path
from typing import Mapping


PREFERENCE_SECTIONS = (
    "模式", "POV", "叙述距离", "对白", "描写", "禁忌", "标题与排版", "Reference", "其他",
)


def author_preferences_path(library_root: Path, story_id: str) -> Path:
    return library_root / "stories" / story_id / "author-preferences.txt"


def render_author_preferences(values: Mapping[str, str]) -> str:
    blocks: list[str] = []
    for section in PREFERENCE_SECTIONS:
        value = str(values.get(section) or "").strip()
        if value:
            blocks.append(f"【{section}】\n{value}")
    if not blocks:
        blocks.append("【未指定】\n按当前任务要求和系统默认执行。")
    return "\n\n".join(blocks) + "\n"


def save_author_preferences(library_root: Path, story_id: str, text: str, *, overwrite: bool = False) -> Path:
    path = author_preferences_path(library_root, story_id)
    if not path.parent.is_dir():
        raise FileNotFoundError(f"小说目录不存在: {path.parent}")
    if not text.strip():
        raise ValueError("作者偏好不能为空；不想指定时可填写“按系统默认”")
    if path.exists() and path.read_text(encoding="utf-8-sig").strip() and not overwrite:
        raise FileExistsError(f"作者偏好已存在: {path}")
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
    return path
