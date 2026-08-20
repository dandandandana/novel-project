from pathlib import Path

import pytest

from novel_rag.catalog import (
    CatalogValidationError,
    CorpusValidationError,
    LayoutMappingError,
    LegacyLayoutMapper,
    TimelineRegistry,
    ValidatedCorpus,
    fingerprint_documents,
    resolve_divergence_snapshot,
)
from novel_rag.documents import RagDocument
from novel_rag.identity import GraphKey, IdentityError, StoryCoordinate


def _timeline_registry() -> dict:
    return {
        "timelines": [
            {
                "story_id": "demo",
                "timeline_id": "main",
                "parent_timeline_id": None,
                "status": "active",
            },
            {
                "story_id": "demo",
                "timeline_id": "branch-a",
                "parent_timeline_id": "main",
                "divergence_at": "volume-04/chapter-24/scene-03",
                "divergence_snapshot": "snapshots/branch-a.yaml",
                "status": "active",
            },
            {
                "story_id": "demo",
                "timeline_id": "branch-b",
                "parent_timeline_id": "branch-a",
                "divergence_at": "volume-05/chapter-01/scene-01",
                "divergence_snapshot": "snapshots/branch-b.yaml",
                "status": "active",
            },
        ]
    }


def _document(path: Path, *, title: str, timeline_id: str = "main") -> RagDocument:
    return RagDocument(
        path,
        {
            "document_id": f"history-{title}",
            "story_id": "demo",
            "timeline_id": timeline_id,
            "document_type": "history",
            "title": title,
            "status": "canon",
            "version": "1.0",
        },
        {"content": title},
    )


def test_graph_key_validates_ids_and_builds_graph_path_without_creating_it(tmp_path: Path):
    key = GraphKey("demo", "branch-a")
    assert key.graph_path(tmp_path) == tmp_path / "graphs" / "demo" / "branch-a.db"
    assert not (tmp_path / "graphs").exists()
    assert GraphKey.shared().graph_path(tmp_path) == tmp_path / "shared.db"

    for story_id, timeline_id in [("../demo", "main"), ("Demo", "main"), ("demo", "a/b")]:
        with pytest.raises(IdentityError):
            GraphKey(story_id, timeline_id)
    with pytest.raises(IdentityError):
        GraphKey("__shared__", "main")


def test_story_coordinate_is_comparable_and_accepts_registry_shapes():
    before = StoryCoordinate.from_value("volume-04/chapter-24/scene-03")
    after = StoryCoordinate.from_value({"volume": 4, "chapter": 25, "scene": 1})
    assert before < after
    assert before.as_path() == "volume-4/chapter-24/scene-3"
    assert before.as_path(padded=True) == "volume-04/chapter-024/scene-003"
    assert StoryCoordinate.from_value((4, 24, 3)) == before
    assert StoryCoordinate.from_value("volume-04-chapter-024-scene-003") == before
    assert StoryCoordinate.from_metadata({"volume": 4, "chapter": 24, "scene": 3}) == before
    assert StoryCoordinate.from_metadata({"title": "no coordinate"}) is None
    with pytest.raises(IdentityError):
        StoryCoordinate.from_value("../../etc/passwd")


def test_timeline_registry_returns_lineage_and_segment_cutoffs():
    registry = TimelineRegistry.from_mapping(_timeline_registry(), expected_story_id="demo")
    assert registry.allowed_timeline_ids("branch-b") == ("main", "branch-a", "branch-b")
    assert registry.lineage("branch-b")[0].timeline_id == "main"
    cutoffs = registry.cutoffs("branch-b")
    assert cutoffs["main"] == StoryCoordinate(4, 24, 3)
    assert cutoffs["branch-a"] == StoryCoordinate(5, 1, 1)
    assert cutoffs["branch-b"] is None


def test_timeline_registry_resolves_and_validates_snapshot_yaml(tmp_path: Path):
    snapshot_root = tmp_path / "snapshots"
    snapshot_root.mkdir()
    (snapshot_root / "branch-a.yaml").write_text("state:\n  scene: 3\n", encoding="utf-8")
    (snapshot_root / "branch-b.yaml").write_text("state:\n  scene: 1\n", encoding="utf-8")

    registry = TimelineRegistry.from_mapping(
        _timeline_registry(),
        expected_story_id="demo",
        root=tmp_path,
    )
    entry = registry.get("branch-a")
    assert entry.snapshot_path(tmp_path) == snapshot_root / "branch-a.yaml"
    assert resolve_divergence_snapshot("snapshots/branch-b.yaml", tmp_path) == (
        snapshot_root / "branch-b.yaml"
    )

    registry_path = tmp_path / "timelines.yaml"
    registry_path.write_text(
        "timelines:\n"
        "- story_id: demo\n"
        "  timeline_id: main\n"
        "- story_id: demo\n"
        "  timeline_id: branch-a\n"
        "  parent_timeline_id: main\n"
        "  divergence_at: volume-04/chapter-24/scene-03\n"
        "  divergence_snapshot: snapshots/branch-a.yaml\n",
        encoding="utf-8",
    )
    loaded = TimelineRegistry.from_path(
        registry_path,
        expected_story_id="demo",
        snapshot_root=tmp_path,
    )
    assert loaded.get("branch-a").snapshot_path(tmp_path) == snapshot_root / "branch-a.yaml"


