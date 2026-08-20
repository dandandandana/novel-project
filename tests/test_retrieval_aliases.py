from __future__ import annotations

import pytest

from novel_rag.graph.types import EntityResolution
from novel_rag.identity import GraphKey
from novel_rag.retrieval import RetrievalRequest, RetrieverService


class AliasReader:
    def __init__(self, aliases: dict[str, str]) -> None:
        self.aliases = aliases
        self.resolved: list[str] = []
        self.entity_sets: list[set[str]] = []

    def manifest(self):
        return type(
            "Manifest",
            (),
            {
                "story_id": "story",
                "timeline_id": "main",
                "source_fingerprint": "source-1",
                "shared_manifest_fingerprint": None,
            },
        )()

    def resolve_aliases(self, text: str) -> EntityResolution:
        self.resolved.append(text)
        entity_id = self.aliases.get(text)
        if entity_id is None:
            return EntityResolution(text, ())
        return EntityResolution(text, (entity_id,), ({"alias": text, "entity_id": entity_id},))

    def neighbors(self, entity_ids, _relation_types, _max_hops):
        self.entity_sets.append(set(entity_ids))
        return []

    def documents_for_entities(self, _entity_ids, _document_types=None):
        return []

    def search(self, _query: str, *, limit: int):
        assert limit > 0
        return []


@pytest.mark.parametrize(
    ("outline", "alias", "entity_id"),
    (
        ("甲在城内巡逻", "甲", "character-jia"),
        ("阿尔法在城内巡逻", "阿尔法", "character-alpha"),
        ("Alice guards the gate", "Alice", "character-alice"),
    ),
)
def test_free_text_terms_reach_alias_resolution(
    outline: str,
    alias: str,
    entity_id: str,
) -> None:
    reader = AliasReader({alias: entity_id})
    service = RetrieverService(reader)

    service.retrieve(RetrievalRequest(GraphKey("story", "main"), outline))

    assert alias in reader.resolved
    assert any(entity_id in entity_ids for entity_ids in reader.entity_sets)
