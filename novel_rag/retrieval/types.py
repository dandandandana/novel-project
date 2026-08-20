"""Framework-independent retrieval value objects.

These objects are intentionally storage agnostic.  In particular, an
``Evidence`` item contains provenance and an intra-channel score, but it does
not expose a database row or a score that can be compared with another
channel's score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - imported only by type checkers
    from ..identity import GraphKey


class EvidenceChannel(str, Enum):
    """The only channels allowed in a retrieval result.

    ``shared`` is deliberately absent.  Shared modules are an Authority data
    source and must never become a sixth channel.
    """

    AUTHORITY = "authority"
    GRAPH = "graph"
    TEMPORAL = "temporal"
    LEXICAL = "lexical"
    SEMANTIC = "semantic"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(item.value for item in cls)


# A short alias is convenient for callers that use ``Channel`` in annotations.
Channel = EvidenceChannel


@dataclass(frozen=True, slots=True)
class Evidence:
    """One explainable retrieval result.

    ``timeline_id`` and ``status`` are optional extensions to the original
    architecture sketch.  They are required by the conflict contract but were
    omitted from that sketch's field list; keeping them optional preserves
    compatibility with adapters that do not yet expose those metadata fields.
    """

    document_id: str
    channel: EvidenceChannel | str
    authority: str
    fact_type: str | None = None
    valid_at: str | None = None
    entity_ids: tuple[str, ...] = ()
    relation_path: tuple[str, ...] = ()
    reason: str = ""
    source_version: str | None = None
    source_fingerprint: str | None = None
    content: str = ""
    channel_score: float | None = None
    timeline_id: str | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.document_id, str) or not self.document_id.strip():
            raise ValueError("Evidence.document_id 不能为空")
        try:
            channel = EvidenceChannel(self.channel)
        except (TypeError, ValueError) as exc:
            allowed = ", ".join(EvidenceChannel.values())
            raise ValueError(
                f"Evidence.channel 必须是五个受支持通道之一: {allowed}"
            ) from exc
        object.__setattr__(self, "channel", channel)
        if not isinstance(self.authority, str) or not self.authority.strip():
            raise ValueError("Evidence.authority 不能为空")
        if not isinstance(self.content, str):
            raise TypeError("Evidence.content 必须是字符串")
        object.__setattr__(self, "entity_ids", tuple(str(value) for value in self.entity_ids))
        object.__setattr__(self, "relation_path", tuple(str(value) for value in self.relation_path))

    @property
    def channel_name(self) -> str:
        """Return a JSON-friendly channel value."""

        return self.channel.value


@dataclass(frozen=True, slots=True)
class RetrievalRequest:
    """Input contract for a retrieval operation."""

    graph_key: Any
    outline: str
    target_entities: tuple[str, ...] = ()
    target_stage: str | None = None
    token_budget: int | None = None

    def __post_init__(self) -> None:
        if self.graph_key is None:
            raise ValueError("RetrievalRequest.graph_key 不能为空")
        if not isinstance(self.outline, str):
            raise TypeError("RetrievalRequest.outline 必须是字符串")
        if isinstance(self.token_budget, bool):
            raise ValueError("token_budget 必须是正整数或 None")
        if self.token_budget is not None and self.token_budget <= 0:
            raise ValueError("token_budget 显式值必须大于 0；None 表示使用默认预算")
        object.__setattr__(self, "target_entities", tuple(str(value) for value in self.target_entities))

    def resolved_token_budget(self, default: int) -> int:
        """Resolve ``None`` to a validated system default."""

        if isinstance(default, bool) or not isinstance(default, int) or default <= 0:
            raise ValueError("默认 token budget 必须是正整数")
        return default if self.token_budget is None else self.token_budget


@dataclass(frozen=True, slots=True)
class ContextConflict:
    """An unresolved contradiction with enough provenance to explain it."""

    fact_type: str | None
    timeline_id: str | None
    valid_at: str | None
    evidence: tuple[Evidence, ...]
    reason: str
    differing_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.evidence) < 2:
            raise ValueError("ContextConflict 至少需要两条候选证据")
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "differing_fields", tuple(self.differing_fields))

    @property
    def fact_key(self) -> tuple[str | None, str | None, str | None]:
        """The identity dimensions used to group competing facts."""

        return self.fact_type, self.timeline_id, self.valid_at

    @property
    def candidate_keys(
        self,
    ) -> tuple[tuple[str | None, str | None, str | None, str | None, str, str | None], ...]:
        """Return the full explainability key for every competing source.

        The first three components identify the fact group. ``status``,
        ``authority`` and ``source_version`` are retained per candidate so a
        caller can present the documented resolution order without silently
        selecting a winner.
        """

        return tuple(
            (
                self.fact_type,
                self.timeline_id,
                self.valid_at,
                item.status,
                item.authority,
                item.source_version,
            )
            for item in self.evidence
        )

    @property
    def candidate_metadata(self) -> tuple[dict[str, Any], ...]:
        """Return compact status/authority/version provenance for diagnostics."""

        return tuple(
            {
                "document_id": item.document_id,
                "status": item.status,
                "authority": item.authority,
                "source_version": item.source_version,
                "channel": item.channel.value,
            }
            for item in self.evidence
        )


@dataclass(frozen=True, slots=True)
class ChannelStats:
    """Per-channel accounting included in a :class:`RetrievalReceipt`."""

    channel: EvidenceChannel
    candidate_count: int = 0
    selected_count: int = 0
    token_count: int = 0
    dropped_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "channel", EvidenceChannel(self.channel))
        for name in ("candidate_count", "selected_count", "token_count", "dropped_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"ChannelStats.{name} 必须是非负整数")


@dataclass(frozen=True, slots=True)
class RetrievalReceipt:
    """Audit trail for one assembled context.

    Counts are intentionally kept separate by channel.  There is no combined
    relevance score because raw scores from different channels have no common
    scale.
    """

    graph_key: Any = None
    requested_token_budget: int | None = None
    effective_token_budget: int = 4096
    used_token_count: int = 0
    candidate_count: int = 0
    selected_count: int = 0
    deduplicated_count: int = 0
    conflict_count: int = 0
    channel_stats: tuple[ChannelStats, ...] = ()
    dropped_document_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.requested_token_budget is not None and self.requested_token_budget <= 0:
            raise ValueError("requested_token_budget 必须为 None 或正整数")
        if self.effective_token_budget <= 0:
            raise ValueError("effective_token_budget 必须大于 0")
        for name in (
            "used_token_count",
            "candidate_count",
            "selected_count",
            "deduplicated_count",
            "conflict_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"RetrievalReceipt.{name} 必须是非负整数")
        object.__setattr__(self, "channel_stats", tuple(self.channel_stats))
        object.__setattr__(self, "dropped_document_ids", tuple(str(value) for value in self.dropped_document_ids))
        object.__setattr__(self, "notes", tuple(str(value) for value in self.notes))

    @property
    def selected_by_channel(self) -> dict[EvidenceChannel, int]:
        return {item.channel: item.selected_count for item in self.channel_stats}


@dataclass(frozen=True, slots=True)
class ContextBundle:
    """The only context shape generation should consume."""

    mandatory: tuple[Evidence, ...] = ()
    graph_context: tuple[Evidence, ...] = ()
    temporal_memory: tuple[Evidence, ...] = ()
    lexical_supplements: tuple[Evidence, ...] = ()
    semantic_supplements: tuple[Evidence, ...] = ()
    conflicts: tuple[ContextConflict, ...] = ()
    receipt: RetrievalReceipt = field(default_factory=RetrievalReceipt)

    def __post_init__(self) -> None:
        for name in (
            "mandatory",
            "graph_context",
            "temporal_memory",
            "lexical_supplements",
            "semantic_supplements",
            "conflicts",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    @property
    def all_evidence(self) -> tuple[Evidence, ...]:
        return (
            *self.mandatory,
            *self.graph_context,
            *self.temporal_memory,
            *self.lexical_supplements,
            *self.semantic_supplements,
        )