@pytest.mark.parametrize(
    "snapshot_contents,needle",
    [(None, "不存在"), ("broken: [", "YAML"), ("[]", "YAML 根节点")],
)
def test_timeline_registry_rejects_missing_or_invalid_snapshot_yaml(
    tmp_path: Path,
    snapshot_contents: str | None,
    needle: str,
):
    snapshot_root = tmp_path / "snapshots"
    snapshot_root.mkdir()
    if snapshot_contents is not None:
        (snapshot_root / "branch-a.yaml").write_text(snapshot_contents, encoding="utf-8")
    (snapshot_root / "branch-b.yaml").write_text("state: {}\n", encoding="utf-8")

    with pytest.raises(CatalogValidationError, match=needle):
        TimelineRegistry.from_mapping(
            _timeline_registry(),
            expected_story_id="demo",
            snapshot_root=tmp_path,
        )


def test_validated_corpus_for_graph_applies_scene_cutoff_to_ancestor_documents(tmp_path: Path):
    registry = TimelineRegistry.from_mapping(_timeline_registry(), expected_story_id="demo")
    before = _document(tmp_path / "before.yaml", title="before")
    before.metadata.update({"volume": 4, "chapter": 24, "scene": 2})
    after = _document(tmp_path / "after.yaml", title="after")
    after.metadata.update({"volume": 4, "chapter": 24, "scene": 4})
    branch = _document(tmp_path / "branch.yaml", title="branch", timeline_id="branch-a")
    branch.metadata.update({"volume": 4, "chapter": 24, "scene": 4})
    corpus = ValidatedCorpus.from_documents(
        [before, after, branch],
        root=tmp_path,
        timeline_registry=registry,
    )

    scoped = corpus.for_graph(GraphKey("demo", "branch-a"))
    assert scoped.document_ids == ("history-before", "history-branch")


def test_nested_lineage_applies_each_cutoff_and_keeps_common_and_target_without_coordinates(
    tmp_path: Path,
):
    registry = TimelineRegistry.from_mapping(_timeline_registry(), expected_story_id="demo")
    root_before = _document(tmp_path / "root-before.yaml", title="root-before")
    root_before.metadata.update({"volume": 4, "chapter": 24, "scene": 2})
    root_after = _document(tmp_path / "root-after.yaml", title="root-after")
    root_after.metadata.update({"volume": 4, "chapter": 24, "scene": 4})
    branch_before = _document(
        tmp_path / "branch-before.yaml",
        title="branch-before",
        timeline_id="branch-a",
    )
    branch_before.metadata.update({"volume": 5, "chapter": 1, "scene": 1})
    branch_target = _document(
        tmp_path / "branch-target.yaml",
        title="branch-target",
        timeline_id="branch-b",
    )
    common = _document(tmp_path / "common.yaml", title="common", timeline_id="common")
    corpus = ValidatedCorpus.from_documents(
        [root_before, root_after, branch_before, branch_target, common],
        root=tmp_path,
        timeline_registry=registry,
    )

    scoped = corpus.for_graph(GraphKey("demo", "branch-b"))
    assert scoped.document_ids == (
        "history-root-before",
        "history-branch-before",
        "history-branch-target",
        "history-common",
    )


def test_ancestor_without_complete_coordinate_is_a_diagnostic_error_but_common_and_target_are_exempt(
    tmp_path: Path,
):
    registry = TimelineRegistry.from_mapping(_timeline_registry(), expected_story_id="demo")
    ancestor = _document(tmp_path / "ancestor.yaml", title="ancestor")
    common = _document(tmp_path / "common.yaml", title="common", timeline_id="common")
    target = _document(
        tmp_path / "target.yaml",
        title="target",
        timeline_id="branch-a",
    )
    corpus = ValidatedCorpus.from_documents(
        [ancestor, common, target],
        root=tmp_path,
        timeline_registry=registry,
    )

    with pytest.raises(CorpusValidationError, match="祖先 timeline 文档缺少"):
        corpus.for_graph(GraphKey("demo", "branch-a"))


