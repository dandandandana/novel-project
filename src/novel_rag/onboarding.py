from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .layout import story_root
from .mutations import (
    FileMutationLock,
    MISSING_FINGERPRINT,
    MutationConflictError,
    atomic_write_bytes,
    fingerprint_bytes,
)

PREFERENCE_SECTIONS = (
    "模式", "POV", "叙述距离", "对白", "描写", "禁忌", "标题与排版", "Reference", "其他",
)


def author_preferences_path(library_root: Path, story_id: str) -> Path:
    """依赖：作品目录。输入：库根和作品 ID。输出：偏好文件路径或身份错误。实现：沿共用作品目录定位固定文件名。"""
    return story_root(library_root, story_id) / "author-preferences.txt"


def read_author_preferences_text(library_root: Path, story_id: str) -> str:
    """依赖：作品偏好路径。输入：库根和作品 ID。输出：偏好原文或空串。实现：有文件时读取 UTF-8 文本并兼容 BOM。"""
    path = author_preferences_path(library_root, story_id)
    return path.read_text(encoding="utf-8-sig") if path.is_file() else ""


def render_author_preferences(values: Mapping[str, str]) -> str:
    blocks: list[str] = []
    for section in PREFERENCE_SECTIONS:
        value = str(values.get(section) or "").strip()
        if value:
            blocks.append(f"【{section}】\n{value}")
    if not blocks:
        blocks.append("【未指定】\n按当前任务要求和系统默认执行。")
    return "\n\n".join(blocks) + "\n"


def save_author_preferences(
    library_root: Path,
    story_id: str,
    text: str,
    *,
    overwrite: bool = False,
    expected_fingerprint: str | None = None,
) -> Path:
    """依赖：author_preferences_path、FileMutationLock 与 mutations 原子写入。
    输入：库根、story_id、偏好全文、覆盖选择及可选完整字节指纹 CAS。
    输出：已保存的偏好文件路径；不匹配的 CAS 抛出 MutationConflictError。
    实现：共享库 mutation 锁内读取实际旧字节、核验指纹、备份同一字节并原子替换。
    """
    path = author_preferences_path(library_root, story_id)
    path.resolve().relative_to((Path(library_root) / "stories" / story_id).resolve())
    if not path.parent.is_dir():
        raise FileNotFoundError(f"小说目录不存在: {path.parent}")
    if not text.strip():
        raise ValueError("作者偏好不能为空；不想指定时可填写“按系统默认”")
    lock_path = Path(library_root) / ".novel-rag" / "mutation.lock"
    with FileMutationLock(lock_path):
        try:
            existing_bytes = path.read_bytes()
        except FileNotFoundError:
            existing_bytes = None
        actual_fingerprint = (
            fingerprint_bytes(existing_bytes) if existing_bytes is not None else MISSING_FINGERPRINT
        )
        if expected_fingerprint is not None and expected_fingerprint != actual_fingerprint:
            raise MutationConflictError(
                f"作者偏好已改变，拒绝覆盖: {path} "
                f"(expected={expected_fingerprint}, actual={actual_fingerprint})"
            )
        if existing_bytes is not None and existing_bytes.decode("utf-8-sig").strip() and not overwrite:
            raise FileExistsError(f"作者偏好已存在: {path}")
        if existing_bytes is not None:
            backup = path.with_suffix(path.suffix + ".bak")
            atomic_write_bytes(backup, existing_bytes)
        atomic_write_bytes(path, text.encode("utf-8"))
    return path
