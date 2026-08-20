"""Deterministic context assembly with per-channel budgets.

Scores are used only to order candidates inside one channel.  Candidates from
different channels are never added, normalized into a shared score, or
compared by score.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Callable, Iterable, Mapping

from .conflicts import ConflictGuard
from .types import (
    ChannelStats,
    ContextBundle,
    ContextConflict,
    Evidence,
    EvidenceChannel,
    RetrievalReceipt,
    RetrievalRequest,
)


DEFAULT_TOKEN_BUDGET = 4096
DEFAULT_CHANNEL_QUOTAS: dict[EvidenceChannel, float] = {
    EvidenceChannel.GRAPH: 0.40,
    EvidenceChannel.TEMPORAL: 0.30,
    EvidenceChannel.LEXICAL: 0.20,
    EvidenceChannel.SEMANTIC: 0.10,
}
_OPTIONAL_CHANNELS = tuple(DEFAULT_CHANNEL_QUOTAS)
_LAYER_NAMES = (
    "mandatory",
    "graph_context",
    "temporal_memory",
    "lexical_supplements",
    "semantic_supplements",
)
_TOKEN_PART_RE = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9_]+|[^\w\s]", re.UNICODE)


class BudgetExceeded(ValueError):
    """Raised when mandatory evidence cannot fit the requested budget."""


def estimate_tokens(text: str) -> int:
    """Estimate tokens without a model/tokenizer dependency.

    CJK characters and punctuation count individually; contiguous Latin
    letters/digits count as one token.  This is a deterministic budget guard,
    not a claim about any particular model's tokenizer.
    """

    if not isinstance(text, str):
        raise TypeError("token estimation requires a string")
    return len(_TOKEN_PART_RE.findall(text))


def _evidence_identity(item: Evidence) -> tuple[object, ...]:
    # Channel is intentionally absent: the same source fact found by several
    # channels is represented once, with the highest-priority layer retaining
    # it.  Source/version/content remain in the key so distinct revisions are
    # not silently collapsed.
    return (
        item.document_id,
        item.fact_type,
        item.timeline_id,
        item.valid_at,
        item.status,
        item.source_version,
        item.source_fingerprint,
        item.content.strip(),
    )


def _score_key(item: Evidence) -> tuple[int, float, str, str]:
    # Sorting by score is allowed only for candidates in the same channel.
    score_missing = item.channel_score is None
    score = 0.0 if score_missing else float(item.channel_score)
    # NaN must not make ordering platform-dependent.
    if math.isnan(score):
        score_missing = True
        score = float("-inf")
    return (1 if score_missing else 0, -score, item.document_id, item.content.strip())


def _dedupe_candidates(
    layers: Mapping[str, tuple[Evidence, ...]],
) -> tuple[dict[str, tuple[Evidence, ...]], int]:
    seen: dict[tuple[object, ...], Evidence] = {}
    seen_layer: dict[tuple[object, ...], str] = {}
    unique_layers: dict[str, list[Evidence]] = {name: [] for name in _LAYER_NAMES}
    duplicates = 0
    for layer_name in _LAYER_NAMES:
        for item in layers[layer_name]:
            identity = _evidence_identity(item)
            previous = seen.get(identity)
            if previous is None:
                seen[identity] = item
                seen_layer[identity] = layer_name
                unique_layers[layer_name].append(item)
                continue
            duplicates += 1
            previous_layer = seen_layer[identity]
            if previous_layer == layer_name:
                # Same-channel duplicates may use their channel-local score.
                if _score_key(item) < _score_key(previous):
                    values = unique_layers[previous_layer]
                    values[values.index(previous)] = item
                    seen[identity] = item
            # Cross-channel duplicates retain the earlier layer.  This is a
            # layer-priority decision, never a cross-channel score comparison.
    return {name: tuple(values) for name, values in unique_layers.items()}, duplicates


class ContextAssembler:
    """Assemble a bounded, de-duplicated :class:`ContextBundle`."""

    def __init__(
        self,
        *,
        default_token_budget: int = DEFAULT_TOKEN_BUDGET,
        channel_quotas: Mapping[EvidenceChannel | str, float] | None = None,
        token_estimator: Callable[[str], int] = estimate_tokens,
        conflict_guard: ConflictGuard | None = None,
    ) -> None:
        if isinstance(default_token_budget, bool) or not isinstance(default_token_budget, int):
            raise ValueError("默认 token budget 必须是正整数")
        if default_token_budget <= 0:
            raise ValueError("默认 token budget 必须大于 0")
        if not callable(token_estimator):
            raise TypeError("token_estimator 必须可调用")
        quotas: dict[EvidenceChannel, float] = dict(DEFAULT_CHANNEL_QUOTAS)
        if channel_quotas is not None:
            for raw_channel, raw_quota in channel_quotas.items():
                try:
                    channel = EvidenceChannel(raw_channel)
                except (TypeError, ValueError) as exc:
                    raise ValueError("channel quota 只能使用五个受支持通道，不能使用 shared") from exc
                if channel is EvidenceChannel.AUTHORITY:
                    raise ValueError("authority 通过 mandatory 层配额，不接受独立 optional quota")
                if isinstance(raw_quota, bool) or not isinstance(raw_quota, (int, float)):
                    raise ValueError("channel quota 必须是 0 到 1 之间的数字")
                if not 0 <= float(raw_quota) <= 1:
                    raise ValueError("channel quota 必须是 0 到 1 之间的数字")
                quotas[channel] = float(raw_quota)
        if sum(quotas.values()) > 1.0 + 1e-9:
            raise ValueError("optional channel quotas 的总和不能大于 1")
        self.default_token_budget = default_token_budget
        self.channel_quotas = quotas
        self.token_estimator = token_estimator
        self.conflict_guard = conflict_guard or ConflictGuard()

    def assemble(
        self,
        request: RetrievalRequest,
        *,
        mandatory: Iterable[Evidence] = (),
        graph_context: Iterable[Evidence] = (),
        temporal_memory: Iterable[Evidence] = (),
        lexical_supplements: Iterable[Evidence] = (),
        semantic_supplements: Iterable[Evidence] = (),
        conflicts: Iterable[ContextConflict] = (),
    ) -> ContextBundle:
        if not isinstance(request, RetrievalRequest):
            raise TypeError("ContextAssembler 需要 RetrievalRequest")
        raw_layers: dict[str, tuple[Evidence, ...]] = {
            "mandatory": tuple(mandatory),
            "graph_context": tuple(graph_context),
            "temporal_memory": tuple(temporal_memory),
            "lexical_supplements": tuple(lexical_supplements),
            "semantic_supplements": tuple(semantic_supplements),
        }
        self._validate_layers(raw_layers)
        layers, deduplicated_count = _dedupe_candidates(raw_layers)
        all_candidates = tuple(item for name in _LAYER_NAMES for item in layers[name])
        detected_conflicts = self.conflict_guard.detect(
            all_candidates,
            timeline_id=self._request_timeline(request),
        )
        all_conflicts = self._merge_conflicts(detected_conflicts, tuple(conflicts))

        effective_budget = request.resolved_token_budget(self.default_token_budget)
        mandatory_items = layers["mandatory"]
        mandatory_tokens = sum(self._tokens(item) for item in mandatory_items)
        if mandatory_tokens > effective_budget:
            raise BudgetExceeded(
                "mandatory evidence 超出 token_budget: "
                f"需要 {mandatory_tokens}，预算 {effective_budget}"
            )

        selected: dict[str, tuple[Evidence, ...]] = {
            "mandatory": mandatory_items,
            "graph_context": (),
            "temporal_memory": (),
            "lexical_supplements": (),
            "semantic_supplements": (),
        }
        optional_budget = effective_budget - mandatory_tokens
        optional_caps = self._optional_caps(optional_budget)
        used_optional = 0
        dropped_ids: list[str] = []
        for channel, layer_name in zip(
            _OPTIONAL_CHANNELS,
            ("graph_context", "temporal_memory", "lexical_supplements", "semantic_supplements"),
        ):
            candidates = layers[layer_name]
            cap = optional_caps[channel]
            chosen, dropped = self._select_within_channel(candidates, cap)
            selected[layer_name] = chosen
            used_optional += sum(self._tokens(item) for item in chosen)
            dropped_ids.extend(item.document_id for item in dropped)

        all_selected = tuple(item for name in _LAYER_NAMES for item in selected[name])
        stats = self._channel_stats(raw_layers, selected, dropped_ids)
        receipt = RetrievalReceipt(
            graph_key=request.graph_key,
            requested_token_budget=request.token_budget,
            effective_token_budget=effective_budget,
            used_token_count=mandatory_tokens + used_optional,
            candidate_count=sum(len(raw_layers[name]) for name in _LAYER_NAMES),
            selected_count=len(all_selected),
            deduplicated_count=deduplicated_count,
            conflict_count=len(all_conflicts),
            channel_stats=stats,
            dropped_document_ids=tuple(dict.fromkeys(dropped_ids)),
        )
        return ContextBundle(
            mandatory=selected["mandatory"],
            graph_context=selected["graph_context"],
            temporal_memory=selected["temporal_memory"],
            lexical_supplements=selected["lexical_supplements"],
            semantic_supplements=selected["semantic_supplements"],
            conflicts=all_conflicts,
            receipt=receipt,
        )

    @staticmethod
    def _request_timeline(request: RetrievalRequest) -> str | None:
        key = request.graph_key
        if isinstance(key, Mapping):
            value = key.get("timeline_id")
        else:
            value = getattr(key, "timeline_id", None)
        return str(value) if value not in (None, "") else None

    @staticmethod
    def _validate_layers(layers: Mapping[str, tuple[Evidence, ...]]) -> None:
        expected = {
            "graph_context": EvidenceChannel.GRAPH,
            "temporal_memory": EvidenceChannel.TEMPORAL,
            "lexical_supplements": EvidenceChannel.LEXICAL,
            "semantic_supplements": EvidenceChannel.SEMANTIC,
        }
        for layer_name, items in layers.items():
            for item in items:
                if not isinstance(item, Evidence):
                    raise TypeError(f"{layer_name} 只能包含 Evidence")
                required_channel = expected.get(layer_name)
                if required_channel is not None and item.channel is not required_channel:
                    raise ValueError(
                        f"{layer_name} 只能接收 {required_channel.value} channel，"
                        f"收到 {item.channel.value}"
                    )

    def _tokens(self, item: Evidence) -> int:
        value = self.token_estimator(item.content)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("token_estimator 必须返回非负整数")
        return value

    def _optional_caps(self, optional_budget: int) -> dict[EvidenceChannel, int]:
        caps: dict[EvidenceChannel, int] = {}
        consumed = 0
        for channel in _OPTIONAL_CHANNELS[:-1]:
            cap = int(optional_budget * self.channel_quotas[channel])
            caps[channel] = cap
            consumed += cap
        last = _OPTIONAL_CHANNELS[-1]
        caps[last] = max(0, optional_budget - consumed)
        return caps

    def _select_within_channel(
        self,
        candidates: tuple[Evidence, ...],
        cap: int,
    ) -> tuple[tuple[Evidence, ...], tuple[Evidence, ...]]:
        chosen: list[Evidence] = []
        dropped: list[Evidence] = []
        used = 0
        for item in sorted(candidates, key=_score_key):
            cost = self._tokens(item)
            if used + cost <= cap:
                chosen.append(item)
                used += cost
            else:
                dropped.append(item)
        return tuple(chosen), tuple(dropped)

    @staticmethod
    def _merge_conflicts(
        detected: tuple[ContextConflict, ...],
        supplied: tuple[ContextConflict, ...],
    ) -> tuple[ContextConflict, ...]:
        merged: list[ContextConflict] = []
        seen: set[tuple[object, ...]] = set()
        for conflict in (*detected, *supplied):
            key = (
                conflict.fact_type,
                conflict.timeline_id,
                conflict.valid_at,
                tuple(item.document_id for item in conflict.evidence),
            )
            if key not in seen:
                merged.append(conflict)
                seen.add(key)
        return tuple(merged)

    def _channel_stats(
        self,
        raw_layers: Mapping[str, tuple[Evidence, ...]],
        selected: Mapping[str, tuple[Evidence, ...]],
        dropped_ids: list[str],
    ) -> tuple[ChannelStats, ...]:
        raw_by_channel: dict[EvidenceChannel, int] = defaultdict(int)
        selected_by_channel: dict[EvidenceChannel, list[Evidence]] = defaultdict(list)
        for name in _LAYER_NAMES:
            for item in raw_layers[name]:
                raw_by_channel[item.channel] += 1
            for item in selected[name]:
                selected_by_channel[item.channel].append(item)
        result: list[ChannelStats] = []
        for channel in EvidenceChannel:
            channel_selected = selected_by_channel[channel]
            result.append(
                ChannelStats(
                    channel=channel,
                    candidate_count=raw_by_channel[channel],
                    selected_count=len(channel_selected),
                    token_count=sum(self._tokens(item) for item in channel_selected),
                    dropped_count=sum(1 for item in dropped_ids if any(
                        candidate.document_id == item and candidate.channel is channel
                        for candidates in raw_layers.values() for candidate in candidates
                    )),
                )
            )
        return tuple(result)
