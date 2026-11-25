"""Error classes, constants, and dataclasses for state review."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


class StateReviewError(ValueError):
    """Raised when a proposal cannot be safely reviewed or promoted."""


# Compatibility name used by a few callers that call all writeback failures
# "StatePromotionError".
StatePromotionError = StateReviewError


_CHARACTER_FIELDS = {
    "current_position",
    "physical",
    "mental",
    "knowledge",
    "goals",
    "relationships",
    "abilities",
    "inventory",
    "narrative",
}
_WORLD_FIELDS = {
    "timeline_position",
    "locations",
    "factions",
    "global_events",
    "public_knowledge",
    "hidden_world_changes",
    "unresolved_world_flags",
}
_CHARACTER_SUBFIELDS = {
    "current_position": {"location", "companions", "faction"},
    "physical": {"health", "injuries", "fatigue", "temporary_conditions", "permanent_changes"},
    "mental": {"dominant_emotions", "current_pressure", "desires", "fears", "unresolved_conflicts", "behavior_effects"},
    "knowledge": {"known", "unknown", "mistaken_beliefs", "suspicions", "secrets_held"},
    "goals": {"immediate", "short_term", "long_term", "priorities", "obstacles"},
    "abilities": {"available", "unavailable", "newly_acquired", "consumed_resources", "active_costs"},
    "inventory": {"carried", "lost", "damaged"},
    "narrative": {"current_arc", "completed_changes", "unresolved_flags", "active_promises", "future_pressure"},
}


@dataclass(slots=True)
class StateProposalReview:
    """A compact, serialisable view of a pending state proposal."""

    runtime_dir: str
    status: str
    writeback_id: str
    story_id: str
    timeline_id: str
    history_document_id: str
    character_ids: list[str] = field(default_factory=list)
    world_fields: list[str] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    candidate_state: dict[str, Any] = field(default_factory=dict)
    event_state_deltas: list[dict[str, Any]] = field(default_factory=list)
    decision: str = ""
    promoted_document_ids: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_dir": self.runtime_dir,
            "status": self.status,
            "writeback_id": self.writeback_id,
            "story_id": self.story_id,
            "timeline_id": self.timeline_id,
            "history_document_id": self.history_document_id,
            "character_ids": list(self.character_ids),
            "world_fields": list(self.world_fields),
            "event_ids": list(self.event_ids),
            "evidence": copy.deepcopy(self.evidence),
            "candidate_state": copy.deepcopy(self.candidate_state),
            "event_state_deltas": copy.deepcopy(self.event_state_deltas),
            "decision": self.decision,
            "promoted_document_ids": list(self.promoted_document_ids),
            "skipped": dict(self.skipped),
        }


@dataclass(slots=True)
class StatePromotionResult:
    status: str
    decision: str
    writeback_id: str
    document_ids: list[str] = field(default_factory=list)
    snapshot_paths: list[str] = field(default_factory=list)
    change_log_paths: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    retrieval_cases: int = 0
    validation_issues: list[str] = field(default_factory=list)

    @property
    def state_promoted(self) -> bool:
        return self.status in {"promoted", "noop"} and bool(self.document_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "decision": self.decision,
            "writeback_id": self.writeback_id,
            "document_ids": list(self.document_ids),
            "snapshot_paths": list(self.snapshot_paths),
            "change_log_paths": list(self.change_log_paths),
            "skipped": dict(self.skipped),
            "retrieval_cases": self.retrieval_cases,
            "validation_issues": list(self.validation_issues),
            "state_promoted": self.state_promoted,
        }