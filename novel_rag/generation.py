from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Mapping

from .documents import read_yaml_mapping, registered_story_ids
from .generation_schema import (
    AuthorEvent,
    AuthorPreferenceProfile,
    DynamicCharacterState,
    EventResult,
    GenerationContract,
    GenerationRequest,
    GenerationResult,
    LengthPolicy,
    OutlineContract,
    ReferenceProfile,
    SceneState,
    ValidationIssue,
    ValidationReport,
)
from .index import SearchResult, search_isolated
from .layout import story_root
from .service import load_valid_documents


Model = Callable[[str, dict[str, Any]], str | Mapping[str, Any]]


STAGE_INSTRUCTIONS = {
    "normalize": "宽松理解作者大纲。保留硬事件、顺序、主体、结果、自由空间和歧义；每个结果用 source_clause_ids 对应原文条目，不改善、替换或否决作者剧情。",
    "reference_profile": "只提取可迁移的底层写作能力和禁止照搬项；不得提出剧情或角色行为。",
    "decide_behavior": "只依据作者事件、人物与当前状态决定角色怎样执行。不得接触 Reference 或文风，不得否决作者事件。",
    "derive_result": "根据已经确定的行为产生现实结果、观察者信息和状态增量。不得润色正文或改变作者事件。",
    "render_prose": "把已经确定的 Behavior、Result 和 State 写成小说正文。可以使用作者偏好与抽象 Reference，但不得改变语义。",
    "polish": "依据 Reference 改善表达，但不得改变事件、顺序、主体、结果、认知、状态或结尾。",
    "validate": "检查作者硬事件、顺序、主体、结果、连续性、自然停点、可续状态及表达边界。格式小问题只警告。",
    "repair": "只修复给定问题，保持作者合同和已成立语义不变。不得新增重大事件或删除硬事件。",
}


class GenerationError(RuntimeError):
    pass


class PreferenceRequired(GenerationError):
    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"请先填写本书作者偏好文件（也可以只写“默认”）: {path}")


def author_preferences_path(library_root: Path, story_id: str) -> Path:
    return story_root(library_root, story_id) / "author-preferences.txt"


def read_author_preferences(library_root: Path, story_id: str) -> AuthorPreferenceProfile:
    path = author_preferences_path(library_root, story_id)
    if not path.exists() or not path.read_text(encoding="utf-8-sig").strip():
        raise PreferenceRequired(path)
    text = path.read_text(encoding="utf-8-sig")
    sections: dict[str, str] = {}
    current = ""
    aliases = {"模式": "模式", "POV": "POV", "视角": "POV", "叙述距离": "叙述距离",
               "对白": "对白", "描写": "描写", "禁忌": "禁忌", "标题与排版": "标题与排版",
               "标题排版": "标题与排版", "Reference": "Reference", "参考文": "Reference", "其他": "其他"}
    for line in text.splitlines():
        match = re.fullmatch(r"\s*[【\[](.+?)[】\]]\s*", line)
        if match:
            current = aliases.get(match.group(1).strip(), match.group(1).strip())
            sections.setdefault(current, "")
        elif current:
            sections[current] = (sections[current] + "\n" + line).strip()
    sections["raw_text"] = text
    known = set(aliases.values())
    profile = AuthorPreferenceProfile.from_input(sections, source_path=str(path))
    profile.extensions.update({key: value for key, value in sections.items() if key not in known | {"raw_text"}})
    return profile


def _validate_identity(library_root: Path, request: GenerationRequest) -> None:
    if request.story_id not in registered_story_ids(library_root):
        raise GenerationError(f"未注册 story_id: {request.story_id}")
    rows = read_yaml_mapping(
        story_root(library_root, request.story_id) / "registry" / "timelines.yaml"
    ).get("timelines", [])
    if not any(isinstance(row, dict) and row.get("story_id") == request.story_id
               and row.get("timeline_id") == request.timeline_id for row in rows):
        raise GenerationError(f"未注册 timeline_id: {request.story_id}/{request.timeline_id}")


