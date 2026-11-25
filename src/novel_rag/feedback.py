from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .documents import RagDocument
from .std.time import utc_now_iso
from .importers import (
    RagImportError,
    _ids,
    _import_text,
    _safe_name,
    _validate_identity,
    _validate_roots,
)
from .service import load_valid_documents


class FeedbackError(RagImportError):
    pass


@dataclass(frozen=True)
class FeedbackResult:
    status: str
    path: Path
    document_id: str
    document_family: str = ""
    version: str = ""
    supersedes: tuple[str, ...] = ()
    resolved_at: str | None = None


@dataclass(frozen=True)
class FeedbackRecord:
    status: str
    path: Path
    document_id: str
    story_id: str
    timeline_id: str
    target_type: str
    target_id: str
    version: str
    resolved_at: str | None = None


_TARGET_TYPES = {
    "runtime", "history", "character_state", "world_state", "outline", "canon",
    "rule", "judgment_spec", "generator_spec", "audit_spec", "style_audit", "scene",
}
_TARGET_DOCUMENT_TYPES = {
    "history": "history",
    "character_state": "character_state",
    "world_state": "world_state",
    "outline": "outline",
    "canon": "canon",
    "rule": "rule",
    "judgment_spec": "judgment_spec",
    "generator_spec": "generator_spec",
    "audit_spec": "audit_spec",
    "style_audit": "style_audit",
}


def _feedback_fingerprint(story_id: str, timeline_id: str, target_type: str, target_id: str) -> str:
    return hashlib.sha1(
        f"{story_id}|{timeline_id}|{target_type}|{target_id}".encode("utf-8")
    ).hexdigest()[:10]


def _default_family(story_id: str, timeline_id: str, target_type: str, target_id: str) -> str:
    return f"feedback-{story_id}-{_feedback_fingerprint(story_id, timeline_id, target_type, target_id)}"


def _load_story_documents(library_root: Path, story_id: str, timeline_id: str) -> list[RagDocument]:
    library, _ = _validate_roots(library_root, library_root / "index")
    _validate_identity(library, story_id, timeline_id)
    documents, issues = load_valid_documents(library, story_id=story_id, include_shared=False)
    if issues:
        raise FeedbackError(f"知识库校验失败: {issues[0].message}")
    return documents


def _validate_runtime(runtime_dir: str | Path, story_id: str) -> str:
    path = Path(runtime_dir).resolve()
    if ".workflow" not in path.parts:
        raise FeedbackError("runtime_dir 必须位于 .workflow 运行时目录")
    marker = path.parts.index(".workflow")
    if len(path.parts) <= marker + 2 or path.parts[marker + 1] != story_id:
        raise FeedbackError("runtime_dir 的 story_id 与反馈不一致")
    return str(path)


