"""Stable application-facing protocols for graph and retrieval adapters."""

from __future__ import annotations

from typing import Any, Protocol

from .types import ContextBundle, RetrievalRequest


class GraphReader(Protocol):
    """Read-only graph projection contract.

    Concrete readers must open their storage read-only and validate identity,
    schema, and freshness before serving these methods.  The protocol itself
    deliberately does not mention SQLite row or connection types.
    """

    def manifest(self) -> Any:
        ...

    def resolve_aliases(self, text: str) -> Any:
        ...

    def neighbors(
        self,
        entity_ids: set[str],
        relation_types: set[str],
        max_hops: int = 1,
    ) -> list[Any]:
        ...

    def documents_for_entities(
        self,
        entity_ids: set[str],
        document_types: set[str] | None = None,
    ) -> list[Any]:
        ...


class Retriever(Protocol):
    """The sole retrieval dependency exposed to generation."""

    def retrieve(self, request: RetrievalRequest) -> ContextBundle:
        ...