def _payload(value: Any) -> Any:
    try:
        return asdict(value)
    except TypeError:
        if isinstance(value, list):
            return [_payload(item) for item in value]
        if isinstance(value, dict):
            return {key: _payload(item) for key, item in value.items()}
        return value


def _items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def _unwrap(value: str | Mapping[str, Any]) -> str | Mapping[str, Any]:
    if isinstance(value, str):
        stripped = value.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, re.S | re.I)
        if fenced:
            stripped = fenced.group(1).strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = json.loads(stripped)
                return _unwrap(parsed) if isinstance(parsed, Mapping) else stripped
            except json.JSONDecodeError:
                pass
        return stripped
    current: Mapping[str, Any] = value
    for key in ("data", "result", "response"):
        nested = current.get(key)
        if isinstance(nested, Mapping) and not any(name in current for name in ("text", "prose", "draft", "issues")):
            return _unwrap(nested)
    return current


def _call(model: Model, stage: str, payload: dict[str, Any]) -> str | Mapping[str, Any]:
    if model is None:
        raise GenerationError("未提供可调用的语言模型")
    return _unwrap(model(stage, {"phase": stage, "protocol_version": 1,
                                 "instruction": STAGE_INSTRUCTIONS[stage], **payload}))


def build_contract(request: GenerationRequest, preferences: AuthorPreferenceProfile, model: Model) -> GenerationContract:
    source_outline = OutlineContract.from_input(request.outline)
    normalized = _call(model, "normalize", {
        "outline": request.outline,
        "source_clauses": [{"clause_id": event.event_id, "raw_text": event.event, "position": event.order}
                           for event in source_outline.required_events],
        "current_request": request.current_request,
        "author_preferences": _payload(preferences),
    })
    if isinstance(normalized, Mapping):
        outline_input = normalized.get("outline", normalized)
        length_input = request.length if request.length is not None else normalized.get("length")
        extensions = {key: value for key, value in normalized.items() if key not in {"outline", "length"}}
    else:
        outline_input, length_input, extensions = normalized or request.outline, request.length, {}
    outline = OutlineContract.from_input(outline_input)
    if not outline.has_writing_goal:
        outline = source_outline
    # Natural-language clauses remain the authoritative events. The normalizer
    # may enrich a clause only when it explicitly maps back to that clause ID.
    if source_outline.required_events and isinstance(request.outline, str):
        mapped: dict[str, AuthorEvent] = {}
        for candidate in outline.required_events:
            clause_ids = _items(candidate.extensions.get("source_clause_ids",
                                                          candidate.extensions.get("source_clause_id")))
            for clause_id in clause_ids:
                mapped[str(clause_id)] = candidate
        for source in source_outline.required_events:
            candidate = mapped.get(source.event_id)
            if candidate:
                source.actor = candidate.actor
                source.target = candidate.target
                source.required_result = candidate.required_result
                source.extensions = {**candidate.extensions, **source.extensions}
        outline.required_events = source_outline.required_events
        outline.required_order = [event.event_id for event in source_outline.required_events]
    # Structured author events are immutable. A normalizer may enrich them, never delete them.
    elif source_outline.required_events and isinstance(request.outline, Mapping):
        by_id = {event.event_id: event for event in outline.required_events}
        by_text = {event.event: event for event in outline.required_events}
        merged = []
        for source in source_outline.required_events:
            candidate = by_id.get(source.event_id) or by_text.get(source.event)
            if candidate:
                source.actor = source.actor or candidate.actor
                source.target = source.target or candidate.target
                source.required_result = source.required_result or candidate.required_result
                source.extensions = {**candidate.extensions, **source.extensions}
            merged.append(source)
        known = {event.event_id for event in merged}
        known_text = {event.event for event in merged}
        merged.extend(event for event in outline.required_events
                      if event.event_id not in known and event.event not in known_text)
        outline.required_events = merged
    # Explicit author constraints always win over normalized suggestions.
    for name in ("opening_state", "required_result", "ending_state"):
        source_value = getattr(source_outline, name)
        if source_value:
            setattr(outline, name, source_value)
    for name in ("required_order", "must_not", "forbidden_reveals", "allowed_inventions"):
        source_values = getattr(source_outline, name)
        if source_values:
            setattr(outline, name, list(source_values))
    extensions["author_source_outline"] = _payload(source_outline)
    length = LengthPolicy.from_input(length_input)
    if length.mode == "author" and all(value is None for value in (length.target, length.minimum, length.maximum)):
        length.mode = "auto"
    contract = GenerationContract(
        request=request,
        outline=outline,
        length=length,
        preferences=preferences,
        extensions=extensions,
    )
    errors = contract.semantic_errors()
    if errors:
        raise GenerationError("；".join(errors))
    return contract


