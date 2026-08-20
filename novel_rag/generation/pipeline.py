"""Main generation pipeline orchestrator."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..generation_schema import GenerationRequest, GenerationResult, ValidationIssue
from .types import GenerationError
from .helpers import (
    _payload,
    _safe_task_id,
    _prepare_runtime,
    _call,
    _draft,
    _semantic_envelope_ok,
    _reference_advice,
    _reference_audit_metadata,
    _write_json,
    _validate_identity,
    read_author_preferences,
    build_contract,
    retrieve_context_bundle,
    build_reference_profiles,
    load_scene_state,
    execute_scene,
    validate_draft,
)
from .retrieval import Retriever, bundle_to_context_items


def generate(request_input: str | Mapping[str, Any], model, *,
             library_root: Path, index_root: Path | None = None,
             output_root: Path | None = None,
             task_id: str = "generation", overwrite_runtime: bool = False,
             retriever: Retriever | None = None) -> GenerationResult:
    request = GenerationRequest.from_input(request_input)
    _validate_identity(library_root, request)
    output_base = (output_root or library_root.parent / "outputs").resolve()
    safe_task_id = _safe_task_id(task_id)
    workdir = output_base / ".workflow" / request.story_id / safe_task_id
    _prepare_runtime(workdir, overwrite_runtime=overwrite_runtime)
    preferences = read_author_preferences(library_root, request.story_id)
    contract = build_contract(request, preferences, model)
    index_root = index_root or library_root / "index"
    retrieval_request, context_bundle = retrieve_context_bundle(
        contract,
        index_root,
        library_root=library_root,
        retriever=retriever,
    )
    context = bundle_to_context_items(context_bundle, retrieval_request)
    contract.context = {"retrieved": [_payload(item) for item in context],
                        "cpm_context": [_payload(item) for item in context if item.document_type in {"canon", "history", "character_state", "world_state", "rule"}]}
    initial_state, character_profiles = load_scene_state(library_root, request.story_id, request.timeline_id)
    references = build_reference_profiles(request.references, model)
    _write_json(workdir / "contract.json", contract)
    _write_json(workdir / "context.json", contract.context)
    _write_json(workdir / "references.json", _reference_audit_metadata(references))

    text, events, state = execute_scene(contract, model, references, initial_state, character_profiles)
    if not text.strip():
        raise GenerationError("模型没有返回小说正文")
    (workdir / "draft-00.txt").write_text(text, encoding="utf-8")

    if references:
        original = text
        try:
            polished = _call(model, "polish", {
            "text": text, "events": _payload(events), "references": _reference_advice(references),
            "author_preferences": _payload(contract.preferences),
            "writing_feedback": [item for item in contract.context.get("retrieved", [])
                                 if item.get("document_type") == "feedback"],
            "semantic_lock": "不得改变事件、顺序、主体、结果、认知和状态。",
            "immutable_event_texts": [item.prose for item in events],
            "required_response": {"text": "润色正文", "preserved_event_ids": [item.event_id for item in events],
                                  "event_evidence": {item.event_id: {"excerpt": "正文中的真实连续短句",
                                                                      "actor": item.actor, "result": item.result}
                                                     for item in events}},
            })
        except Exception:
            polished = original
        candidate, _, _ = _draft(polished)
        if candidate.strip() and _semantic_envelope_ok(polished, events, references):
            text = candidate
            (workdir / "polished-00.txt").write_text(text, encoding="utf-8")

    report = validate_draft(text, contract, events, model, attempt=0, state=state)
    if references and report.status in {"repair_required", "user_guidance_required"}:
        text = original
        report = validate_draft(text, contract, events, model, attempt=0, state=state)
    _write_json(workdir / "audit-00.json", report)
    attempts = 0
    while report.needs_repair and attempts < contract.max_repairs:
        attempts += 1
        try:
            repaired = _call(model, "repair", {
            "text": text, "contract": _payload(contract), "events": _payload(events),
            "issues": [_payload(issue) for issue in report.issues], "attempt": attempts,
            "expansion_points": contract.length.expansion_points,
            "scope": "只修失败项；纯表达修复不得产生状态变化。",
            "immutable_event_texts": [item.prose for item in events],
            "required_response": {"text": "修复后正文", "preserved_event_ids": [item.event_id for item in events],
                                  "event_evidence": {item.event_id: {"excerpt": "正文中的真实连续短句",
                                                                      "actor": item.actor, "result": item.result}
                                                     for item in events}},
            })
        except Exception as exc:
            report.issues.append(ValidationIssue("repair", f"自动修复失败: {exc}", "warning"))
            break
        candidate, _, _ = _draft(repaired)
        if candidate.strip() and _semantic_envelope_ok(repaired, events, references):
            text = candidate
        (workdir / f"draft-{attempts:02d}.txt").write_text(text, encoding="utf-8")
        report = validate_draft(text, contract, events, model, attempt=attempts, state=state)
        _write_json(workdir / f"audit-{attempts:02d}.json", report)
    if report.needs_repair:
        report.status = "user_guidance_required"
    warnings = [issue.message for issue in report.issues if issue.severity == "warning"]
    result = GenerationResult(text=text, status=report.status, warnings=warnings, validation=report,
                              events=events, state=state, attempts=attempts,
                              extensions={"runtime_dir": str(workdir), "confirmed": False})
    (workdir / "final.txt").write_text(text, encoding="utf-8")
    _write_json(workdir / "result.json", result)
    return result
