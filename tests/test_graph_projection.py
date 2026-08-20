from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from novel_rag.documents import RagDocument
from novel_rag.graph import (
    GRAPH_TABLES,
    SHARED_TABLES,
    GraphBuildError,
    GraphManifest,
    GraphKey,
    GraphReader,
    GraphReadError,
    ModuleGraphIndex,
    SharedBuilder,
    SharedReader,
    ValidatedCorpus,
    build_graph,
    build_shared,
    probe_trigram,
)
import novel_rag.graph.builder as graph_builder
import novel_rag.graph.shared as shared_graph
from novel_rag.catalog import TimelineRegistry


def _document(
    root: Path,
    document_id: str,
    *,
    story_id: str = "story",
    timeline_id: str = "main",
    document_type: str = "canon",
    text: str = "中文检索能力",
    module_type: str | None = None,
) -> RagDocument:
    path = root / f"{document_id}.yaml"
    path.write_text(text, encoding="utf-8")
    metadata = {
        "document_id": document_id,
        "story_id": story_id,
        "timeline_id": timeline_id,
        "document_type": document_type,
        "status": "active" if document_type == "rule" else "canon",
        "version": "1.0",
        "title": document_id,
    }
    if module_type:
        metadata["module_type"] = module_type
    return RagDocument(path, metadata, {"text": text})


def test_graph_builds_manifest_schema_and_read_only_reader(tmp_path: Path) -> None:
    document = _document(tmp_path, "d1", text="中文检索能力和明确来源")
    corpus = ValidatedCorpus.from_documents([document], source_root=tmp_path)

    result = build_graph(GraphKey("story", "main"), corpus, tmp_path / "index")
    expected = tmp_path / "index" / "graphs" / "story" / "main.db"
    assert result.path == expected
    assert result.promoted is True
    assert result.manifest.source_fingerprint.startswith("sha256:")
    assert result.manifest.document_count == 1

    with sqlite3.connect(f"file:{expected.as_posix()}?mode=ro", uri=True) as connection:
        names = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type in ('table', 'view')"
            )
        }
        assert GRAPH_TABLES <= names

    with GraphReader(expected, expected_key=GraphKey("story", "main")) as reader:
        assert reader.manifest().story_id == "story"
        assert [hit.document_id for hit in reader.search("中文检")]
        with pytest.raises(sqlite3.OperationalError):
            reader._connection.execute("create table should_not_write(value text)")


def test_reader_missing_graph_does_not_create_parent_or_database(tmp_path: Path) -> None:
    path = tmp_path / "index" / "graphs" / "story" / "main.db"
    assert not path.parent.exists()
    with pytest.raises(GraphReadError):
        GraphReader(path)
    assert not path.exists()
    assert not path.parent.exists()


def test_manifest_identity_and_source_fingerprint_reject_stale_graph(tmp_path: Path) -> None:
    document = _document(tmp_path, "d1", text="first source")
    corpus = ValidatedCorpus.from_documents([document], source_root=tmp_path)
    result = build_graph(GraphKey("story", "main"), corpus, tmp_path / "index")

    with pytest.raises(GraphReadError):
        GraphReader(result.path, expected_key=GraphKey("story", "branch"))

    document.path.write_text("changed source", encoding="utf-8")
    with pytest.raises(GraphReadError, match="stale"):
        GraphReader(result.path)


def test_identity_failure_keeps_previous_promoted_graph(tmp_path: Path) -> None:
    good = _document(tmp_path, "d1")
    target = tmp_path / "index"
    build_graph(
        GraphKey("story", "main"),
        ValidatedCorpus.from_documents([good], source_root=tmp_path),
        target,
    )
    bad = _document(tmp_path, "bad", story_id="other")
    with pytest.raises(GraphBuildError):
        build_graph(
            GraphKey("story", "main"),
            ValidatedCorpus.from_documents([bad], source_root=tmp_path),
            target,
        )
    with GraphReader(target / "graphs" / "story" / "main.db") as reader:
        assert reader.manifest().document_count == 1
        assert reader.manifest().story_id == "story"