def _validate_bindings(
    documents: list[RagDocument],
    *,
    story_id: str,
    timeline_id: str,
    target_type: str,
    target_id: str,
    runtime_dir: str | Path | None,
    history_id: str | None,
    state_versions: Mapping[str, Any] | Sequence[str] | None,
) -> tuple[str, str | None, dict[str, Any] | list[str]]:
    target_type = str(target_type or "").strip()
    target_id = str(target_id or "").strip()
    if target_type not in _TARGET_TYPES:
        raise FeedbackError(f"不支持的反馈 target_type: {target_type}")
    if not target_id:
        raise FeedbackError("反馈必须绑定 target_id")
    by_id = {item.document_id: item for item in documents}
    if target_type != "runtime":
        target = by_id.get(target_id)
        if target is None:
            raise FeedbackError(f"反馈目标文档不存在: {target_id}")
        if target.metadata.get("story_id") != story_id or target.metadata.get("timeline_id") != timeline_id:
            raise FeedbackError("反馈目标跨越 story/timeline 隔离边界")
        if target_type == "history" and target.metadata.get("document_type") != "history":
            raise FeedbackError("target_type=history 必须绑定 history 文档")
        if target_type == "character_state" and target.metadata.get("document_type") != "character_state":
            raise FeedbackError("target_type=character_state 必须绑定 character_state 文档")
        if target_type == "world_state" and target.metadata.get("document_type") != "world_state":
            raise FeedbackError("target_type=world_state 必须绑定 world_state 文档")
    expected_document_type = _TARGET_DOCUMENT_TYPES.get(target_type)
    if expected_document_type and target.metadata.get("document_type") != expected_document_type:
        raise FeedbackError(f"target_type={target_type} must bind {expected_document_type} document")
    runtime_ref = _validate_runtime(runtime_dir, story_id) if runtime_dir else ""
    history_ref = str(history_id or "").strip() or None
    if history_ref:
        history = by_id.get(history_ref)
        if history is None or history.metadata.get("document_type") != "history":
            raise FeedbackError(f"history_id 未找到有效 history: {history_ref}")
        if history.metadata.get("story_id") != story_id or history.metadata.get("timeline_id") != timeline_id:
            raise FeedbackError("history_id 跨越 story/timeline 隔离边界")
    if isinstance(state_versions, Mapping):
        normalized_states: dict[str, Any] | list[str] = {str(key): str(value) for key, value in state_versions.items()}
        references = list(normalized_states.values())
    else:
        references = _ids(state_versions)
        normalized_states = references
    for state_id in references:
        state = by_id.get(state_id)
        if state is None or state.metadata.get("document_type") not in {"character_state", "world_state"}:
            raise FeedbackError(f"state_versions 未找到角色/世界状态版本: {state_id}")
        if state.metadata.get("story_id") != story_id or state.metadata.get("timeline_id") != timeline_id:
            raise FeedbackError("state_versions 跨越 story/timeline 隔离边界")
    return runtime_ref, history_ref, normalized_states


def _feedback_payload(
    *,
    issue: str,
    user_comment: str,
    affected_scope: str,
    correction_rule: Sequence[str] | None,
    examples: Sequence[str] | None,
    runtime_id: str,
    history_id: str | None,
    state_versions: Mapping[str, Any] | Sequence[str] | None,
    resolution: str = "",
    resolved_at: str | None = None,
) -> dict[str, Any]:
    return {
        "issue": str(issue or "").strip(),
        "user_comment": str(user_comment or "").strip(),
        "affected_scope": str(affected_scope or "").strip(),
        "correction_rule": [str(item) for item in (correction_rule or [])],
        "examples": [str(item) for item in (examples or [])],
        "runtime_id": runtime_id,
        "history_id": history_id,
        "state_versions": state_versions if state_versions is not None else {},
        "resolution": str(resolution or "").strip(),
        "resolved_at": resolved_at,
    }


def _feedback_document(
    *,
    story_id: str,
    timeline_id: str,
    target_type: str,
    target_id: str,
    version: str,
    family: str,
    payload: dict[str, Any],
    supersedes: Sequence[str] | None,
) -> str:
    fingerprint = _feedback_fingerprint(story_id, timeline_id, target_type, target_id)
    document_id = f"feedback-{story_id}-{fingerprint}-v{version}"
    metadata = {
        "document_id": document_id,
        "document_family": family,
        "story_id": story_id,
        "timeline_id": timeline_id,
        "document_type": "feedback",
        "title": f"反馈：{target_type}/{target_id}",
        "target_type": target_type,
        "target_id": target_id,
        "version": version,
        "status": "active",
        "supersedes": (list(supersedes) if supersedes else None),
    }
    return yaml.safe_dump({"metadata": metadata, "feedback": payload}, allow_unicode=True, sort_keys=False, width=120)


def _result(value: Any, *, resolved_at: str | None = None) -> FeedbackResult:
    return FeedbackResult(
        status=value.status,
        path=value.path,
        document_id=value.document_id,
        document_family=value.document_family,
        version=value.version,
        supersedes=value.supersedes,
        resolved_at=resolved_at,
    )


