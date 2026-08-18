"""Public API for state review, approval, and rejection."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from ..documents import read_yaml_mapping, registered_story_ids
from .types import StateReviewError, StateProposalReview, StatePromotionResult
from .helpers import (
    _assert_path_scope,
    _atomic_text,
    _atomic_yaml,
    _backup_path,
    _candidate_characters,
    _candidate_world,
    _canonical_character_patch,
    _canonical_world_patch,
    _check_callback,
    _default_checks,
    _find_history,
    _make_character_documents,
    _make_world_documents,
    _persist_decision,
    _reject_conflicting_history_file,
    _restore_files,
    _runtime_paths,
    _safe_id,
    _scope_values,
    _update_version_map,
    _version_map_path,
    read_yaml_mapping,
)
from ..index import rebuild_isolated_indexes
from ..service import load_valid_documents


def inspect_state_proposal(runtime_dir: Path, *, library_root: Path | None = None) -> dict[str, Any]:
    """Return a human-reviewable proposal summary without changing files."""

    runtime, contract, result, proposal = _runtime_paths(runtime_dir, require_confirmed=False)
    request = contract.get("request") or {}
    candidate_chars = _candidate_characters(proposal)
    candidate_world = _candidate_world(proposal)
    event_ids = [str(item.get("event_id")) for item in proposal.get("event_state_deltas", [])
                 if isinstance(item, Mapping) and item.get("event_id")]
    evidence: dict[str, Any] = {
        "confirmed": (result.get("extensions") or {}).get("confirmed") is True,
        "result_status": result.get("status"),
        "history_document_id": proposal.get("history_document_id", ""),
    }
    if library_root is not None and evidence["confirmed"]:
        try:
            history_path, history = _find_history(
                library_root.resolve(), str(request.get("story_id") or ""),
                str(proposal.get("history_document_id") or ""), str(request.get("timeline_id") or ""),
            )
        except StateReviewError as exc:
            evidence["history_error"] = str(exc)
        else:
            content = str(history.body.get("content") or "")
            evidence.update({
                "history_path": str(history_path),
                "history_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "history_chars": len(content),
            })
    summary = StateProposalReview(
        runtime_dir=str(runtime),
        status=str(proposal.get("status") or ""),
        writeback_id=str(proposal.get("writeback_id") or ""),
        story_id=str(request.get("story_id") or ""),
        timeline_id=str(request.get("timeline_id") or ""),
        history_document_id=str(proposal.get("history_document_id") or ""),
        character_ids=sorted(candidate_chars),
        world_fields=sorted(_canonical_world_patch(candidate_world, None)),
        event_ids=event_ids,
        evidence=evidence,
        candidate_state=copy.deepcopy(dict(proposal.get("candidate_state") or {})) if isinstance(proposal.get("candidate_state"), Mapping) else {},
        event_state_deltas=copy.deepcopy(list(proposal.get("event_state_deltas") or [])) if isinstance(proposal.get("event_state_deltas"), list) else [],
        decision=str(proposal.get("decision") or ""),
        promoted_document_ids=[str(item) for item in proposal.get("promoted_document_ids", []) if item],
    )
    return summary.to_dict()


def approve_state_proposal(
    runtime_dir: Path,
    *,
    library_root: Path,
    index_root: Path | None = None,
    field_scopes: Mapping[str, Any] | None = None,
    approved_scopes: Mapping[str, Any] | None = None,
    approved_fields: Mapping[str, Any] | None = None,
    character_ids: Iterable[str] | None = None,
    include_world: bool = True,
    validator: Callable[..., Any] | None = None,
    indexer: Callable[..., Any] | None = None,
    retrieval: Callable[..., Any] | None = None,
    note: str = "",
) -> StatePromotionResult:
    """Approve and promote a confirmed proposal.

    ``field_scopes`` is optional.  Without it, only explicitly recognised
    canonical template fields are promoted.  Unknown/transient fields are
    reported in ``skipped`` and never guessed into the RAG.
    """

    runtime, contract, result, proposal = _runtime_paths(runtime_dir, require_confirmed=True)
    field_scopes = field_scopes or approved_scopes or approved_fields
    library_root = library_root.resolve()
    if library_root.is_symlink() or not library_root.is_dir():
        raise StateReviewError("library_root 必须是目录且不能是符号链接")
    index_root = (index_root or library_root / "index").resolve()
    expected_index = (library_root / "index").resolve()
    if index_root != expected_index:
        raise StateReviewError("index_root 必须是 library_root/index")
    request = contract.get("request") or {}
    story_id = str(request.get("story_id") or "")
    timeline_id = str(request.get("timeline_id") or "main")
    if not story_id:
        raise StateReviewError("提案缺少 story_id")
    if story_id not in registered_story_ids(library_root):
        raise StateReviewError(f"未注册 story_id: {story_id}")
    history_path, history = _find_history(library_root, story_id, str(proposal.get("history_document_id") or ""), timeline_id)
    status = str(proposal.get("status") or "")
    writeback_id = str(proposal.get("writeback_id") or "")
    if status == "promoted" and proposal.get("decision") == "approve":
        return StatePromotionResult(
            status="noop", decision="approve", writeback_id=writeback_id,
            document_ids=[str(item) for item in proposal.get("promoted_document_ids", []) if item],
            skipped={str(k): str(v) for k, v in (proposal.get("skipped") or {}).items()},
            retrieval_cases=int(proposal.get("retrieval_cases") or 0),
        )
    if status == "rejected":
        raise StateReviewError("已拒绝的提案不能再次 approve")
    candidate_chars = _candidate_characters(proposal)
    selected = {str(item) for item in character_ids} if character_ids is not None else set(candidate_chars)
    skipped: dict[str, str] = {}
    docs: list[tuple[Path, dict[str, Any]]] = []
    snapshots: list[tuple[Path, dict[str, Any]]] = []
    change_logs: list[tuple[Path, dict[str, Any]]] = []
    document_ids: list[str] = []
    version_map_updates: dict[Path, dict[str, Any]] = {}
    reason = note.strip() or f"approved confirmed state proposal {writeback_id}"
    for character_id, candidate in candidate_chars.items():
        if character_id not in selected:
            skipped[character_id] = "not_selected"
            continue
        try:
            safe_character_id = _safe_id(character_id, field_name="character_id")
            allowed = _scope_values(field_scopes, safe_character_id)
            if allowed is None:
                allowed = _scope_values(field_scopes, "characters")
            patch = _canonical_character_patch(candidate, allowed)
            if not patch:
                skipped[character_id] = "no_explicit_canonical_fields"
                continue
            document, snapshot, current_path, snapshot_path, change_path, change = _make_character_documents(
                library_root, story_id, timeline_id, safe_character_id, patch, history, writeback_id, reason,
            )
            docs.append((current_path, document))
            if snapshot is not None and snapshot_path is not None:
                snapshots.append((snapshot_path, snapshot))
            change_logs.append((change_path, change))
            document_ids.append(str(document["metadata"]["document_id"]))
            version_map_updates[_version_map_path(library_root, story_id)] = _update_version_map(
                version_map_updates.get(_version_map_path(library_root, story_id), read_yaml_mapping(_version_map_path(library_root, story_id)) if _version_map_path(library_root, story_id).exists() else {}),
                f"state-current-{safe_character_id}", str(document["metadata"]["document_id"]),
                str(document["metadata"].get("supersedes") or "") or None, reason,
            )
        except StateReviewError as exc:
            skipped[character_id] = str(exc)
    world_candidate = _candidate_world(proposal) if include_world else {}
    world_allowed = _scope_values(field_scopes, "world_state")
    world_patch = _canonical_world_patch(world_candidate, world_allowed)
    if world_candidate and not world_patch:
        skipped["world_state"] = "no_explicit_canonical_fields"
    if world_patch:
        try:
            world_doc, world_snapshot, world_current, world_snapshot_path, world_change_path, world_change, world_id = _make_world_documents(
                library_root, story_id, timeline_id, world_patch, history, writeback_id, reason,
            )
        except StateReviewError as exc:
            skipped["world_state"] = str(exc)
        else:
            docs.append((world_current, world_doc))
            if world_snapshot is not None and world_snapshot_path is not None:
                snapshots.append((world_snapshot_path, world_snapshot))
            change_logs.append((world_change_path, world_change))
            document_ids.append(world_id)
            map_path = _version_map_path(library_root, story_id)
            version_map_updates[map_path] = _update_version_map(
                version_map_updates.get(map_path, read_yaml_mapping(map_path) if map_path.exists() else {}),
                "world-state-current", world_id,
                str(world_doc["metadata"].get("supersedes") or "") or None, reason,
            )
    if not docs and not snapshots and not change_logs:
        return _persist_decision(runtime / "state-writeback-proposal.json", proposal, "approve", writeback_id,
                                 document_ids=[], skipped=skipped, retrieval_cases=0, status="promoted")

    proposal_path = runtime / "state-writeback-proposal.json"
    _assert_path_scope(proposal_path, runtime, label="proposal")
    for path, value in [*snapshots, *change_logs]:
        _reject_conflicting_history_file(path, value)
    backups: dict[Path, bytes | None] = {}
    for path, _ in [*docs, *snapshots, *change_logs, *[(path, value) for path, value in version_map_updates.items()]]:
        _assert_path_scope(path, library_root, label="state promotion target")
        _backup_path(path, backups)
    _backup_path(proposal_path, backups)
    retrieval_cases = 0
    try:
        for path, value in snapshots:
            _atomic_yaml(path, value)
        for path, value in change_logs:
            _atomic_yaml(path, value)
        for path, value in docs:
            _atomic_yaml(path, value)
            from ..documents import load_document, validate_document
            errors = validate_document(load_document(path))
            if errors:
                raise StateReviewError(f"状态模板校验失败 {path.name}: {'; '.join(errors)}")
        for path, value in version_map_updates.items():
            _atomic_yaml(path, value)
        if validator is None and indexer is None and retrieval is None:
            retrieval_cases = _default_checks(library_root, index_root)
        else:
            validation_result = _check_callback(validator, library_root)
            if isinstance(validation_result, (list, tuple)) and validation_result:
                raise StateReviewError("状态晋升后 validate 失败: " + "; ".join(str(item) for item in validation_result[:8]))
            _check_callback(indexer, library_root, index_root)
            retrieval_result = _check_callback(retrieval, library_root, index_root)
            if isinstance(retrieval_result, int):
                retrieval_cases = retrieval_result
        proposal.update({
            "status": "promoted",
            "decision": "approve",
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "review_note": note,
            "promoted_document_ids": document_ids,
            "snapshot_paths": [str(path) for path, _ in snapshots],
            "change_log_paths": [str(path) for path, _ in change_logs],
            "skipped": skipped,
            "retrieval_cases": retrieval_cases,
            "evidence": {"history_path": str(history_path), "history_document_id": history.document_id},
        })
        _atomic_text(proposal_path, json.dumps(proposal, ensure_ascii=False, indent=2))
    except Exception as exc:
        _restore_files(backups)
        if validator is None and indexer is None and retrieval is None:
            try:
                documents, _ = load_valid_documents(library_root)
                rebuild_isolated_indexes(index_root, documents, registered_story_ids(library_root))
            except Exception:
                pass
        if isinstance(exc, StateReviewError):
            raise
        raise StateReviewError(f"状态晋升失败并已回滚: {exc}") from exc
    return StatePromotionResult(
        status="promoted", decision="approve", writeback_id=writeback_id,
        document_ids=document_ids,
        snapshot_paths=[str(path) for path, _ in snapshots],
        change_log_paths=[str(path) for path, _ in change_logs],
        skipped=skipped, retrieval_cases=retrieval_cases,
    )


def reject_state_proposal(runtime_dir: Path, *, reason: str = "", library_root: Path | None = None) -> StatePromotionResult:
    """Reject a proposal without changing History, current state, or indexes."""

    runtime, _contract, _result, proposal = _runtime_paths(runtime_dir, require_confirmed=False)
    writeback_id = str(proposal.get("writeback_id") or "")
    if proposal.get("status") == "promoted":
        raise StateReviewError("已晋升的提案不能 reject")
    if proposal.get("status") == "rejected" and proposal.get("decision") == "reject":
        return StatePromotionResult(status="noop", decision="reject", writeback_id=writeback_id)
    return _persist_decision(runtime / "state-writeback-proposal.json", proposal, "reject", writeback_id,
                             document_ids=[], skipped={}, retrieval_cases=0, status="rejected")


# Friendly aliases for callers that use "promote"/"review" terminology.
def review_state_proposal(
    runtime_dir: Path,
    *,
    library_root: Path | None = None,
    decision: str | None = None,
    **kwargs: Any,
) -> Any:
    if decision is None:
        return inspect_state_proposal(runtime_dir, library_root=library_root)
    normalized = decision.strip().lower()
    if normalized in {"approve", "approved", "promote", "promoted"}:
        if library_root is None:
            raise StateReviewError("approve 需要 library_root")
        return approve_state_proposal(runtime_dir, library_root=library_root, **kwargs)
    if normalized in {"reject", "rejected"}:
        return reject_state_proposal(runtime_dir, library_root=library_root, **kwargs)
    raise StateReviewError(f"未知审核决定: {decision}")


def load_state_proposal(runtime_dir: Path, *, library_root: Path | None = None) -> dict[str, Any]:
    return inspect_state_proposal(runtime_dir, library_root=library_root)


promote_state_proposal = approve_state_proposal
apply_state_proposal = approve_state_proposal