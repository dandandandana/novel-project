"""Public API for state review, approval, and rejection."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from ..catalog.layout import LegacyLayoutMapper
from ..documents import RagDocument, read_yaml_mapping, read_yaml_snapshot, registered_story_ids
from ..identity import GraphKey
from ..mutations import ChangeSet, MutationCoordinator, fingerprint_file
from ..mutations.source import require_source_write_scope
from ..mutations.types import MISSING_FINGERPRINT
from .types import StateReviewError, StateProposalReview, StatePromotionResult
from .helpers import (
    _assert_path_scope,
    _atomic_text,
    _candidate_characters,
    _candidate_world,
    _canonical_character_patch,
    _canonical_world_patch,
    _check_callback,
    _find_history,
    _make_character_documents,
    _make_world_documents,
    _persist_decision,
    _reject_conflicting_history_file,
    _runtime_paths,
    _safe_id,
    _scope_values,
    _update_version_map,
    _version_map_path,
    read_yaml_mapping,
)
from ..documents import load_document, validate_document
from ..service import load_valid_documents


def _build_default_mutation_coordinator(
    *,
    library_root: Path,
    index_root: Path,
    story_id: str,
    timeline_id: str,
) -> Any:
    """Load the application write composition root only when a write occurs."""

    try:
        from ..composition import build_mutation_coordinator
    except (ImportError, AttributeError) as exc:
        raise StateReviewError(
            "默认 MutationCoordinator composition 不可用；"
            "请注入 coordinator 或配置 novel_rag.composition.build_mutation_coordinator"
        ) from exc
    try:
        coordinator = build_mutation_coordinator(
            library_root=library_root,
            index_directory=index_root,
        )
    except TypeError as first:
        try:
            coordinator = build_mutation_coordinator(
                library_root=library_root,
                index_root=index_root,
                story_id=story_id,
                timeline_id=timeline_id,
            )
        except TypeError:
            try:
                coordinator = build_mutation_coordinator(library_root, index_root, story_id, timeline_id)
            except TypeError:
                try:
                    coordinator = build_mutation_coordinator(library_root, index_directory=index_root)
                except TypeError:
                    try:
                        coordinator = build_mutation_coordinator(library_root, index_root)
                    except TypeError:
                        raise first
    if not hasattr(coordinator, "commit"):
        raise StateReviewError("build_mutation_coordinator 必须返回带 commit() 的对象")
    return coordinator


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
    coordinator: MutationCoordinator | Any | None = None,
    note: str = "",
) -> StatePromotionResult:
    """依赖：模板、源归属与 Coordinator。输入：已确认提案及批准范围。输出：晋升回执或 StateReviewError。实现：核对已有资料和待写版本归属，以同次检查的字节 CAS 提交。

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
            version_map_path = _version_map_path(library_root, story_id, timeline_id)
            version_map_updates[version_map_path] = _update_version_map(
                version_map_updates.get(version_map_path, read_yaml_mapping(version_map_path) if version_map_path.exists() else {}),
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
            map_path = _version_map_path(library_root, story_id, timeline_id)
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
    if proposal_path.is_symlink():
        raise StateReviewError("proposal 不能是符号链接")
    for path, value in [*snapshots, *change_logs]:
        _reject_conflicting_history_file(path, value)
    changes: dict[Path, Mapping[str, Any]] = {}
    for path, value in [*docs, *snapshots, *change_logs, *[(path, value) for path, value in version_map_updates.items()]]:
        _assert_path_scope(path, library_root, label="state promotion target")
        changes[path] = value

    retrieval_cases = 0

    def _legacy_validate(_staged: Any) -> None:
        """Compatibility callbacks run as pre-commit validation only."""

        _documents, corpus_issues = load_valid_documents(library_root)
        if corpus_issues:
            raise StateReviewError(
                "状态晋升前 validate 失败: "
                + "; ".join(issue.message for issue in corpus_issues[:8])
            )
        for path, value in docs:
            # Validate the exact value that will be committed without writing
            # the target early; staged-file ownership remains with the
            # MutationCoordinator.
            if not isinstance(value, Mapping) or not isinstance(value.get("metadata"), Mapping):
                raise StateReviewError(f"状态模板缺少 metadata: {path.name}")
            body = {key: child for key, child in value.items() if key != "metadata"}
            errors = validate_document(
                RagDocument(path=path, metadata=dict(value["metadata"]), body=body)
            )
            if errors:
                raise StateReviewError(f"状态模板校验失败 {path.name}: {'; '.join(errors)}")
        validation_result = _check_callback(validator, library_root)
        if isinstance(validation_result, (list, tuple)) and validation_result:
            raise StateReviewError(
                "状态晋升后 validate 失败: "
                + "; ".join(str(item) for item in validation_result[:8])
            )
        if validation_result is False:
            raise StateReviewError("状态晋升后 validate 失败")
        index_result = _check_callback(indexer, library_root, index_root)
        if isinstance(index_result, (list, tuple)) and index_result:
            raise StateReviewError(
                "状态晋升后 index/build 失败: "
                + "; ".join(str(item) for item in index_result[:8])
            )
        if index_result is False:
            raise StateReviewError("状态晋升后 index/build 失败")
        nonlocal_retrieval["value"] = _check_callback(retrieval, library_root, index_root)
        if isinstance(nonlocal_retrieval["value"], (list, tuple)) and nonlocal_retrieval["value"]:
            raise StateReviewError(
                "状态晋升后 retrieval 失败: "
                + "; ".join(str(item) for item in nonlocal_retrieval["value"][:8])
            )
        if nonlocal_retrieval["value"] is False:
            raise StateReviewError("状态晋升后 retrieval 失败")

    # Capture the source baseline before compatibility callbacks or the
    # composition root can inspect/build anything.  External edits during
    # validation must still be rejected by the coordinator.
    scope = GraphKey(story_id, timeline_id)
    mapper = LegacyLayoutMapper(library_root)
    expected_files = {}
    for path, payload in changes.items():
        if path in version_map_updates:
            expected_files[path] = fingerprint_file(path)
            continue
        try:
            require_source_write_scope(mapper.normalize_path(path, metadata=payload["metadata"]), scope)
            if path.exists():
                previous = read_yaml_snapshot(path)
                previous_doc = load_document(path, snapshot=previous)
                require_source_write_scope(mapper.normalize_path(path, metadata=previous_doc.metadata), scope)
                expected_files[path] = previous.source_hash
            else:
                expected_files[path] = MISSING_FINGERPRINT
        except ValueError as exc:
            raise StateReviewError(str(exc)) from exc
    nonlocal_retrieval: dict[str, Any] = {"value": None}
    active_coordinator = coordinator
    if active_coordinator is None:
        # Run legacy callbacks as compatibility validation hooks, then use the
        # application composition root for the real staged graph transaction.
        # No YAML-only coordinator is allowed on the default path.
        _legacy_validate(None)
        active_coordinator = _build_default_mutation_coordinator(
            library_root=library_root,
            index_root=index_root,
            story_id=story_id,
            timeline_id=timeline_id,
        )
        try:
            graph_keys = (GraphKey(story_id, timeline_id),)
        except (TypeError, ValueError) as exc:
            raise StateReviewError(f"无法构造目标 GraphKey: {exc}") from exc
    else:
        try:
            graph_keys = (GraphKey(story_id, timeline_id),)
        except (TypeError, ValueError) as exc:
            raise StateReviewError(f"无法构造目标 GraphKey: {exc}") from exc

    change_set = ChangeSet(
        changes=changes,
        affected_graph_keys=graph_keys,
        expected_file_fingerprints=expected_files,
        change_id=writeback_id,
        metadata={"operation": "state_promotion", "story_id": story_id, "timeline_id": timeline_id},
    )
    retrieval_cases = 0
    try:
        mutation = active_coordinator.commit(change_set)
        if not hasattr(mutation, "yaml_committed"):
            raise StateReviewError("MutationCoordinator.commit 未返回 MutationResult")
        mutation_status = str(getattr(mutation, "status", "promoted") or "promoted")

        def _result_items(value: Any) -> tuple[Any, ...]:
            if not value:
                return ()
            if isinstance(value, (str, bytes)):
                return (value,)
            try:
                return tuple(value)
            except TypeError:
                return (value,)

        pending_results = _result_items(getattr(mutation, "pending", ()))
        failed_results = _result_items(getattr(mutation, "failed", ()))
        if mutation_status == "failed" or not bool(mutation.yaml_committed) or failed_results:
            raise StateReviewError(
                "状态晋升失败，YAML 未提交: " + (getattr(mutation, "error", None) or "unknown mutation failure")
            )
        retrieval_result = nonlocal_retrieval["value"]
        if isinstance(retrieval_result, int) and not isinstance(retrieval_result, bool):
            retrieval_cases = retrieval_result
        if mutation_status == "pending" or pending_results:
            proposal.update({
                "status": "pending",
                "decision": "approve",
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
                "review_note": note,
                "promoted_document_ids": document_ids,
                "snapshot_paths": [str(path) for path, _ in snapshots],
                "change_log_paths": [str(path) for path, _ in change_logs],
                "skipped": skipped,
                "retrieval_cases": retrieval_cases,
                "mutation_status": mutation_status,
                "mutation_error": "; ".join(str(getattr(item, "error", "") or "") for item in pending_results),
                "evidence": {"history_path": str(history_path), "history_document_id": history.document_id},
            })
            _atomic_text(proposal_path, json.dumps(proposal, ensure_ascii=False, indent=2))
            return StatePromotionResult(
                status="pending", decision="approve", writeback_id=writeback_id,
                document_ids=document_ids,
                snapshot_paths=[str(path) for path, _ in snapshots],
                change_log_paths=[str(path) for path, _ in change_logs],
                skipped=skipped, retrieval_cases=retrieval_cases,
            )
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
        if isinstance(exc, StateReviewError):
            raise
        raise StateReviewError(f"状态晋升失败: {exc}") from exc
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