def retrieve_context(contract: GenerationContract, index_root: Path, *, limit: int = 12) -> list[SearchResult]:
    queries = [event.event for event in contract.outline.required_events if event.event]
    if contract.outline.required_result:
        queries.append(contract.outline.required_result)
    if not queries and contract.outline.raw_input:
        queries.append(contract.outline.raw_input)
    results: dict[str, SearchResult] = {}
    try:
        for query in queries[:4]:
            compact = " ".join(query.split())[:120]
            candidates = [compact]
            candidates.extend(token for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]{2,}", compact)
                              if token not in candidates)
            for candidate in candidates[:4]:
                for item in search_isolated(index_root, candidate, contract.request.story_id,
                                            contract.request.timeline_id,
                                            document_types=["canon", "history", "character_state", "world_state", "rule", "feedback"],
                                            limit=min(6, limit), include_shared=True):
                    results[item.document_id] = item
    except FileNotFoundError as exc:
        raise GenerationError(f"{exc}；请先执行 novel-rag index") from exc
    return sorted(results.values(), key=lambda item: item.score, reverse=True)[:limit]


def build_reference_profiles(references: list[Any], model: Model) -> list[ReferenceProfile]:
    def one(pair: tuple[int, Any]) -> ReferenceProfile:
        index, reference = pair
        try:
            result = _call(model, "reference_profile", {"reference_id": f"reference-{index + 1}", "reference": reference})
        except Exception as exc:
            return ReferenceProfile(reference_id=f"reference-{index + 1}", raw_text=str(reference),
                                    extensions={"warning": f"Reference 分析失败: {exc}"})
        if isinstance(result, Mapping):
            return ReferenceProfile(
                reference_id=str(result.get("reference_id") or f"reference-{index + 1}"),
                source_ref=str(result.get("source_ref") or "uploaded"),
                capabilities=[str(item) for item in _items(result.get("capabilities"))],
                apply_scope=[str(item) for item in _items(result.get("apply_scope"))],
                forbidden_surface_copy=[str(item) for item in _items(result.get("forbidden_surface_copy"))],
                raw_text=str(reference),
                extensions={key: value for key, value in result.items() if key not in {
                    "reference_id", "source_ref", "capabilities", "apply_scope", "forbidden_surface_copy"}},
            )
        return ReferenceProfile(reference_id=f"reference-{index + 1}", raw_text=str(reference),
                                extensions={"advice": str(result)})
    if not references:
        return []
    with ThreadPoolExecutor(max_workers=min(4, len(references))) as executor:
        return list(executor.map(one, enumerate(references)))


def _events(value: Any) -> list[EventResult]:
    output: list[EventResult] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, Mapping):
            continue
        output.append(EventResult(
            event_id=str(item.get("event_id") or ""), behavior=item.get("behavior", ""),
            result=item.get("result", ""), actor=str(item.get("actor") or ""),
            targets=[str(v) for v in _items(item.get("targets"))], observers=[str(v) for v in _items(item.get("observers"))],
            state_deltas=dict(item.get("state_deltas") or {}), prose=str(item.get("prose") or ""),
        ))
    return output


