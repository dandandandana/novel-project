from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha1
import re
from typing import Any, Mapping


SemanticInput = str | Mapping[str, Any]


def _mapping(value: SemanticInput | None) -> tuple[dict[str, Any], str]:
    if value is None:
        return {}, ""
    if isinstance(value, str):
        return {}, value.strip()
    return dict(value), str(value.get("raw_input") or value.get("raw_text") or "").strip()


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _outline_clauses(raw: str) -> list[str]:
    lines = [re.sub(r"^\s*(?:[-*+] |\d+[.)、]\s*)", "", line).strip()
             for line in raw.splitlines() if line.strip()]
    return lines or ([raw] if raw else [])


def _extra(data: Mapping[str, Any], known: set[str]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key not in known}


@dataclass(slots=True)
class GenerationRequest:
    story_id: str
    timeline_id: str = "main"
    outline: SemanticInput = ""
    current_request: str = ""
    references: list[SemanticInput] = field(default_factory=list)
    identity: dict[str, Any] = field(default_factory=dict)
    length: SemanticInput | None = None
    extensions: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_input(cls, value: SemanticInput) -> "GenerationRequest":
        data, raw = _mapping(value)
        known = {"story_id", "story", "timeline_id", "timeline", "outline", "大纲",
                 "current_request", "request", "references", "reference", "identity", "length", "字数", "raw_input"}
        outline = data.get("outline", data.get("大纲", raw))
        return cls(
            story_id=_text(data.get("story_id", data.get("story"))),
            timeline_id=_text(data.get("timeline_id", data.get("timeline", "main"))) or "main",
            outline=outline,
            current_request=_text(data.get("current_request", data.get("request"))),
            references=_list(data.get("references", data.get("reference"))),
            identity=dict(data.get("identity") or {}),
            length=data.get("length", data.get("字数")),
            extensions=_extra(data, known),
        )


@dataclass(slots=True)
class AuthorEvent:
    event_id: str
    event: str
    actor: str = ""
    target: str = ""
    required_result: str = ""
    order: int = 0
    extensions: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_input(cls, value: SemanticInput, order: int = 0) -> "AuthorEvent":
        data, raw = _mapping(value)
        text = _text(data.get("event", data.get("content", data.get("剧情节点", raw))))
        event_id = _text(data.get("event_id", data.get("id")))
        if not event_id:
            event_id = f"event-{order + 1:03d}-{sha1(text.encode('utf-8')).hexdigest()[:8]}"
        known = {"event_id", "id", "event", "content", "剧情节点", "actor", "subject",
                 "target", "required_result", "result", "order", "raw_input"}
        try:
            parsed_order = int(data.get("order", order) or order)
        except (TypeError, ValueError):
            parsed_order = order
        return cls(
            event_id=event_id,
            event=text,
            actor=_text(data.get("actor", data.get("subject"))),
            target=_text(data.get("target")),
            required_result=_text(data.get("required_result", data.get("result"))),
            order=parsed_order,
            extensions=_extra(data, known),
        )


@dataclass(slots=True)
class OutlineContract:
    raw_input: str = ""
    opening_state: str = ""
    required_events: list[AuthorEvent] = field(default_factory=list)
    required_order: list[str] = field(default_factory=list)
    required_result: str = ""
    ending_state: str = ""
    must_not: list[str] = field(default_factory=list)
    forbidden_reveals: list[str] = field(default_factory=list)
    allowed_inventions: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    blocking_unknowns: list[str] = field(default_factory=list)
    extensions: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_input(cls, value: SemanticInput) -> "OutlineContract":
        data, raw = _mapping(value)
        event_values = data.get("required_events", data.get("must_happen", data.get("必须发生")))
        if event_values is None and raw:
            event_values = _outline_clauses(raw)
        events = [AuthorEvent.from_input(item, index) for index, item in enumerate(_list(event_values))]
        if raw:
            for event in events:
                event.extensions.setdefault("source_clause_id", event.event_id)
        known = {"raw_input", "raw_text", "opening_state", "required_events", "must_happen",
                 "必须发生", "required_order", "required_result", "ending_state", "must_not",
                 "forbidden_reveals", "allowed_inventions", "ambiguities", "blocking_unknowns"}
        return cls(
            raw_input=raw or _text(data.get("raw_input", data.get("raw_text"))),
            opening_state=_text(data.get("opening_state")),
            required_events=events,
            required_order=[_text(item) for item in _list(data.get("required_order"))],
            required_result=_text(data.get("required_result")),
            ending_state=_text(data.get("ending_state")),
            must_not=[_text(item) for item in _list(data.get("must_not"))],
            forbidden_reveals=[_text(item) for item in _list(data.get("forbidden_reveals"))],
            allowed_inventions=[_text(item) for item in _list(data.get("allowed_inventions"))],
            ambiguities=[_text(item) for item in _list(data.get("ambiguities"))],
            blocking_unknowns=[_text(item) for item in _list(data.get("blocking_unknowns"))],
            extensions=_extra(data, known),
        )

    @property
    def has_writing_goal(self) -> bool:
        return bool(self.required_events or self.required_result or self.ending_state or self.raw_input)


