from __future__ import annotations

import pytest

from novel_rag.retrieval import (
    BudgetExceeded,
    ContextAssembler,
    ConflictGuard,
    ContextBundle,
    Evidence,
    EvidenceChannel,
    RetrievalRequest,
)


class Key:
    def __init__(self, timeline_id: str = "main") -> None:
        self.story_id = "story"
        self.timeline_id = timeline_id


def evidence(
    document_id: str,
    channel: EvidenceChannel,
    content: str,
    *,
    fact_type: str | None = None,
    timeline_id: str | None = "main",
    status: str | None = "active",
    authority: str = "canon",
    version: str | None = "1",
    score: float | None = None,
) -> Evidence:
    return Evidence(
        document_id=document_id,
        channel=channel,
        authority=authority,
        fact_type=fact_type,
        valid_at="chapter-1" if fact_type else None,
        reason="test fixture",
        source_version=version,
        source_fingerprint=f"sha256:{document_id}",
        content=content,
        channel_score=score,
        timeline_id=timeline_id,
        status=status,
    )


def request(*, budget: int | None = None) -> RetrievalRequest:
    return RetrievalRequest(graph_key=Key(), outline="继续场景", token_budget=budget)


def test_evidence_allows_exactly_five_channels_and_rejects_shared() -> None:
    assert EvidenceChannel.values() == ("authority", "graph", "temporal", "lexical", "semantic")
    for channel in EvidenceChannel:
        assert evidence(channel.value, channel, "内容").channel is channel
    with pytest.raises(ValueError, match="五个受支持通道"):
        evidence("bad", "shared", "内容")  # type: ignore[arg-type]


def test_request_budget_none_uses_default_and_non_positive_is_rejected() -> None:
    assert request().resolved_token_budget(123) == 123
    assert request(budget=7).resolved_token_budget(123) == 7
    with pytest.raises(ValueError, match="大于 0"):
        request(budget=0)
    with pytest.raises(ValueError, match="大于 0"):
        request(budget=-1)


def test_conflict_guard_reports_fact_key_and_provenance_without_resolving() -> None:
    left = evidence("left", EvidenceChannel.AUTHORITY, "甲在城内", fact_type="location", authority="canon")
    right = evidence("right", EvidenceChannel.TEMPORAL, "甲在城外", fact_type="location", authority="current", version="2")

    conflicts = ConflictGuard().detect([left, right])

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.fact_key == ("location", "main", "chapter-1")
    assert "content" in conflict.differing_fields
    assert "authority" in conflict.differing_fields
    assert "source_version" in conflict.differing_fields
    assert "不按跨通道分数自动选边" in conflict.reason


def test_assembler_deduplicates_across_channels_and_never_adds_scores() -> None:
    shared = evidence("same", EvidenceChannel.AUTHORITY, "稳定事实", score=0.1)
    lexical_duplicate = evidence("same", EvidenceChannel.LEXICAL, "稳定事实", score=999.0)
    graph = evidence("graph", EvidenceChannel.GRAPH, "关系", score=0.2)
    bundle = ContextAssembler(default_token_budget=100).assemble(
        request(budget=None), mandatory=[shared], graph_context=[graph], lexical_supplements=[lexical_duplicate]
    )

    assert [item.document_id for item in bundle.all_evidence] == ["same", "graph"]
    assert bundle.receipt.deduplicated_count == 1
    assert bundle.receipt.selected_count == 2
    assert bundle.receipt.used_token_count <= bundle.receipt.effective_token_budget


def test_assembler_uses_channel_local_scores_and_optional_quotas() -> None:
    graph_high = evidence("graph-high", EvidenceChannel.GRAPH, "甲甲甲甲甲", score=0.1)
    graph_low = evidence("graph-low", EvidenceChannel.GRAPH, "乙乙乙乙乙", score=0.9)
    temporal = evidence("temporal", EvidenceChannel.TEMPORAL, "历史", score=0.0)
    bundle = ContextAssembler(default_token_budget=20).assemble(
        request(budget=20), graph_context=[graph_high, graph_low], temporal_memory=[temporal]
    )

    # Graph's own score orders graph-low first; temporal is not compared with
    # graph scores.  At least one graph item remains within its quota.
    assert bundle.graph_context[0].document_id == "graph-low"
    assert all(item.channel is EvidenceChannel.GRAPH for item in bundle.graph_context)
    assert bundle.receipt.used_token_count <= 20


def test_mandatory_over_budget_fails_loudly() -> None:
    required = evidence("required", EvidenceChannel.AUTHORITY, "一二三四五")
    with pytest.raises(BudgetExceeded, match="mandatory evidence"):
        ContextAssembler(default_token_budget=2).assemble(request(budget=2), mandatory=[required])


def test_assembler_rejects_wrong_layer_channel_and_context_bundle_is_immutable() -> None:
    wrong = evidence("wrong", EvidenceChannel.LEXICAL, "词面")
    with pytest.raises(ValueError, match="graph_context"):
        ContextAssembler().assemble(request(), graph_context=[wrong])
    assert ContextBundle().all_evidence == ()
