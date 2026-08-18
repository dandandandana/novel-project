"""Safe continuation of a generation that asks the author for guidance.

The generation runtime is an immutable proposal until ``confirm`` migrates it
to canon.  A continuation therefore creates a child runtime instead of
editing the parent in place.  The child reuses :func:`novel_rag.generation.generate`
so all normal normalization, CPM/state chaining, validation and repair limits
remain in one pipeline.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .generation import GenerationError, GenerationResult, Model, _payload, _safe_task_id, generate


class ResumeError(GenerationError):
    """Raised when a runtime cannot safely be continued."""


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


def continue_generation(
    runtime_dir: Path,
    guidance: str,
    model: Model,
    *,
    library_root: Path,
    index_root: Path | None = None,
    output_root: Path | None = None,
    task_id: str | None = None,
) -> GenerationResult:
    """Create a child generation runtime using author guidance.

    Only ``user_guidance_required`` runtimes may be resumed.  The parent is
    read but never modified, and the generated child stores ``parent_runtime``
    and ``supersedes_runtime`` metadata for audit/review tooling.
    """
    runtime_dir = Path(runtime_dir).resolve()
    output_from_path, path_story_id, parent_task_id = _runtime_parts(runtime_dir)
    if not runtime_dir.exists() or not runtime_dir.is_dir():
        raise ResumeError(f"运行时目录不存在: {runtime_dir}")
    contract = _read_object(runtime_dir / "contract.json", "contract.json")
    result = _read_object(runtime_dir / "result.json", "result.json")
    status = str(result.get("status") or "")
    if status != "user_guidance_required":
        raise ResumeError(f"只有 user_guidance_required 运行时可以继续，当前状态是 {status or 'unknown'}")
    extensions = result.get("extensions") or {}
    if isinstance(extensions, Mapping) and extensions.get("confirmed") is True:
        raise ResumeError("已确认的运行时不可继续；请从新的未确认任务开始")
    request = contract.get("request")
    if not isinstance(request, Mapping):
        raise ResumeError("contract.request 缺失或格式不正确")
    story_id = str(request.get("story_id") or "")
    if not story_id or story_id != path_story_id:
        raise ResumeError("运行时目录中的 story_id 与 contract.request 不一致")
    timeline_id = str(request.get("timeline_id") or "main")
    value = _guidance_text(guidance)

    target_output = Path(output_root).resolve() if output_root is not None else output_from_path
    child_task_id = _safe_task_id(task_id) if task_id else _default_child_task(runtime_dir, target_output, story_id)
    if not child_task_id:
        raise ResumeError("无法生成安全的 child task_id")
    if child_task_id == _safe_task_id(parent_task_id) and target_output == output_from_path:
        raise ResumeError("续作必须使用新的 task_id，不能覆盖父任务")

    # Preserve the author's original request and add a bounded, explicit
    # continuation note.  The immutable outline stays in ``outline``; the
    # model receives the guidance through the regular current_request field.
    child_request = deepcopy(dict(request))
    original_request = str(child_request.get("current_request") or child_request.get("request") or "").strip()
    validation = result.get("validation")
    issues: list[str] = []
    if isinstance(validation, Mapping):
        raw_issues = validation.get("issues")
        if isinstance(raw_issues, list):
            issues = [str(item.get("message") or item) for item in raw_issues[:12]
                      if isinstance(item, Mapping) or item]
    context_lines = [line for line in [
        original_request,
        "这是对上一次未确认草稿的继续生成。保留作者大纲中的硬事件、顺序、主体和结果。",
        f"上一次校验状态：{status}",
        *(f"上一次校验提示：{item}" for item in issues),
        f"作者续作指导：{value}",
    ] if line]
    child_request["current_request"] = "\n".join(context_lines)
    child_request.pop("request", None)
    request_extensions = dict(child_request.get("extensions") or {})
    request_extensions.update({
        "parent_runtime": str(runtime_dir),
        "supersedes_runtime": str(runtime_dir),
        "parent_task_id": parent_task_id,
        "guidance": value,
        "resume_timeline_id": timeline_id,
    })
    child_request["extensions"] = request_extensions

    # ``generate`` performs the conflict check before calling the model.  A
    # fresh child id is therefore safe even if a client retries this call.
    child = generate(
        child_request,
        model,
        library_root=Path(library_root),
        index_root=Path(index_root) if index_root is not None else None,
        output_root=target_output,
        task_id=child_task_id,
    )
    child_dir = Path(str(child.extensions.get("runtime_dir") or "")).resolve()
    if not child_dir.exists() or child_dir.parent.name != story_id:
        raise ResumeError("续作生成了无法确认归属的 child runtime")
    metadata = {
        "status": "created",
        "parent_runtime": str(runtime_dir),
        "supersedes_runtime": str(runtime_dir),
        "parent_task_id": parent_task_id,
        "child_runtime": str(child_dir),
        "child_task_id": child_task_id,
        "story_id": story_id,
        "timeline_id": timeline_id,
        "guidance": value,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "parent_status": status,
    }
    _write_json(child_dir / "resume.json", metadata)
    child.extensions.update({
        "parent_runtime": str(runtime_dir),
        "supersedes_runtime": str(runtime_dir),
        "resume_file": str(child_dir / "resume.json"),
    })
    # ``generate`` has already completed its atomic result write.  Updating
    # only the additive audit metadata is safe and keeps the public result in
    # sync with resume.json for callers that do not inspect the filesystem.
    _write_json(child_dir / "result.json", {
        "text": child.text,
        "status": child.status,
        "warnings": child.warnings,
        "validation": child.validation,
        "events": child.events,
        "state": child.state,
        "attempts": child.attempts,
        "extensions": child.extensions,
    })
    return child


def resume_generation(
    runtime_dir: Path,
    guidance: str,
    model: Model,
    *,
    library_root: Path,
    index_root: Path | None = None,
    output_root: Path | None = None,
    task_id: str | None = None,
) -> GenerationResult:
    """Compatibility alias with an explicit verb for API clients."""
    return continue_generation(runtime_dir, guidance, model, library_root=library_root,
                               index_root=index_root, output_root=output_root, task_id=task_id)


__all__ = ["ResumeError", "continue_generation", "resume_generation"]
