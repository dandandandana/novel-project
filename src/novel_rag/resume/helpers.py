"""Filesystem and validation helpers for the resume/continuation step."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..generation import _payload, _safe_task_id
from .types import ResumeError


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResumeError(f"无法读取 {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ResumeError(f"{label} 必须是 JSON 对象: {path}")
    return value


def _runtime_parts(runtime_dir: Path) -> tuple[Path, str, str]:
    """Validate a runtime path and return ``(output_root, story_id, task)``."""
    if runtime_dir.is_symlink():
        raise ResumeError("运行时目录不能是符号链接")
    resolved = runtime_dir.resolve()
    parts = resolved.parts
    try:
        marker = parts.index(".workflow")
    except ValueError as exc:
        raise ResumeError("--runtime 必须指向 outputs/.workflow/<story>/<task>") from exc
    if len(parts) <= marker + 2:
        raise ResumeError("--runtime 缺少 story_id 或 task_id")
    if len(parts) != marker + 3:
        raise ResumeError("--runtime 必须正好指向 outputs/.workflow/<story>/<task>")
    if marker == 0:
        raise ResumeError("运行时目录必须位于一个 outputs 根目录下")
    story_id = parts[marker + 1]
    task_id = parts[marker + 2]
    if not story_id or not task_id or any(part in {".", ".."} for part in (story_id, task_id)):
        raise ResumeError("运行时 story_id/task_id 不安全")
    output_root = Path(*parts[:marker])
    return output_root, story_id, task_id


def _default_child_task(runtime_dir: Path, output_root: Path, story_id: str) -> str:
    parent = runtime_dir.name
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    base = _safe_task_id(f"{parent}-guidance-{stamp}")
    candidate = output_root / ".workflow" / story_id / base
    suffix = 1
    while candidate.exists():
        base = _safe_task_id(f"{parent}-guidance-{stamp}-{suffix}")
        candidate = output_root / ".workflow" / story_id / base
        suffix += 1
    return base


def _guidance_text(guidance: str) -> str:
    value = str(guidance or "").strip()
    if not value:
        raise ResumeError("作者指导不能为空；请说明要继续、补写或修正的位置")
    # Keep the natural-language interface permissive while avoiding an
    # accidental multi-megabyte prompt from a pasted file.
    if len(value) > 50_000:
        raise ResumeError("作者指导过长（最多 50000 字符），请拆成几次继续")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(_payload(dict(value)), ensure_ascii=False, indent=2, default=str), encoding="utf-8")