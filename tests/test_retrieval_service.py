from __future__ import annotations

from pathlib import Path

import pytest

from novel_rag.documents import RagDocument
from novel_rag.graph import GraphKey, GraphReadError, GraphReader, SharedReader, ValidatedCorpus, build_shared
from novel_rag.graph.builder import GraphBuilder
from novel_rag.retrieval import (
    EvidenceChannel,
    RetrievalAmbiguityError,
    RetrievalConfigurationError,
    RetrievalRequest,
    RetrieverService,
)


def _document(
    root: Path,
    document_id: str,
    *,
    story_id: str = "story",
    timeline_id: str = "main",
    document_type: str = "canon",
    text: str = "甲在城内，守护乙。",
    entities: list[str] | None = None,
    aliases: dict[str, list[str]] | None = None,
    relations: list[dict[str, str]] | None = None,
    **extra,
) -> RagDocument:
    path = root / f"{document_id}.yaml"
    path.write_text(text, encoding="utf-8")
    metadata = {
        "document_id": document_id,
        "story_id": story_id,
        "timeline_id": timeline_id,
        "document_type": document_type,
        "status": "active" if document_type in {"rule", "feedback"} else "canon",
        "version": "1.0",
        "title": document_id,
    }
    if entities:
        metadata["entities"] = [{"entity_id": value, "name": value} for value in entities]
    if aliases:
        metadata["aliases"] = aliases
    if relations:
        metadata["relations"] = relations
    metadata.update(extra)
    return RagDocument(path, metadata, {"text": text})


def _build_readers(tmp_path: Path):
    shared_doc = _document(
        tmp_path,
        "rule-1",
        story_id="__shared__",
        timeline_id="global",
        document_type="rule",
        text="所有角色必须遵守中文叙事规则。",
        module_type="ruler",
        priority=1,
        enforcement="must",
    )
    story_doc = _document(
        tmp_path,
        "canon-1",
        text="甲在城内，守护乙。",
        entities=["a", "b"],
        aliases={"a": ["甲"], "b": ["乙"]},
        relations=[{"subject_id": "a", "relation_type": "protects", "object_id": "b"}],
        fact_type="location",
        valid_at="chapter-1",
    )
    summary = _document(
        tmp_path,
        "summary-1",
        document_type="chapter-summary",
        text="甲在第一章守护了乙。",
        entities=["a", "b"],
        ownership="auto",
        covers_through="chapter-1",
    )
    feedback = _document(
        tmp_path,
        "feedback-LETTER-FEEDBACK-921",
        document_type="feedback",
        text="LETTER-FEEDBACK-921：交信后必须留出接住信件的动作。",
        target_type="runtime",
        target_id="generation",
        correction_rule=["交信后留出接住信件的动作"],
    )
    shared_corpus = ValidatedCorpus.from_documents([shared_doc], source_root=tmp_path, strict=False)
    story_corpus = ValidatedCorpus.from_documents(
        [story_doc, summary, feedback], source_root=tmp_path, strict=False
    )
    shared_result = build_shared(shared_corpus, tmp_path / "index")
    graph_result = GraphBuilder(
        GraphKey("story", "main"),
        story_corpus,
        tmp_path / "index",
        # Explicitly tie the story graph to the shared manifest for freshness tests.
        shared_manifest_fingerprint=shared_result.manifest.source_fingerprint,
    ).build()
    return graph_result, shared_result, story_corpus, shared_corpus


def test_service_composes_authority_graph_temporal_lexical_and_empty_semantic(tmp_path: Path) -> None:
    graph_result, shared_result, story_corpus, shared_corpus = _build_readers(tmp_path)
    with GraphReader(graph_result.path, expected_key=GraphKey("story", "main")) as graph_reader:
        with SharedReader(shared_result.path) as shared_reader:
            service = RetrieverService(
                graph_reader,
                shared_reader=shared_reader,
                corpus=story_corpus,
                shared_corpus=shared_corpus,
            )
            bundle = service.retrieve(
                RetrievalRequest(GraphKey("story", "main"), "甲在城内", target_entities=("甲",))
            )

    channels = {item.channel for item in bundle.all_evidence}
    assert EvidenceChannel.AUTHORITY in channels
    assert EvidenceChannel.GRAPH in channels
    assert EvidenceChannel.TEMPORAL in channels
    # Lexical hits are present in the receipt even when the same document was
    # already selected by a higher-priority layer and de-duplicated.
    lexical_stats = next(
        item for item in bundle.receipt.channel_stats if item.channel is EvidenceChannel.LEXICAL
    )
    assert lexical_stats.candidate_count > 0
    assert EvidenceChannel.SEMANTIC not in channels
    assert all(item.channel.value != "shared" for item in bundle.all_evidence)
    assert bundle.receipt.graph_key == GraphKey("story", "main")
    assert bundle.receipt.conflict_count == len(bundle.conflicts)


