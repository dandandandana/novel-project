"""Stable retrieval contracts and framework-independent assembly logic.

The package deliberately has no SQLite, model, or application-layer imports.
Storage adapters and channel implementations can depend on these contracts,
while generation only needs the :class:`Retriever` protocol.
"""

from .assembler import (
    BudgetExceeded,
    ContextAssembler,
    DEFAULT_CHANNEL_QUOTAS,
    DEFAULT_TOKEN_BUDGET,
    estimate_tokens,
)
from .conflicts import ConflictGuard, detect_conflicts
from .protocols import GraphReader, Retriever
from .service import (
    EvidenceNormalizer,
    HybridRetriever,
    RetrievalAmbiguityError,
    RetrievalConfigurationError,
    RetrievalError,
    RetrievalService,
    RetrieverService,
    ServiceRetriever,
)
from .types import (
    ChannelStats,
    ContextBundle,
    ContextConflict,
    Evidence,
    EvidenceChannel,
    RetrievalReceipt,
    RetrievalRequest,
)

__all__ = [
    "BudgetExceeded",
    "ChannelStats",
    "ConflictGuard",
    "ContextAssembler",
    "ContextBundle",
    "ContextConflict",
    "detect_conflicts",
    "DEFAULT_CHANNEL_QUOTAS",
    "DEFAULT_TOKEN_BUDGET",
    "Evidence",
    "EvidenceChannel",
    "EvidenceNormalizer",
    "GraphReader",
    "HybridRetriever",
    "RetrievalAmbiguityError",
    "RetrievalConfigurationError",
    "RetrievalError",
    "RetrievalService",
    "Retriever",
    "RetrieverService",
    "RetrievalReceipt",
    "RetrievalRequest",
    "ServiceRetriever",
    "estimate_tokens",
]