@pytest.mark.parametrize(
    "row,needle",
    [
        ({"story_id": "demo", "timeline_id": "child", "parent_timeline_id": "missing", "divergence_at": "volume-1/chapter-1/scene-1", "divergence_snapshot": "s.yaml"}, "parent_timeline_id 不存在"),
        ({"story_id": "demo", "timeline_id": "child", "parent_timeline_id": "main", "divergence_at": "volume-1/chapter-1/scene-1"}, "必须设置 divergence_snapshot"),
        ({"story_id": "demo", "timeline_id": "child", "parent_timeline_id": "main", "divergence_at": "volume-1/chapter-1/scene-1", "divergence_snapshot": "../escape.yaml"}, "路径穿越"),
        ({"story_id": "demo", "timeline_id": "main", "divergence_at": "volume-1/chapter-1/scene-1"}, "根 timeline 不得设置 divergence_at"),
    ],
)
def test_timeline_registry_rejects_invalid_lineage(row, needle):
    with pytest.raises(CatalogValidationError, match=needle):
        TimelineRegistry.from_mapping({"timelines": [{"story_id": "demo", "timeline_id": "main"}, row]}, expected_story_id="demo")


def test_legacy_layout_maps_common_and_main_timeline_without_moving_files(tmp_path: Path):
    mapper = LegacyLayoutMapper(tmp_path)
    canon = mapper.normalize_path(tmp_path / "stories/demo/canon/hero.yaml")
    assert canon.scope == "common"
    assert canon.timeline_id is None
    assert canon.graph_key is None
    assert canon.target_path == tmp_path / "stories/demo/common/canon/hero.yaml"
    assert canon.legacy is True

    history = mapper.normalize_path(tmp_path / "stories/demo/history/volume-01/chapter-01/scene-01.yaml")
    assert history.scope == "timeline"
    assert history.timeline_id == "main"
    assert history.graph_key == GraphKey("demo", "main")
    assert history.target_path == tmp_path / "stories/demo/timelines/main/history/volume-01/chapter-01/scene-01.yaml"

    branch_canon = mapper.normalize_path(
        tmp_path / "stories/demo/canon/branch-rule.yaml",
        metadata={"story_id": "demo", "timeline_id": "branch-a"},
    )
    assert branch_canon.timeline_id == "branch-a"
    assert branch_canon.target_path == tmp_path / "stories/demo/timelines/branch-a/canon/branch-rule.yaml"

    canonical = mapper.normalize_path(tmp_path / "stories/demo/timelines/branch-a/history/scene.yaml")
    assert canonical.target_path == canonical.source_path
    assert canonical.legacy is False

    shared = mapper.normalize_path(tmp_path / "shared/ruler.yaml")
    assert shared.graph_key == GraphKey.shared()
    with pytest.raises(LayoutMappingError, match="shared"):
        mapper.normalize_path(
            tmp_path / "shared/ruler.yaml",
            metadata={"story_id": "demo", "timeline_id": "main"},
        )


def test_legacy_layout_rejects_outside_and_metadata_identity_mismatch(tmp_path: Path):
    mapper = LegacyLayoutMapper(tmp_path)
    with pytest.raises(LayoutMappingError):
        mapper.normalize_path(tmp_path.parent / "outside.yaml")
    with pytest.raises(LayoutMappingError, match="story_id"):
        mapper.normalize_path(
            tmp_path / "stories/demo/history/scene.yaml",
            metadata={"story_id": "other"},
        )


def test_validated_corpus_adapts_rag_documents_and_fingerprints_exact_sources(tmp_path: Path):
    first_path = tmp_path / "a.yaml"
    second_path = tmp_path / "b.yaml"
    first_path.write_text("metadata:\n  title: A\n", encoding="utf-8")
    second_path.write_text("metadata:\n  title: B\n", encoding="utf-8")
    one = _document(first_path, title="one")
    two = _document(second_path, title="two")

    corpus = ValidatedCorpus.from_documents([one, two], source_root=tmp_path)
    assert corpus.document_ids == ("history-one", "history-two")
    assert corpus.source_root == tmp_path
    assert corpus.module_references == ()
    assert corpus.source_fingerprint == fingerprint_documents([two, one], root=tmp_path)

    before = corpus.source_fingerprint
    second_path.write_text("changed source", encoding="utf-8")
    assert corpus.source_fingerprint != before

    with pytest.raises(CatalogValidationError, match="document_id 重复"):
        ValidatedCorpus.from_documents([one, one], root=tmp_path)
