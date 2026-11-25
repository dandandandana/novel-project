from __future__ import annotations

from pathlib import Path

import pytest

from novel_rag.mutations import MISSING_FINGERPRINT, MutationConflictError, fingerprint_bytes
from novel_rag.onboarding import save_author_preferences


def _story_root(library_root: Path) -> Path:
    story_root = library_root / "stories" / "demo"
    story_root.mkdir(parents=True)
    return story_root


def test_preferences_first_write_requires_missing_fingerprint(tmp_path: Path) -> None:
    _story_root(tmp_path)

    path = save_author_preferences(
        tmp_path, "demo", "按系统默认执行。\n", expected_fingerprint=MISSING_FINGERPRINT
    )

    assert path.read_bytes() == "按系统默认执行。\n".encode("utf-8")
    assert fingerprint_bytes(path.read_bytes()).startswith("sha256:")


def test_stale_preferences_fingerprint_rejects_without_changing_source_or_backup(tmp_path: Path) -> None:
    story_root = _story_root(tmp_path)
    path = story_root / "author-preferences.txt"
    old_bytes = b"\xef\xbb\xbf\xe6\x97\xa7\xe5\x81\x8f\xe5\xa5\xbd\r\n"
    path.write_bytes(old_bytes)

    with pytest.raises(MutationConflictError):
        save_author_preferences(
            tmp_path,
            "demo",
            "不应写入。\n",
            overwrite=True,
            expected_fingerprint=fingerprint_bytes(b"stale source"),
        )

    assert path.read_bytes() == old_bytes
    assert not path.with_suffix(".txt.bak").exists()


def test_matching_fingerprint_backs_up_exact_old_bytes_before_update(tmp_path: Path) -> None:
    story_root = _story_root(tmp_path)
    path = story_root / "author-preferences.txt"
    old_bytes = b"\xef\xbb\xbf\xe6\x97\xa7\xe5\x81\x8f\xe5\xa5\xbd\r\n"
    path.write_bytes(old_bytes)

    saved = save_author_preferences(
        tmp_path,
        "demo",
        "新偏好。\n",
        overwrite=True,
        expected_fingerprint=fingerprint_bytes(old_bytes),
    )

    assert saved.read_bytes() == "新偏好。\n".encode("utf-8")
    assert saved.with_suffix(".txt.bak").read_bytes() == old_bytes


def test_legacy_onboarding_calls_keep_overwrite_behavior_without_cas(tmp_path: Path) -> None:
    _story_root(tmp_path)

    path = save_author_preferences(tmp_path, "demo", "旧 CLI 写法。\n")
    with pytest.raises(FileExistsError):
        save_author_preferences(tmp_path, "demo", "未确认覆盖。\n")

    updated = save_author_preferences(tmp_path, "demo", "显式覆盖。\n", overwrite=True)

    assert updated == path
    assert path.read_text(encoding="utf-8") == "显式覆盖。\n"
    assert path.with_suffix(".txt.bak").read_text(encoding="utf-8") == "旧 CLI 写法。\n"
