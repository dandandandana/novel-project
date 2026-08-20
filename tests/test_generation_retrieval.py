from pathlib import Path

import pytest

from novel_rag.generation import (
    GenerationError,
    build_retrieval_request,
    retrieve_context,
)
from novel_rag.generation_schema import (
    AuthorPreferenceProfile,
    GenerationContract,
    GenerationRequest,
    OutlineContract,
)
from novel_rag.identity import GraphKey
from novel_rag.retrieval import ContextBundle, ContextConflict, Evidence, EvidenceChannel


def _contract() -> GenerationContract:
    request = GenerationRequest.from_input(
        {
            "story_id": "demo",
            "timeline_id": "main",
            "outline": {"required_events": [{"event": "甲打开门", "actor": "甲", "target": "门"}]},
        }
    )
    return GenerationContract(
        request=request,
        outline=OutlineContract.from_input(request.outline),
        preferences=AuthorPreferenceProfile.from_input("默认"),
    )


class StubRetriever:
    def __init__(self, bundle: ContextBundle) -> None:
        self.bundle = bundle
        self.request = None

    def retrieve(self, request):
        self.request = request
        return self.bundle


def _evidence(*, content: str, status: str = "active", fact_type: str | None = "canon") -> Evidence:
    return Evidence(
        document_id=f"doc-{abs(hash(content))}",
        channel=EvidenceChannel.AUTHORITY,
        authority="canon",
        fact_type=fact_type,
        content=content,
        timeline_id="main",
        status=status,
    )


def test_generation_retrieval_injects_contract_and_preserves_context_shape(tmp_path: Path) -> None:
    evidence = _evidence(content="甲打开门，门外没有人。")
    retriever = StubRetriever(ContextBundle(mandatory=(evidence,)))

    items = retrieve_context(_contract(), tmp_path / "index", retriever=retriever)

    assert isinstance(retriever.request.graph_key, GraphKey)
    assert retriever.request.graph_key == GraphKey("demo", "main")
    assert "甲打开门" in retriever.request.outline
    assert items[0].document_id == evidence.document_id
    assert items[0].document_type == "canon"
    assert items[0].metadata["channel"] == "authority"


def test_generation_retrieval_rejects_conflicts_before_context_conversion(tmp_path: Path) -> None:
    first = _evidence(content="门外有人。")
    second = _evidence(content="门外无人。")
    conflict = ContextConflict(
        fact_type="canon",
        timeline_id="main",
        valid_at=None,
        evidence=(first, second),
        reason="contradictory canon",
    )
    retriever = StubRetriever(ContextBundle(mandatory=(first, second), conflicts=(conflict,)))

    with pytest.raises(GenerationError, match="未解决冲突"):
        retrieve_context(_contract(), tmp_path / "index", retriever=retriever)


def test_generation_retrieval_rejects_stale_evidence(tmp_path: Path) -> None:
    retriever = StubRetriever(ContextBundle(mandatory=(_evidence(content="旧图", status="stale"),)))

    with pytest.raises(GenerationError, match="stale"):
        retrieve_context(_contract(), tmp_path / "index", retriever=retriever)


def test_retrieval_request_uses_graph_key_contract() -> None:
    request = build_retrieval_request(_contract())

    assert request.graph_key == GraphKey("demo", "main")
    assert request.target_entities == ("甲", "门")