def _draft(result: str | Mapping[str, Any]) -> tuple[str, list[EventResult], dict[str, Any]]:
    if isinstance(result, str):
        match = re.search(r"BEGIN_PROSE\s*(.*?)\s*END_PROSE", result, re.S)
        return (match.group(1).strip() if match else result.strip()), [], {}
    text = str(result.get("text") or result.get("prose") or result.get("draft") or "")
    return text, _events(result.get("events")), dict(result.get("state") or {})


def _semantic_envelope_ok(value: str | Mapping[str, Any], events: list[EventResult],
                          references: list[ReferenceProfile] | None = None) -> bool:
    if not isinstance(value, Mapping):
        return False
    claimed = value.get("preserved_event_ids")
    evidence = value.get("event_evidence")
    if not isinstance(claimed, list) or [str(item) for item in claimed] != [item.event_id for item in events]:
        return False
    if not isinstance(evidence, Mapping):
        return False
    text, _, _ = _draft(value)
    # The prose emitted for each committed event is the runtime's semantic
    # anchor.  A later style pass may add or reshape surrounding text, but it
    # may not replace, negate, or reorder those anchors.  Model-supplied IDs
    # and evidence are useful diagnostics, not proof of semantic preservation.
    cursor = 0
    additions: list[str] = []
    for item in events:
        anchor = item.prose.strip()
        if not anchor:
            return False
        position = text.find(anchor, cursor)
        if position < 0:
            return False
        additions.append(text[cursor:position])
        cursor = position + len(anchor)
    additions.append(text[cursor:])
    added_text = "\n".join(additions)
    reversal = re.compile(
        r"(?:从未|根本没(?:有)?|并未|没有).{0,16}(?:发生|做|交|拿|给|成为|实现)"
        r"|(?:只是|不过是|仅仅是).{0,10}(?:传闻|谣言|梦|假象|误会)"
        r"|\b(?:did\s+not|never\s+happened|only\s+a\s+rumou?r)\b",
        re.I | re.S,
    )
    if reversal.search(added_text):
        return False
    for profile in references or []:
        forbidden = [str(item).strip() for item in profile.forbidden_surface_copy]
        raw_fragments = [part.strip() for part in re.split(r"[。！？!?\n]+", profile.raw_text) if len(part.strip()) >= 8]
        if any(fragment and fragment in added_text for fragment in forbidden + raw_fragments):
            return False
    for item in events:
        row = evidence.get(item.event_id)
        if not isinstance(row, Mapping):
            return False
        excerpt = str(row.get("excerpt") or "").strip()
        if not excerpt or excerpt not in text:
            return False
        if item.actor and (str(row.get("actor") or "") != item.actor or item.actor not in excerpt):
            return False
        required_result = str(item.result or "").strip()
        if required_result and (str(row.get("result") or "") != required_result or required_result not in excerpt):
            return False
    return True


def _deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, Mapping):
        merged = deepcopy(base)
        for key, value in patch.items():
            merged[key] = _deep_merge(merged.get(key), value)
        return merged
    return deepcopy(patch)


