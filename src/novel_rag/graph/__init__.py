"""Authority-first graph projection primitives.

This package owns only the derived SQLite graph boundary.  Application
composition wires its readers and builders to the catalog and retrieval
contracts; canonical CLI/TUI paths do not need to know the SQLite schema.
The legacy ``novel_rag.index`` façade remains an explicit migration
compatibility surface and is not a canonical read path.
"""

from .builder import GraphBuilder, build_graph, graph_path
from .fingerprint import (
    compute_source_fingerprint,
    corpus_fingerprint,
    fingerprint_documents,
    graph_corpus_fingerprint,
)
from .reader import GraphReader, open_read_only, read_only_uri
from .schema import (
    GRAPH_TABLES,
    SHARED_TABLES,
    SCHEMA_VERSION,
    SHARED_SCHEMA_VERSION,
    TrigramProbe,
    probe_trigram,
    require_trigram,
    verify_integrity,
)
from .shared import SharedBuilder, SharedReader, build_shared, shared_path
from .types import (
    DocumentHit,
    EntityResolution,
    GraphBuildError,
    GraphBuildResult,
    GraphError,
    GraphKey,
    GraphManifest,
    GraphReadError,
    build_module_graph_index,
    ModuleReference,
    ModuleGraphIndex,
    RelationHit,
    SharedManifest,
    SharedModuleHit,
    ValidatedCorpus,
)

__all__ = [
    "DocumentHit",
    "EntityResolution",
    "GraphBuildError",
    "GraphBuildResult",
    "GraphBuilder",
    "GraphError",
    "GraphKey",
    "GraphManifest",
    "GraphReadError",
    "GraphReader",
    "build_module_graph_index",
    "GRAPH_TABLES",
    "ModuleReference",
    "ModuleGraphIndex",
    "RelationHit",
    "SCHEMA_VERSION",
    "SHARED_SCHEMA_VERSION",
    "SHARED_TABLES",
    "SharedBuilder",
    "SharedManifest",
    "SharedModuleHit",
    "SharedReader",
    "TrigramProbe",
    "ValidatedCorpus",
    "build_graph",
    "build_shared",
    "compute_source_fingerprint",
    "corpus_fingerprint",
    "fingerprint_documents",
    "graph_corpus_fingerprint",
    "graph_path",
    "open_read_only",
    "probe_trigram",
    "read_only_uri",
    "require_trigram",
    "verify_integrity",
    "shared_path",
]
