"""Safe continuation of a generation that asks the author for guidance.

The generation runtime is an immutable proposal until ``confirm`` migrates it
to canon.  A continuation therefore creates a child runtime instead of
editing the parent in place.  The child reuses :func:`novel_rag.generation.generate`
so all normal normalization, CPM/state chaining, validation and repair limits
remain in one pipeline.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..generation import GenerationResult, Model, generate
from .helpers import _default_child_task, _guidance_text, _read_object, _runtime_parts, _write_json
from .types import ResumeError


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
    child_task_id = task_id or _default_child_task(runtime_dir, target_output, story_id)
    if not child_task_id:
        raise ResumeError("无法生成安全的 child task_id")
    if child_task_id == parent_task_id and target_output == output_from_path:
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