def load_scene_state(library_root: Path, story_id: str, timeline_id: str) -> tuple[SceneState, dict[str, Any]]:
    documents, issues = load_valid_documents(library_root, story_id=story_id, include_shared=False)
    if issues:
        raise GenerationError("当前小说资料校验失败: " + "；".join(issue.message for issue in issues[:3]))
    state = SceneState()
    profiles: dict[str, Any] = {}
    for document in documents:
        metadata = document.metadata
        if metadata.get("timeline_id") != timeline_id or metadata.get("status") != "active":
            continue
        document_type = metadata.get("document_type")
        if document_type == "character_state" and metadata.get("snapshot_type") == "current":
            character_id = str(metadata.get("character_id") or "")
            body = document.body.get("character_state", {}) if isinstance(document.body, dict) else {}
            if not character_id or not isinstance(body, dict):
                continue
            mental = body.get("mental", {}) or {}
            dynamic = DynamicCharacterState(
                character_id=character_id,
                intent={"goals": body.get("goals", {})}, relationships={"items": body.get("relationships", [])},
                emotion=mental, knowledge=body.get("knowledge", {}),
                constraints={"position": body.get("current_position", {}), "physical": body.get("physical", {}),
                             "abilities": body.get("abilities", {}), "inventory": body.get("inventory", {})},
            )
            state.characters[character_id] = dynamic
            profiles[character_id] = {"long_term": (body.get("goals", {}) or {}).get("long_term", []),
                                      "knowledge_base": body.get("knowledge", {}),
                                      "constraints_base": {"abilities": body.get("abilities", {})},
                                      "voice": body.get("narrative", {})}
        elif document_type == "world_state" and isinstance(document.body, dict):
            state.shared_context.setdefault("world_state", []).append(document.body)
    return state, profiles


def _reference_advice(profiles: list[ReferenceProfile]) -> list[dict[str, Any]]:
    return [{"reference_id": item.reference_id, "capabilities": item.capabilities,
             "apply_scope": item.apply_scope, "forbidden_surface_copy": item.forbidden_surface_copy,
             "extensions": {key: value for key, value in item.extensions.items() if key != "raw_text"}}
            for item in profiles]


def _reference_audit_metadata(profiles: list[ReferenceProfile]) -> list[dict[str, Any]]:
    """Persist provenance and capabilities without storing uploaded surface text."""
    return [{"reference_id": item.reference_id, "source_ref": item.source_ref,
             "capabilities": item.capabilities, "apply_scope": item.apply_scope,
             "surface_rules_count": len(item.forbidden_surface_copy),
             "raw_text_sha256": hashlib.sha256(item.raw_text.encode("utf-8")).hexdigest() if item.raw_text else ""}
            for item in profiles]


def execute_scene(contract: GenerationContract, model: Model, references: list[ReferenceProfile],
                  initial_state: SceneState, character_profiles: dict[str, Any]) -> tuple[str, list[EventResult], SceneState]:
    state = deepcopy(initial_state)
    state.shared_context["retrieved_facts"] = contract.context.get("cpm_context", [])
    prose_parts: list[str] = []
    events: list[EventResult] = []
    order_index = {event_id: index for index, event_id in enumerate(contract.outline.required_order)}
    ordered = sorted(contract.outline.required_events,
                     key=lambda item: (order_index.get(item.event_id, len(order_index) + item.order), item.order))
    for event_index, event in enumerate(ordered):
        behavior = _call(model, "decide_behavior", {
            "author_event": _payload(event), "scene_state": _payload(state),
            "character_profiles": character_profiles,
            "invariant": "此阶段没有 Reference；作者事件必须执行。",
        })
        result_value = _call(model, "derive_result", {
            "author_event": _payload(event), "behavior": behavior, "scene_state": _payload(state),
        })
        result_map = dict(result_value) if isinstance(result_value, Mapping) else {"result": str(result_value)}
        deltas = dict(result_map.get("state_deltas") or {})
        for character_id, patch in deltas.items():
            if not isinstance(patch, Mapping):
                continue
            previous = state.characters.get(character_id, DynamicCharacterState(character_id=character_id))
            merged = _payload(previous)
            merged = _deep_merge(merged, patch)
            merged["character_id"] = character_id
            allowed = {key: merged[key] for key in ("character_id", "intent", "relationships", "emotion", "knowledge", "constraints", "extensions") if key in merged}
            state.characters[character_id] = DynamicCharacterState(**allowed)
        state.version += 1
        item = EventResult(
            event_id=event.event_id, behavior=behavior, result=result_map.get("result", event.required_result),
            actor=event.actor, targets=[event.target] if event.target else [],
            observers=[str(value) for value in result_map.get("observers", [])], state_deltas=deltas,
        )
        rendered = _call(model, "render_prose", {
            "author_event": _payload(event), "behavior": behavior, "result": _payload(item),
            "scene_state": _payload(state), "author_preferences": _payload(contract.preferences),
            "length_policy": _payload(contract.length),
            "event_progress": {"index": event_index + 1, "total": len(ordered)},
            "references": _reference_advice(references),
            "writing_feedback": [item for item in contract.context.get("retrieved", [])
                                 if item.get("document_type") == "feedback"],
            "semantic_lock": "只能渲染已成立内容。",
        })
        prose, _, _ = _draft(rendered)
        if not prose.strip():
            raise GenerationError(f"事件 {event.event_id} 没有生成正文")
        item.prose = prose
        events.append(item)
        prose_parts.append(prose.strip())
    return "\n\n".join(prose_parts), events, state