@dataclass(slots=True)
class LengthPolicy:
    mode: str = "auto"
    unit: str = "non_whitespace_chars"
    target: int | None = None
    minimum: int | None = None
    maximum: int | None = None
    expansion_points: list[str] = field(default_factory=list)
    overlong: str = "warn"
    extensions: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_input(cls, value: SemanticInput | None) -> "LengthPolicy":
        data, raw = _mapping(value)
        known = {"mode", "unit", "target", "min", "minimum", "max", "maximum",
                 "expansion_points", "author_expansion_points", "overlong", "raw_input"}
        mode = _text(data.get("mode")) or ("author" if any(data.get(k) is not None for k in ("target", "min", "minimum", "max", "maximum")) else "auto")
        def number(*keys: str) -> int | None:
            for key in keys:
                if data.get(key) is not None:
                    try:
                        return int(data[key])
                    except (TypeError, ValueError):
                        return None
            return None
        result = cls(
            mode=mode if mode in {"auto", "author"} else "auto",
            unit=_text(data.get("unit")) or "non_whitespace_chars",
            target=number("target"), minimum=number("minimum", "min"), maximum=number("maximum", "max"),
            expansion_points=[_text(item) for item in _list(data.get("expansion_points", data.get("author_expansion_points")))],
            overlong=_text(data.get("overlong")) or "warn",
            extensions=_extra(data, known),
        )
        if raw:
            result.extensions["raw_text"] = raw
        return result


@dataclass(slots=True)
class AuthorPreferenceProfile:
    raw_text: str = ""
    mode: str = "novel_generation"
    pov: str = ""
    narrative_distance: str = ""
    dialogue: str = ""
    description: str = ""
    taboos: str = ""
    title_layout: str = ""
    reference_policy: str = ""
    other: str = ""
    source_path: str = ""
    read_status: str = "ok"
    extensions: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_input(cls, value: SemanticInput | None, *, source_path: str = "") -> "AuthorPreferenceProfile":
        data, raw = _mapping(value)
        aliases = {
            "mode": ("mode", "模式"), "pov": ("pov", "POV", "视角"),
            "narrative_distance": ("narrative_distance", "叙述距离"),
            "dialogue": ("dialogue", "对白"), "description": ("description", "描写"),
            "taboos": ("taboos", "禁忌"), "title_layout": ("title_layout", "标题与排版", "标题排版"),
            "reference_policy": ("reference_policy", "Reference", "参考文"), "other": ("other", "其他"),
        }
        def pick(name: str) -> str:
            return next((_text(data[key]) for key in aliases[name] if data.get(key) is not None), "")
        known = {key for values in aliases.values() for key in values} | {"raw_input", "raw_text", "source_path", "read_status"}
        return cls(raw_text=raw or _text(data.get("raw_text")), mode=pick("mode") or "novel_generation",
                   pov=pick("pov"), narrative_distance=pick("narrative_distance"), dialogue=pick("dialogue"),
                   description=pick("description"), taboos=pick("taboos"), title_layout=pick("title_layout"),
                   reference_policy=pick("reference_policy"), other=pick("other"),
                   source_path=source_path or _text(data.get("source_path")),
                   read_status=_text(data.get("read_status")) or "ok", extensions=_extra(data, known))


@dataclass(slots=True)
class CharacterProfile:
    character_id: str
    long_term: Any = ""
    habits: Any = ""
    knowledge_base: Any = ""
    constraints_base: Any = ""
    relationships: Any = field(default_factory=dict)
    voice: Any = ""
    extensions: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_input(cls, value: SemanticInput) -> "CharacterProfile":
        data, raw = _mapping(value)
        known = {"character_id", "id", "long_term", "L", "habits", "H", "knowledge_base", "K_base",
                 "constraints_base", "C_base", "relationships", "voice", "raw_input"}
        return cls(character_id=_text(data.get("character_id", data.get("id"))),
                   long_term=data.get("long_term", data.get("L", "")), habits=data.get("habits", data.get("H", "")),
                   knowledge_base=data.get("knowledge_base", data.get("K_base", "")),
                   constraints_base=data.get("constraints_base", data.get("C_base", "")),
                   relationships=data.get("relationships", {}), voice=data.get("voice", ""),
                   extensions={**_extra(data, known), **({"raw_text": raw} if raw else {})})


@dataclass(slots=True)
class DynamicCharacterState:
    character_id: str
    intent: Any = ""
    relationships: dict[str, Any] = field(default_factory=dict)
    emotion: Any = ""
    knowledge: Any = field(default_factory=dict)
    constraints: Any = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_input(cls, value: SemanticInput) -> "DynamicCharacterState":
        data, raw = _mapping(value)
        known = {"character_id", "id", "intent", "I", "relationships", "R", "emotion", "E",
                 "knowledge", "K", "constraints", "C", "extensions", "raw_input"}
        return cls(character_id=_text(data.get("character_id", data.get("id"))),
                   intent=data.get("intent", data.get("I", "")),
                   relationships=dict(data.get("relationships", data.get("R", {})) or {}),
                   emotion=data.get("emotion", data.get("E", "")), knowledge=data.get("knowledge", data.get("K", {})),
                   constraints=data.get("constraints", data.get("C", {})),
                   extensions={**dict(data.get("extensions") or {}), **_extra(data, known), **({"raw_text": raw} if raw else {})})