def create_feedback(
    *,
    library_root: Path,
    index_root: Path,
    story_id: str,
    timeline_id: str,
    target_type: str,
    target_id: str,
    issue: str,
    user_comment: str = "",
    affected_scope: str = "",
    correction_rule: Sequence[str] | None = None,
    examples: Sequence[str] | None = None,
    runtime_id: str = "",
    runtime_dir: str | Path | None = None,
    history_id: str | None = None,
    state_versions: Mapping[str, Any] | Sequence[str] | None = None,
    version: str = "1.0",
    supersedes: str | Sequence[str] | None = None,
    document_family: str | None = None,
    coordinator: Any | None = None,
) -> FeedbackResult:
    documents = _load_story_documents(library_root, story_id, timeline_id)
    runtime_ref, history_ref, normalized_states = _validate_bindings(
        documents, story_id=story_id, timeline_id=timeline_id, target_type=target_type,
        target_id=target_id, runtime_dir=runtime_dir, history_id=history_id,
        state_versions=state_versions,
    )
    if not str(issue or "").strip():
        raise FeedbackError("反馈 issue 不能为空")
    family = document_family or _default_family(story_id, timeline_id, target_type, target_id)
    family = _safe_name(family)
    previous = _ids(supersedes)
    payload = _feedback_payload(
        issue=issue, user_comment=user_comment, affected_scope=affected_scope,
        correction_rule=correction_rule, examples=examples,
        runtime_id=runtime_id or runtime_ref, history_id=history_ref,
        state_versions=normalized_states,
    )
    text = _feedback_document(story_id=story_id, timeline_id=timeline_id, target_type=target_type,
                              target_id=target_id, version=version, family=family,
                              payload=payload, supersedes=previous)
    result = _import_text(text, source_path=Path("<feedback>"), library_root=library_root,
                          index_root=index_root, story_id=story_id, timeline_id=timeline_id,
                          expected_type="feedback", version=version,
                          supersedes=previous, document_family=family,
                          coordinator=coordinator)
    return _result(result)


def list_feedback(
    *,
    library_root: Path,
    story_id: str,
    timeline_id: str,
    index_root: Path | None = None,
    status: str = "all",
    target_type: str | None = None,
    target_id: str | None = None,
) -> list[FeedbackRecord]:
    _validate_roots(library_root, index_root or Path(library_root) / "index")
    documents = _load_story_documents(library_root, story_id, timeline_id)
    output: list[FeedbackRecord] = []
    for document in documents:
        metadata = document.metadata
        if metadata.get("document_type") != "feedback":
            continue
        body = document.body.get("feedback", {}) if isinstance(document.body, dict) else {}
        if not isinstance(body, Mapping):
            continue
        resolved_at = str(body.get("resolved_at") or "") or None
        metadata_status = str(metadata.get("status") or "")
        visible_status = "resolved" if resolved_at else metadata_status
        # `active` means unresolved current feedback.  A resolved revision is
        # still stored with metadata.status=active so that the canonical
        # version registry can point at it; callers must not see it as open.
        if status == "active" and (metadata_status != "active" or resolved_at):
            continue
        if status == "resolved" and not resolved_at:
            continue
        if status not in {"all", "active", "resolved"} and status != metadata_status:
            continue
        if target_type and str(metadata.get("target_type") or "") != target_type:
            continue
        if target_id and str(metadata.get("target_id") or "") != target_id:
            continue
        output.append(FeedbackRecord(
            status=visible_status, path=document.path, document_id=document.document_id,
            story_id=str(metadata.get("story_id") or ""), timeline_id=str(metadata.get("timeline_id") or ""),
            target_type=str(metadata.get("target_type") or ""), target_id=str(metadata.get("target_id") or ""),
            version=str(metadata.get("version") or ""), resolved_at=resolved_at,
        ))
    return sorted(output, key=lambda item: (item.target_type, item.target_id, item.version, item.document_id))