def _char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def validate_draft(text: str, contract: GenerationContract, events: list[EventResult], model: Model,
                   *, attempt: int, state: SceneState | None = None) -> ValidationReport:
    issues: list[ValidationIssue] = []
    count = _char_count(text)
    length = contract.length
    if length.mode == "author" and length.minimum is not None and count < length.minimum:
        severity = "repairable" if length.expansion_points else "warning"
        issues.append(ValidationIssue("length", f"正文长度 {count}，低于作者下限 {length.minimum}", severity))
    if length.mode == "author" and length.target is not None and count < int(length.target * 0.9):
        severity = "repairable" if length.expansion_points else "warning"
        issues.append(ValidationIssue("length", f"正文长度 {count}，低于作者目标 {length.target}", severity))
    upper = length.maximum
    if length.mode == "author" and upper is not None and count > upper:
        issues.append(ValidationIssue("length", f"正文长度 {count}，超过作者上限 {upper}", "warning"))
    expected = contract.outline.required_events
    actual_by_id = {item.event_id: item for item in events}
    for event in expected:
        actual = actual_by_id.get(event.event_id)
        if actual is None:
            issues.append(ValidationIssue("hard_event", f"缺少作者事件: {event.event}", "blocked", event.event_id))
            continue
        if event.actor and actual.actor != event.actor:
            issues.append(ValidationIssue("actor", f"事件 {event.event_id} 主体错误", "blocked"))
        if event.required_result and _textual(actual.result) != _textual(event.required_result):
            issues.append(ValidationIssue("result", f"事件 {event.event_id} 结果偏离作者要求", "blocked"))
    actual_ids = [item.event_id for item in events]
    expected_ids = list(contract.outline.required_order) or [item.event_id for item in expected]
    if [item for item in actual_ids if item in expected_ids] != expected_ids:
        issues.append(ValidationIssue("order", "作者硬事件顺序错误", "blocked"))
    try:
        result = _call(model, "validate", {
        "contract": _payload(contract), "text": text, "events": _payload(events), "attempt": attempt,
        "length_count": count, "candidate_state": _payload(state),
        })
    except Exception as exc:
        result = {"issues": [{"check": "validator", "message": f"语义校验不可用: {exc}", "severity": "warning"}]}
    if isinstance(result, Mapping):
        for item in result.get("issues", []):
            if isinstance(item, Mapping):
                severity = str(item.get("severity") or "warning")
                issues.append(ValidationIssue(str(item.get("check") or "semantic"),
                                              str(item.get("message") or ""), severity, item.get("evidence")))
        requested = str(result.get("status") or "")
    else:
        requested = ""
        if str(result).strip():
            issues.append(ValidationIssue("validator", str(result), "warning"))
    if any(issue.severity in {"blocked", "critical"} for issue in issues):
        status = "user_guidance_required"
    elif any(issue.severity in {"repairable", "major"} for issue in issues):
        status = "repair_required"
    elif issues:
        status = "pass_with_warnings"
    else:
        status = "pass"
    if requested in {"repair_required", "user_guidance_required"} and status == "pass":
        status = requested
    return ValidationReport(status=status, issues=issues, attempt=attempt)