def test_canonical_graph_active_feedback_is_recalled_by_split_outline_queries(tmp_path: Path) -> None:
    """A feedback ID must survive an unrelated multi-term scene outline."""

    graph_result, shared_result, story_corpus, shared_corpus = _build_readers(tmp_path)
    with GraphReader(graph_result.path, expected_key=GraphKey("story", "main")) as graph_reader:
        with SharedReader(shared_result.path) as shared_reader:
            service = RetrieverService(
                graph_reader,
                shared_reader=shared_reader,
                corpus=story_corpus,
                shared_corpus=shared_corpus,
            )
            bundle = service.retrieve(
                RetrievalRequest(
                    GraphKey("story", "main"),
                    "LETTER-FEEDBACK-921 甲交出信",
                )
            )

    feedback = next(
        item for item in bundle.mandatory
        if item.document_id == "feedback-LETTER-FEEDBACK-921"
    )
    assert feedback.channel is EvidenceChannel.AUTHORITY
    assert "LETTER-FEEDBACK-921" in feedback.reason
    lexical_stats = next(
        item for item in bundle.receipt.channel_stats
        if item.channel is EvidenceChannel.LEXICAL
    )
    assert lexical_stats.candidate_count > 0


def test_service_rejects_graph_key_mismatch_and_propagates_stale(tmp_path: Path) -> None:
    graph_result, shared_result, story_corpus, shared_corpus = _build_readers(tmp_path)
    with GraphReader(graph_result.path) as graph_reader, SharedReader(shared_result.path) as shared_reader:
        service = RetrieverService(
            graph_reader,
            shared_reader=shared_reader,
            corpus=story_corpus,
            shared_corpus=shared_corpus,
        )
        with pytest.raises(GraphReadError, match="身份"):
            service.retrieve(RetrievalRequest(GraphKey("other", "main"), "甲在城内"))
        story_corpus.documents[0].path.write_text("changed", encoding="utf-8")
        with pytest.raises(GraphReadError, match="stale"):
            service.retrieve(RetrievalRequest(GraphKey("story", "main"), "甲在城内"))


def test_service_detects_ambiguous_longest_alias(tmp_path: Path) -> None:
    class AmbiguousReader:
        def manifest(self):
            return type("Manifest", (), {"story_id": "story", "timeline_id": "main", "source_fingerprint": "x", "shared_manifest_fingerprint": None})()

        def resolve_aliases(self, _text):
            return type(
                "Resolution",
                (),
                {
                    "entity_ids": ("a", "b"),
                    "matches": (
                        {"alias": "甲", "entity_id": "a"},
                        {"alias": "甲", "entity_id": "b"},
                    ),
                },
            )()

        def neighbors(self, *_args):
            return []

        def documents_for_entities(self, *_args):
            return []

        def search(self, *_args, **_kwargs):
            return []

    with pytest.raises(RetrievalAmbiguityError):
        RetrieverService(AmbiguousReader()).retrieve(
            RetrievalRequest(GraphKey("story", "main"), "", target_entities=("甲",))
        )


def test_semantic_is_off_by_default_and_requires_explicit_provider() -> None:
    class Reader:
        def manifest(self):
            return type("Manifest", (), {"story_id": "story", "timeline_id": "main", "source_fingerprint": "x", "shared_manifest_fingerprint": None})()

    with pytest.raises(RetrievalConfigurationError, match="semantic_provider"):
        RetrieverService(Reader(), semantic_enabled=True)
