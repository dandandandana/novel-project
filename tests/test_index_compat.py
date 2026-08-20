from pathlib import Path

import pytest

from novel_rag.cli import build_parser
from novel_rag.documents import RagDocument
from novel_rag.graph import GraphReadError
from novel_rag.index import SqliteIndex, rebuild_isolated_indexes, search_isolated


def _document(path: Path, *, status: str = "canon") -> RagDocument:
    path.write_text("source bytes", encoding="utf-8")
    return RagDocument(
        path,
        {
            "story_id": "demo",
            "timeline_id": "main",
            "document_type": "history",
            "title": "主线事件",
            "status": status,
            "version": "1.0",
        },
        {"content": "三叉戟在港口出现"},
    )


def test_compat_rebuild_promotes_canonical_graph_and_searches_through_retriever(tmp_path):
    document = _document(tmp_path / "history.yaml")
    with pytest.warns(DeprecationWarning):
        results = rebuild_isolated_indexes(tmp_path / "index", [document], ["demo"])

    assert (tmp_path / "index" / "shared.db").is_file()
    assert (tmp_path / "index" / "graphs" / "demo" / "main.db").is_file()
    assert results[-1].scope == "demo"
    with pytest.warns(DeprecationWarning):
        matches = search_isolated(
            tmp_path / "index", "三叉戟", "demo", "main", include_shared=False
        )
    assert [item.title for item in matches] == ["主线事件"]


def test_search_long_authority_document_is_not_limited_by_generation_budget(tmp_path):
    source = tmp_path / "long-canon.yaml"
    source.write_text("source bytes", encoding="utf-8")
    document = RagDocument(
        source,
        {
            "document_id": "long-canon-v1.0",
            "story_id": "demo",
            "timeline_id": "main",
            "document_type": "canon",
            "title": "长篇设定",
            "status": "canon",
            "version": "1.0",
        },
        {"content": "长篇设定 " * 2000},
    )
    with pytest.warns(DeprecationWarning):
        rebuild_isolated_indexes(tmp_path / "index", [document], ["demo"])

    with pytest.warns(DeprecationWarning):
        matches = search_isolated(
            tmp_path / "index",
            "长篇设定",
            "demo",
            "main",
            include_shared=False,
            limit=1,
        )
    assert [item.document_id for item in matches] == [document.document_id]


def test_missing_reader_does_not_create_database(tmp_path):
    target = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        SqliteIndex(target, _compat=True).search("query", "demo", "main")
    assert not target.exists()


def test_canonical_search_propagates_stale_source_error(tmp_path):
    source = tmp_path / "history.yaml"
    document = _document(source)
    with pytest.warns(DeprecationWarning):
        rebuild_isolated_indexes(tmp_path / "index", [document], ["demo"])
    source.write_text("edited source bytes", encoding="utf-8")

    with pytest.warns(DeprecationWarning), pytest.raises(GraphReadError, match="stale"):
        search_isolated(tmp_path / "index", "三叉戟", "demo", "main", include_shared=False)


def test_index_cli_accepts_graphkey_and_shared_selectors():
    parser = build_parser()
    selected = parser.parse_args(["index", "--story", "demo", "--timeline", "branch-a"])
    assert selected.story == "demo"
    assert selected.timeline == "branch-a"
    shared = parser.parse_args(["index", "--shared"])
    assert shared.shared is True
    legacy_search = parser.parse_args(["search", "query", "--story", "demo", "--timeline", "main", "--legacy"])
    assert legacy_search.legacy is True


def test_targeted_rebuild_does_not_prune_unrelated_graphkeys(tmp_path):
    index_root = tmp_path / "index"
    first = _document(tmp_path / "first.yaml")
    second = RagDocument(
        tmp_path / "second.yaml",
        {
            "document_id": "second-v1.0",
            "story_id": "other",
            "timeline_id": "main",
            "document_type": "history",
            "title": "另一作品",
            "status": "canon",
            "version": "1.0",
        },
        {"content": "另一作品内容"},
    )
    second.path.write_text("other source", encoding="utf-8")
    rebuild_isolated_indexes(index_root, [first, second], ["demo", "other"])
    unrelated = index_root / "graphs" / "other" / "main.db"
    assert unrelated.is_file()

    rebuild_isolated_indexes(
        index_root,
        [first],
        ["demo"],
        story_id="demo",
        timeline_id="main",
    )
    assert unrelated.is_file()

    rebuild_isolated_indexes(index_root, [], [], shared_only=True)
    assert unrelated.is_file()


def test_legacy_search_requires_an_explicit_switch(tmp_path):
    legacy = tmp_path / "index" / "stories" / "demo.db"
    document = _document(tmp_path / "legacy-source.yaml")
    document.body["content"] = "legacy-token"
    SqliteIndex(legacy, _compat=True).rebuild([document])
    with pytest.raises(GraphReadError, match="legacy=True"):
        search_isolated(tmp_path / "index", "legacy-token", "demo", "main", include_shared=False)
    with pytest.warns(DeprecationWarning):
        hits = search_isolated(
            tmp_path / "index",
            "legacy-token",
            "demo",
            "main",
            include_shared=False,
            legacy=True,
        )
    assert [item.document_id for item in hits] == [document.document_id]


def test_legacy_search_forces_legacy_db_when_canonical_graph_also_exists(tmp_path):
    index_root = tmp_path / "index"
    legacy_document = _document(tmp_path / "legacy-source.yaml")
    legacy_document.body["content"] = "legacy-only-token"
    SqliteIndex(index_root / "stories" / "demo.db", _compat=True).rebuild(
        [legacy_document]
    )

    canonical_document = _document(tmp_path / "canonical-source.yaml")
    canonical_document.body["content"] = "canonical-only-token"
    with pytest.warns(DeprecationWarning):
        rebuild_isolated_indexes(index_root, [canonical_document], ["demo"])

    with pytest.warns(DeprecationWarning):
        canonical_hits = search_isolated(
            index_root,
            "canonical-only-token",
            "demo",
            "main",
            include_shared=False,
        )
    with pytest.warns(DeprecationWarning):
        legacy_hits = search_isolated(
            index_root,
            "legacy-only-token",
            "demo",
            "main",
            include_shared=False,
            legacy=True,
        )

    assert [item.document_id for item in canonical_hits] == [canonical_document.document_id]
    assert [item.document_id for item in legacy_hits] == [legacy_document.document_id]


def test_legacy_search_rejects_canonical_shared_schema_with_actionable_hint(tmp_path):
    index_root = tmp_path / "index"
    legacy_document = _document(tmp_path / "legacy-source.yaml")
    legacy_document.body["content"] = "legacy-with-shared-token"
    SqliteIndex(index_root / "stories" / "demo.db", _compat=True).rebuild(
        [legacy_document]
    )

    canonical_document = _document(tmp_path / "canonical-source.yaml")
    canonical_document.body["content"] = "canonical-shared-token"
    with pytest.warns(DeprecationWarning):
        rebuild_isolated_indexes(index_root, [canonical_document], ["demo"])

    with pytest.warns(DeprecationWarning), pytest.raises(
        GraphReadError, match=r"--legacy --no-shared|canonical GraphKey"
    ) as failure:
        search_isolated(
            index_root,
            "legacy-with-shared-token",
            "demo",
            "main",
            legacy=True,
        )

    assert "no such table" not in str(failure.value).lower()