def _textual(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_payload(value), ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _safe_task_id(value: str) -> str:
    # ``\w`` is Unicode-aware: Chinese author labels remain distinct while
    # path separators, drive markers and shell punctuation are normalised.
    cleaned = re.sub(r"[^\w.-]+", "-", str(value), flags=re.UNICODE).strip("-.")
    return cleaned or "generation"


def _runtime_is_confirmed(workdir: Path) -> bool:
    """Return whether a runtime has already been migrated to canon.

    ``confirm_runtime`` deliberately leaves a tiny marker after cleaning the
    prose files.  Looking at both result.json and confirmation.json keeps the
    guard useful for runtimes written by older versions of the module.
    """
    result_path = workdir / "result.json"
    if result_path.exists():
        try:
            value = json.loads(result_path.read_text(encoding="utf-8"))
            if isinstance(value, Mapping) and (value.get("extensions") or {}).get("confirmed") is True:
                return True
        except (OSError, UnicodeError, json.JSONDecodeError):
            # A malformed runtime is still non-empty and will be rejected by
            # the normal conflict guard; it must never be replaced silently.
            pass
    return (workdir / "confirmation.json").exists()


def _prepare_runtime(workdir: Path, *, overwrite_runtime: bool = False) -> None:
    """Protect an existing task directory before any model calls are made.

    Generation is intentionally append-only.  A caller that explicitly asks
    to reuse an unconfirmed task gets a recoverable archive next to the task;
    confirmed tasks are immutable regardless of that flag.  In normal use a
    fresh task id is the clearer and safer choice.
    """
    if workdir.is_symlink():
        raise GenerationError(f"运行时目录不能是符号链接: {workdir}")
    if not workdir.exists():
        workdir.mkdir(parents=True, exist_ok=True)
        return
    if not workdir.is_dir():
        raise GenerationError(f"运行时路径不是目录: {workdir}")
    try:
        non_empty = any(workdir.iterdir())
    except OSError as exc:
        raise GenerationError(f"无法检查运行时目录 {workdir}: {exc}") from exc
    if not non_empty:
        return
    if _runtime_is_confirmed(workdir):
        raise GenerationError("该任务已经确认并回写，不能覆盖；请使用新的 task_id")
    if not overwrite_runtime:
        raise GenerationError(
            f"任务运行时已存在且未完成: {workdir}；请使用新的 task_id，或显式传入 overwrite_runtime=True"
        )
    # Preserve the previous attempt instead of deleting it.  This is useful
    # when an interactive client deliberately retries with the same label.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    archive = workdir.with_name(f"{workdir.name}.superseded-{stamp}")
    suffix = 0
    while archive.exists():
        suffix += 1
        archive = workdir.with_name(f"{workdir.name}.superseded-{stamp}-{suffix}")
    try:
        shutil.move(str(workdir), str(archive))
        workdir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise GenerationError(f"无法归档旧运行时 {workdir}: {exc}") from exc


def generate(request_input: str | Mapping[str, Any], model: Model, *, library_root: Path,
             index_root: Path | None = None, output_root: Path | None = None,
             task_id: str = "generation", overwrite_runtime: bool = False) -> GenerationResult:
    request = GenerationRequest.from_input(request_input)
    _validate_identity(library_root, request)
    # Resolve and validate the destination before reading preferences or
    # calling the model, so a conflict never spends tokens or leaves a
    # partially-created task directory behind.
    output_base = (output_root or library_root.parent / "outputs").resolve()
    safe_task_id = _safe_task_id(task_id)
    workdir = output_base / ".workflow" / request.story_id / safe_task_id
    _prepare_runtime(workdir, overwrite_runtime=overwrite_runtime)
    preferences = read_author_preferences(library_root, request.story_id)
    contract = build_contract(request, preferences, model)
    index_root = index_root or library_root / "index"
    context = retrieve_context(contract, index_root)
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
