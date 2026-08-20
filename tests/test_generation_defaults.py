from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from novel_rag.generation import (
    GenerationError,
    LegacyRetrieverAdapter,
    build_default_retriever,
    build_legacy_retriever,
    set_default_retriever_factory,
)
from novel_rag.identity import GraphKey
from novel_rag.retrieval import ContextBundle, RetrievalRequest


class StubRetriever:
    def retrieve(self, _request):
        return ContextBundle()


def test_default_retriever_is_lazy_composition_factory(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, Path] = {}
    module = types.ModuleType("novel_rag.composition")

    def build_graph_retriever(library_root: Path, key: GraphKey, *, index_directory: Path):
        seen.update(library_root=library_root, key=key, index_directory=index_directory)
        return StubRetriever()

    module.build_graph_retriever = build_graph_retriever
    monkeypatch.setitem(sys.modules, "novel_rag.composition", module)
    set_default_retriever_factory(None)

    library = tmp_path / "library"
    index = library / "index"
    provider = build_default_retriever(library, index)
    assert isinstance(
        provider.retrieve(RetrievalRequest(GraphKey("story", "main"), "")),
        ContextBundle,
    )
    assert seen == {
        "library_root": library,
        "key": GraphKey("story", "main"),
        "index_directory": index,
    }


def test_legacy_adapter_requires_explicit_selection(tmp_path: Path) -> None:
    set_default_retriever_factory(lambda library, index: LegacyRetrieverAdapter(library, index))
    try:
        assert isinstance(
            build_default_retriever(tmp_path / "library", tmp_path / "index"),
            LegacyRetrieverAdapter,
        )
    finally:
        set_default_retriever_factory(None)


def test_build_legacy_retriever_is_an_explicit_cli_boundary(tmp_path: Path) -> None:
    library = tmp_path / "library"
    index = library / "index"
    adapter = build_legacy_retriever(library, index)
    assert isinstance(adapter, LegacyRetrieverAdapter)
    assert adapter.library_root == library.resolve()
    assert adapter.index_root == index.resolve()


def test_missing_composition_is_explicit(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "novel_rag.composition", None)
    set_default_retriever_factory(None)

    with pytest.raises(GenerationError, match="显式注入 LegacyRetrieverAdapter"):
        build_default_retriever(tmp_path / "library", tmp_path / "index")