def test_promotion_failure_keeps_accepted_staged_file(tmp_path: Path, monkeypatch) -> None:
    document = _document(tmp_path, "d1")
    staged: list[Path] = []

    def fail_replace(source, _target):
        staged.append(Path(source))
        raise PermissionError("locked")

    monkeypatch.setattr(graph_builder.os, "replace", fail_replace)
    with pytest.raises(GraphBuildError, match="图构建失败"):
        build_graph(
            GraphKey("story", "main"),
            ValidatedCorpus.from_documents([document], source_root=tmp_path),
            tmp_path / "index",
        )
    assert staged and staged[0].is_file()
    staged[0].unlink()


def test_graph_promotion_failure_preserves_old_graph_on_windows_lock(
    tmp_path: Path, monkeypatch
) -> None:
    old = _document(tmp_path, "old", text="old graph")
    target = tmp_path / "index"
    old_result = build_graph(
        GraphKey("story", "main"),
        ValidatedCorpus.from_documents([old], source_root=tmp_path),
        target,
    )
    newer = _document(tmp_path, "new", text="new graph")
    staged: list[Path] = []

    def fail_replace(source, _target):
        staged.append(Path(source))
        raise PermissionError("locked")

    monkeypatch.setattr(graph_builder.os, "replace", fail_replace)
    with pytest.raises(GraphBuildError, match="图构建失败"):
        build_graph(
            GraphKey("story", "main"),
            ValidatedCorpus.from_documents([newer], source_root=tmp_path),
            target,
        )
    assert staged and staged[0].is_file()
    with GraphReader(old_result.path) as reader:
        assert reader.manifest().source_fingerprint == old_result.manifest.source_fingerprint
        assert reader.search("old graph")[0].document_id == "old"
    staged[0].unlink()


def test_shared_builder_writes_manifest_and_module_references(tmp_path: Path) -> None:
    document = _document(
        tmp_path,
        "rule-1",
        story_id="__shared__",
        timeline_id="global",
        document_type="rule",
        text="global system rule",
        module_type="ruler",
    )
    document.metadata.update({"priority": 1, "enforcement": "must"})
    corpus = ValidatedCorpus.from_documents([document], source_root=tmp_path)
    result = build_shared(corpus, tmp_path / "index")
    expected = tmp_path / "index" / "shared.db"
    assert result.path == expected
    with sqlite3.connect(f"file:{expected.as_posix()}?mode=ro", uri=True) as connection:
        names = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type in ('table', 'view')"
            )
        }
        assert SHARED_TABLES <= names
    with SharedReader(expected) as reader:
        assert reader.manifest().module_reference_count == 1
        refs = reader.module_references()
        assert refs[0].document_id == "rule-1"
        assert refs[0].module_type == "ruler"
        assert reader.search("global system rule")[0].document_id == "rule-1"


def test_trigram_probe_is_an_actual_working_feature_probe() -> None:
    assert probe_trigram() is True


def test_builder_requires_canonical_corpus_and_canonical_target(tmp_path: Path) -> None:
    document = _document(tmp_path, "d1")
    corpus = ValidatedCorpus.from_documents([document], source_root=tmp_path)

    with pytest.raises(GraphBuildError, match="ValidatedCorpus"):
        build_graph(GraphKey("story", "main"), [document], tmp_path / "index")
    with pytest.raises(ValueError, match="canonical"):
        graph_builder.GraphBuilder(
            GraphKey("story", "main"),
            corpus,
            tmp_path / "wrong.db",
        )