def resolve_feedback(
    *,
    library_root: Path,
    index_root: Path,
    story_id: str,
    timeline_id: str,
    feedback_id: str,
    resolution: str,
    version: str,
    supersedes: str | Sequence[str] | None = None,
    coordinator: Any | None = None,
) -> FeedbackResult:
    documents = _load_story_documents(library_root, story_id, timeline_id)
    source = next((item for item in documents if item.document_id == feedback_id), None)
    if source is None or source.metadata.get("document_type") != "feedback":
        raise FeedbackError(f"反馈文档不存在: {feedback_id}")
    body = source.body.get("feedback", {}) if isinstance(source.body, Mapping) else {}
    if not isinstance(body, Mapping):
        raise FeedbackError("反馈文档 body.feedback 格式错误")
    metadata = source.metadata
    target_type = str(metadata.get("target_type") or "")
    target_id = str(metadata.get("target_id") or "")
    state_versions = body.get("state_versions")
    runtime_binding = str(body.get("runtime_id") or "")
    # Runtime IDs are often opaque execution identifiers (for example
    # ``run-2026-08-14``).  Only a supplied filesystem path is subject to the
    # .workflow/story boundary check; retain the opaque ID in the payload.
    runtime_path = runtime_binding if ".workflow" in Path(runtime_binding).parts else None
    _validate_bindings(documents, story_id=story_id, timeline_id=timeline_id,
                       target_type=target_type, target_id=target_id,
                       runtime_dir=runtime_path,
                       history_id=body.get("history_id") or None,
                       state_versions=state_versions)
    previous = _ids(supersedes)
    if previous != [feedback_id]:
        raise FeedbackError("resolve 必须显式 supersedes 被解决的反馈版本")
    family = str(metadata.get("document_family") or "").strip()
    if not family:
        family = _default_family(story_id, timeline_id, target_type, target_id)
    resolution_text = str(resolution or "").strip()
    if not resolution_text:
        raise FeedbackError("resolution 不能为空")
    candidate_id = f"feedback-{story_id}-{_feedback_fingerprint(story_id, timeline_id, target_type, target_id)}-v{version}"
    existing_candidate = next((item for item in documents if item.document_id == candidate_id), None)
    if existing_candidate is not None:
        existing_body = existing_candidate.body.get("feedback", {}) if isinstance(existing_candidate.body, Mapping) else {}
        existing_resolved = str(existing_body.get("resolved_at") or "") if isinstance(existing_body, Mapping) else ""
        if (
            existing_resolved
            and str(existing_body.get("resolution") or "").strip() == resolution_text
            and _ids(existing_candidate.metadata.get("supersedes")) == previous
        ):
            return FeedbackResult(
                status="noop", path=existing_candidate.path, document_id=existing_candidate.document_id,
                document_family=str(existing_candidate.metadata.get("document_family") or family),
                version=str(existing_candidate.metadata.get("version") or version),
                supersedes=tuple(previous), resolved_at=existing_resolved,
            )
    resolved_at = utc_now_iso()
    payload = dict(body)
    payload["resolution"] = resolution_text
    payload["resolved_at"] = resolved_at
    text = _feedback_document(story_id=story_id, timeline_id=timeline_id, target_type=target_type,
                              target_id=target_id, version=version, family=family,
                              payload=payload, supersedes=previous)
    result = _import_text(text, source_path=source.path, library_root=library_root,
                          index_root=index_root, story_id=story_id, timeline_id=timeline_id,
                          expected_type="feedback", version=version,
                          supersedes=previous, document_family=family,
                          coordinator=coordinator)
    return FeedbackResult(
        status="resolved" if result.status == "imported" else result.status,
        path=result.path,
        document_id=result.document_id,
        document_family=result.document_family,
        version=result.version,
        supersedes=result.supersedes,
        resolved_at=resolved_at,
    )