@dataclass(slots=True)
class SceneState:
    version: int = 0
    characters: dict[str, DynamicCharacterState] = field(default_factory=dict)
    shared_context: dict[str, Any] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    extensions: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_input(cls, value: SemanticInput | None) -> "SceneState":
        data, raw = _mapping(value)
        characters = {}
        source = data.get("characters", {})
        if isinstance(source, Mapping):
            for character_id, item in source.items():
                mapped = dict(item) if isinstance(item, Mapping) else {"constraints": item}
                mapped.setdefault("character_id", character_id)
                characters[str(character_id)] = DynamicCharacterState.from_input(mapped)
        known = {"version", "characters", "shared_context", "unresolved", "extensions", "raw_input"}
        return cls(version=int(data.get("version", 0) or 0), characters=characters,
                   shared_context=dict(data.get("shared_context") or {}),
                   unresolved=[_text(item) for item in _list(data.get("unresolved"))],
                   extensions={**dict(data.get("extensions") or {}), **_extra(data, known), **({"raw_text": raw} if raw else {})})


@dataclass(slots=True)
class EventResult:
    event_id: str
    behavior: Any = ""
    result: Any = ""
    actor: str = ""
    targets: list[str] = field(default_factory=list)
    observers: list[str] = field(default_factory=list)
    state_deltas: dict[str, Any] = field(default_factory=dict)
    prose: str = ""
    extensions: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_input(cls, value: SemanticInput) -> "EventResult":
        data, raw = _mapping(value)
        known = {"event_id", "id", "behavior", "result", "actor", "targets", "observers", "state_deltas", "prose", "text", "raw_input"}
        return cls(event_id=_text(data.get("event_id", data.get("id"))), behavior=data.get("behavior", ""),
                   result=data.get("result", ""), actor=_text(data.get("actor")),
                   targets=[_text(item) for item in _list(data.get("targets"))],
                   observers=[_text(item) for item in _list(data.get("observers"))],
                   state_deltas=dict(data.get("state_deltas") or {}), prose=_text(data.get("prose", data.get("text", raw))),
                   extensions=_extra(data, known))


@dataclass(slots=True)
class ReferenceProfile:
    reference_id: str
    source_ref: str = ""
    capabilities: list[str] = field(default_factory=list)
    apply_scope: list[str] = field(default_factory=list)
    forbidden_surface_copy: list[str] = field(default_factory=list)
    raw_text: str = ""
    extensions: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_input(cls, value: SemanticInput, *, reference_id: str = "reference") -> "ReferenceProfile":
        data, raw = _mapping(value)
        known = {"reference_id", "id", "source_ref", "capabilities", "apply_scope", "forbidden_surface_copy", "raw_text", "raw_input"}
        return cls(reference_id=_text(data.get("reference_id", data.get("id", reference_id))) or reference_id,
                   source_ref=_text(data.get("source_ref")), capabilities=[_text(item) for item in _list(data.get("capabilities"))],
                   apply_scope=[_text(item) for item in _list(data.get("apply_scope"))],
                   forbidden_surface_copy=[_text(item) for item in _list(data.get("forbidden_surface_copy"))],
                   raw_text=raw or _text(data.get("raw_text")), extensions=_extra(data, known))


@dataclass(slots=True)
class EndConditions:
    hard_events_complete: bool = True
    order_subject_results_match: bool = True
    state_stable: bool = True
    natural_stop: bool = True
    continuable_state: bool = True


@dataclass(slots=True)
class ValidationIssue:
    check: str
    message: str
    severity: str = "warning"
    evidence: Any = None


@dataclass(slots=True)
class ValidationReport:
    status: str = "pass"
    issues: list[ValidationIssue] = field(default_factory=list)
    attempt: int = 0

    @property
    def needs_repair(self) -> bool:
        return self.status == "repair_required"


@dataclass(slots=True)
class GenerationContract:
    request: GenerationRequest
    outline: OutlineContract
    length: LengthPolicy = field(default_factory=LengthPolicy)
    preferences: AuthorPreferenceProfile = field(default_factory=AuthorPreferenceProfile)
    end_conditions: EndConditions = field(default_factory=EndConditions)
    max_repairs: int = 3
    context: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)

    def semantic_errors(self) -> list[str]:
        errors = []
        if not self.request.story_id:
            errors.append("缺少 story_id")
        if not self.request.timeline_id:
            errors.append("缺少 timeline_id")
        if not self.outline.has_writing_goal:
            errors.append("缺少核心写作目标或大纲")
        return errors


@dataclass(slots=True)
class GenerationResult:
    text: str
    status: str = "pass"
    warnings: list[str] = field(default_factory=list)
    validation: ValidationReport = field(default_factory=ValidationReport)
    events: list[EventResult] = field(default_factory=list)
    state: SceneState | None = None
    attempts: int = 0
    extensions: dict[str, Any] = field(default_factory=dict)