def test_builder_applies_lineage_cutoff_and_rejects_sibling_documents(tmp_path: Path) -> None:
    registry = TimelineRegistry.from_mapping(
        {
            "timelines": [
                {"story_id": "story", "timeline_id": "main"},
                {
                    "story_id": "story",
                    "timeline_id": "branch",
                    "parent_timeline_id": "main",
                    "divergence_at": "volume-04/chapter-24/scene-03",
                    "divergence_snapshot": "snapshots/branch.yaml",
                },
                {
                    "story_id": "story",
                    "timeline_id": "sibling",
                    "parent_timeline_id": "main",
                    "divergence_at": "volume-04/chapter-24/scene-04",
                    "divergence_snapshot": "snapshots/sibling.yaml",
                },
            ]
        },
        expected_story_id="story",
    )

    def document(document_id: str, timeline_id: str, scene: int) -> RagDocument:
        value = _document(
            tmp_path,
            document_id,
            timeline_id=timeline_id,
            text=document_id,
        )
        value.metadata.update({"volume": 4, "chapter": 24, "scene": scene})
        return value

    key = GraphKey("story", "branch")
    corpus = ValidatedCorpus.from_documents(
        [
            document("before", "main", 2),
            document("after", "main", 4),
            document("branch-doc", "branch", 4),
            document("sibling-doc", "sibling", 4),
        ],
        source_root=tmp_path,
        graph_key=key,
        timeline_registry=registry,
        strict=False,
    )
    with pytest.raises(GraphBuildError, match="lineage"):
        build_graph(key, corpus, tmp_path / "index")

    scoped = ValidatedCorpus.from_documents(
        [
            document("before", "main", 2),
            document("after", "main", 4),
            document("branch-doc", "branch", 4),
        ],
        source_root=tmp_path,
        graph_key=key,
        timeline_registry=registry,
    )
    result = build_graph(key, scoped, tmp_path / "scoped-index")
    with GraphReader(result.path) as reader:
        assert reader.search("before")[0].document_id == "before"
        assert reader.search("branch-doc")[0].document_id == "branch-doc"
        assert reader.search("after") == []


@pytest.mark.parametrize(
    ("coordinate_metadata", "message"),
    (
        ({}, "缺少可完整解析"),
        ({"volume": "not-a-volume"}, "坐标无效"),
        ({"volume": 1, "chapter": 2}, "必须精确到 scene"),
    ),
)
def test_direct_builder_rejects_invalid_ancestor_coordinates(
    tmp_path: Path,
    coordinate_metadata: dict[str, object],
    message: str,
) -> None:
    registry = TimelineRegistry.from_mapping(
        {
            "timelines": [
                {"story_id": "story", "timeline_id": "main"},
                {
                    "story_id": "story",
                    "timeline_id": "branch",
                    "parent_timeline_id": "main",
                    "divergence_at": "volume-01/chapter-02/scene-03",
                    "divergence_snapshot": "snapshots/branch.yaml",
                },
            ]
        },
        expected_story_id="story",
    )
    ancestor = _document(tmp_path, "ancestor", timeline_id="main", text="ancestor")
    ancestor.metadata.update(coordinate_metadata)
    corpus = ValidatedCorpus.from_documents(
        [ancestor],
        source_root=tmp_path,
        graph_key=GraphKey("story", "branch"),
        timeline_registry=registry,
        strict=False,
    )

    with pytest.raises(GraphBuildError, match=message):
        graph_builder.GraphBuilder(
            GraphKey("story", "branch"),
            corpus,
            tmp_path / "index",
        ).build()


def test_reader_requires_current_scoped_fingerprint_and_manifest_identity(tmp_path: Path) -> None:
    document = _document(tmp_path, "d1", text="original")
    corpus = ValidatedCorpus.from_documents([document], source_root=tmp_path)
    result = build_graph(GraphKey("story", "main"), corpus, tmp_path / "index")

    with GraphReader(
        result.path,
        expected_key=GraphKey("story", "main"),
        expected_fingerprint=result.manifest.source_fingerprint,
    ) as reader:
        assert reader.manifest().source_fingerprint == result.manifest.source_fingerprint

    document.path.write_text("changed", encoding="utf-8")
    with pytest.raises(GraphReadError, match="stale"):
        GraphReader(
            result.path,
            expected_key=GraphKey("story", "main"),
            expected_fingerprint=result.manifest.source_fingerprint,
        )


def test_graph_regression_failure_keeps_previous_promoted_graph(tmp_path: Path) -> None:
    old = _document(tmp_path, "old", text="old source")
    target = tmp_path / "index"
    build_graph(
        GraphKey("story", "main"),
        ValidatedCorpus.from_documents([old], source_root=tmp_path),
        target,
    )
    new = _document(tmp_path, "new", text="new source")
    with pytest.raises(GraphBuildError, match="regression failure"):
        graph_builder.GraphBuilder(
            GraphKey("story", "main"),
            ValidatedCorpus.from_documents([new], source_root=tmp_path),
            target,
            retrieval_regression=lambda _reader: (_ for _ in ()).throw(
                RuntimeError("regression failure")
            ),
        ).build()
    with GraphReader(target / "graphs" / "story" / "main.db") as reader:
        assert reader.manifest().document_count == 1
        assert reader.manifest().source_fingerprint == (
            build_graph(
                GraphKey("story", "main"),
                ValidatedCorpus.from_documents([old], source_root=tmp_path),
                tmp_path / "old-index",
            ).manifest.source_fingerprint
        )


def test_shared_reader_stale_and_shared_promotion_failure_keep_old_graph(
    tmp_path: Path, monkeypatch
) -> None:
    old = _document(
        tmp_path,
        "rule-old",
        story_id="__shared__",
        timeline_id="global",
        document_type="rule",
        text="old shared rule",
        module_type="ruler",
    )
    old.metadata.update({"priority": 1, "enforcement": "must"})
    target = tmp_path / "index"
    old_result = build_shared(
        ValidatedCorpus.from_documents([old], source_root=tmp_path),
        target,
    )
    with SharedReader(target / "shared.db") as reader:
        assert reader.manifest().source_fingerprint == old_result.manifest.source_fingerprint

    old.path.write_text("changed shared rule", encoding="utf-8")
    with pytest.raises(GraphReadError, match="stale"):
        SharedReader(target / "shared.db")
    old.path.write_text("old shared rule", encoding="utf-8")

    staged: list[Path] = []

    def fail_replace(source, _target):
        staged.append(Path(source))
        raise PermissionError("locked")

    monkeypatch.setattr(shared_graph.os, "replace", fail_replace)
    newer = _document(
        tmp_path,
        "rule-new",
        story_id="__shared__",
        timeline_id="global",
        document_type="rule",
        text="new shared rule",
        module_type="ruler",
    )
    newer.metadata.update({"priority": 1, "enforcement": "must"})
    with pytest.raises(GraphBuildError, match="shared 图构建失败"):
        build_shared(
            ValidatedCorpus.from_documents([newer], source_root=tmp_path),
            target,
        )
    assert staged and staged[0].is_file()
    with SharedReader(target / "shared.db") as reader:
        assert reader.manifest().source_fingerprint == old_result.manifest.source_fingerprint
    staged[0].unlink()


def test_module_graph_index_and_shared_reverse_dependency_api(tmp_path: Path) -> None:
    shared_doc = _document(
        tmp_path,
        "rule-1",
        story_id="__shared__",
        timeline_id="global",
        document_type="rule",
        text="shared rule",
        module_type="ruler",
    )
    shared_doc.metadata.update({"priority": 1, "enforcement": "must"})
    shared_result = build_shared(
        ValidatedCorpus.from_documents([shared_doc], source_root=tmp_path),
        tmp_path / "index",
    )
    manifest = GraphManifest(
        schema_version="graph-v1",
        story_id="story",
        timeline_id="main",
        source_fingerprint="sha256:story",
        shared_manifest_fingerprint=shared_result.manifest.source_fingerprint,
        module_references=(
            {"module_type": "ruler", "document_id": "rule-1", "version": "1"},
        ),
        built_at="now",
        document_count=0,
        entity_count=0,
        relation_count=0,
    )
    index = ModuleGraphIndex.from_manifests([manifest])
    assert index.graph_keys_for_module("ruler", "rule-1") == (GraphKey("story", "main"),)
    assert index.as_dict()["ruler:rule-1"] == [{"story_id": "story", "timeline_id": "main"}]
    with SharedReader(shared_result.path) as reader:
        assert reader.dependent_graph_keys([manifest]) == (GraphKey("story", "main"),)
