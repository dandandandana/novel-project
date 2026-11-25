from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from novel_rag.documents import DocumentError
from novel_rag.identity import GraphKey, StoryCoordinate
from novel_rag.service import load_story_sources
from writer_fixtures import make_library, put_document, write_yaml


def test_before_and_after_cursor_bound_the_same_coordinate(tmp_path: Path) -> None:
    """依赖：load_story_sources 与共享临时库。输入：游标前、同位和 common 来源。输出：before/after 可见集合。实现：比较指定坐标边界并保留 common canon。"""

    root = make_library(tmp_path)
    put_document(root, "earlier", "earlier text", volume=1, chapter=2, scene=2)
    put_document(root, "at-cursor", "cursor text", volume=1, chapter=2, scene=3)
    put_document(
        root,
        "common-rule",
        "stable rule",
        category="canon",
        volume=1,
        chapter=1,
        scene=1,
    )
    cursor = StoryCoordinate(1, 2, 3)
    scope = GraphKey("demo", "main")

    before = load_story_sources(root, scope, coordinate=cursor, endpoint="before")
    after = load_story_sources(root, scope, coordinate=cursor, endpoint="after")

    assert {item.document_id for item in before.documents} == {"earlier", "common-rule"}
    assert {item.document_id for item in after.documents} == {
        "earlier",
        "at-cursor",
        "common-rule",
    }
    for corpus in (before, after):
        for document_id, reference in corpus.source_refs.items():
            assert reference.source_hash == corpus.snapshots[document_id].source_hash


def test_story_lineage_filters_sibling_story_and_parent_after_divergence(
    tmp_path: Path,
) -> None:
    """依赖：真实 timeline registry 与 divergence_snapshot。输入：两作品、父线及两条兄弟线。输出：目标线的可见原文。实现：验证 lineage、分歧 cutoff 和 common Canon。"""

    root = make_library(tmp_path)
    story_root = root / "stories" / "demo"
    divergence = "volume-1/chapter-2/scene-3"
    for branch in ("branch-a", "branch-b"):
        write_yaml(story_root / "snapshots" / f"{branch}.yaml", {"state": branch})
    write_yaml(
        story_root / "common" / "registry" / "timelines.yaml",
        {
            "timelines": [
                {
                    "story_id": "demo",
                    "timeline_id": "main",
                    "parent_timeline_id": None,
                    "divergence_at": None,
                    "divergence_snapshot": None,
                },
                {
                    "story_id": "demo",
                    "timeline_id": "branch-a",
                    "parent_timeline_id": "main",
                    "divergence_at": divergence,
                    "divergence_snapshot": "snapshots/branch-a.yaml",
                },
                {
                    "story_id": "demo",
                    "timeline_id": "branch-b",
                    "parent_timeline_id": "main",
                    "divergence_at": divergence,
                    "divergence_snapshot": "snapshots/branch-b.yaml",
                },
            ]
        },
    )
    put_document(root, "parent-before", "parent before", chapter=2, scene=2)
    put_document(root, "parent-at-cutoff", "parent cutoff", chapter=2, scene=3)
    put_document(root, "parent-after-cutoff", "parent after", chapter=2, scene=4)
    put_document(
        root,
        "branch-a-only",
        "branch a text",
        timeline="branch-a",
        chapter=2,
        scene=4,
    )
    put_document(
        root,
        "branch-b-only",
        "branch b text",
        timeline="branch-b",
        chapter=2,
        scene=4,
    )
    put_document(root, "other-story-only", "other story text", story="other")
    put_document(root, "common-rule", "stable rule", category="canon")

    main = load_story_sources(root, GraphKey("demo", "main"))
    branch_a = load_story_sources(root, GraphKey("demo", "branch-a"))

    assert {item.document_id for item in branch_a.documents} == {
        "parent-before",
        "parent-at-cutoff",
        "branch-a-only",
        "common-rule",
    }
    assert "parent-after-cutoff" not in branch_a.source_refs
    assert "branch-b-only" not in branch_a.source_refs
    assert "other-story-only" not in branch_a.source_refs
    assert main.read("common-rule")[1] == branch_a.read("common-rule")[1]


def test_invalid_legacy_maps_do_not_block_book_sources_and_bad_yaml_is_a_gap(
    tmp_path: Path,
) -> None:
    """依赖：source-only 读取入口。输入：有效本书正文及损坏的旧 registry/source 文件。输出：有效正文和可见损坏 gap。实现：隔离旧 map 依赖并保留本书坏源诊断。"""

    root = make_library(tmp_path)
    put_document(root, "valid-source", "valid text")
    bad = put_document(root, "broken-source", "will be replaced")
    bad.write_text("metadata: [\n", encoding="utf-8")
    invalid_maps = (
        root / "shared" / "registry" / "module-defaults.yaml",
        root / "shared" / "registry" / "version-map.yaml",
        root / "stories" / "demo" / "common" / "registry" / "module-map.yaml",
        root / "stories" / "demo" / "common" / "registry" / "version-map.yaml",
        root / "stories" / "demo" / "timelines" / "main" / "registry" / "module-map.yaml",
        root / "stories" / "demo" / "timelines" / "main" / "registry" / "version-map.yaml",
    )
    for path in invalid_maps:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("broken: [\n", encoding="utf-8")

    corpus = load_story_sources(root, GraphKey("demo", "main"))

    assert {item.document_id for item in corpus.documents} == {"valid-source"}
    assert any(bad.name in gap and "source_invalid" in gap for gap in corpus.gaps)
    assert corpus.read("valid-source")[0].body["text"] == "valid text"


def test_unregistered_story_scope_is_rejected(tmp_path: Path) -> None:
    """依赖：GraphKey 与 load_story_sources。输入：未注册作品作用域。输出：明确拒绝。实现：确认源读取不能跨越注册作品边界。"""

    root = make_library(tmp_path)

    with pytest.raises(DocumentError, match="未注册作品"):
        load_story_sources(root, GraphKey("unregistered", "main"))


def test_old_history_without_coordinate_remains_readable_with_gap(tmp_path: Path) -> None:
    """依赖：put_document 与 SourceCorpus.read。输入：缺少坐标的旧 History。输出：保留正文入口并附覆盖 gap。实现：区分原文可读与时间覆盖未知。"""

    root = make_library(tmp_path)
    path = put_document(
        root,
        "old-history",
        "legacy prose remains available",
        extra_metadata={"volume": None, "chapter": None, "scene": None},
    )

    corpus = load_story_sources(root, GraphKey("demo", "main"))
    document, reference = corpus.read("old-history")

    assert document.body["text"] == "legacy prose remains available"
    assert reference.coordinate is None
    assert any("old-history" in gap and "无叙事坐标" in gap for gap in corpus.gaps)
    assert path.is_file()


def test_loaded_document_and_hash_stay_bound_to_one_snapshot_after_edit(
    tmp_path: Path,
) -> None:
    """依赖：SourceCorpus 快照与引用。输入：加载后被改写的源文件。输出：旧正文仍配旧快照引用。实现：检验库外修改不会改写已读版本身份。"""

    root = make_library(tmp_path)
    path = put_document(root, "changing-source", "original prose")
    original_bytes = path.read_bytes()
    corpus = load_story_sources(root, GraphKey("demo", "main"))
    snapshot = corpus.snapshots["changing-source"]
    old_document, old_reference = corpus.read("changing-source")

    put_document(root, "changing-source", "replacement prose")

    assert old_document.body["text"] == "original prose"
    assert old_reference.source_hash == snapshot.source_hash
    assert snapshot.raw_bytes == original_bytes
    assert path.read_bytes() != snapshot.raw_bytes


def test_symlink_to_another_story_is_not_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """依赖：路径归属先验检查与 Windows 文件系统。输入：demo 内指向 other 的源链接。输出：链接目标未被读取。实现：监测目标字节读取并检查作用域结果。"""

    root = make_library(tmp_path)
    foreign_path = put_document(root, "foreign-document", "must stay isolated", story="other")
    link_path = (
        root
        / "stories"
        / "demo"
        / "timelines"
        / "main"
        / "history"
        / "foreign-link.yaml"
    )
    try:
        link_path.symlink_to(foreign_path)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"当前 Windows 权限或文件系统不支持文件符号链接：{exc}")

    foreign_resolved = foreign_path.resolve()
    open_path = Path.open
    foreign_reads: list[Path] = []

    def guard_foreign_open(candidate: Path, *args: Any, **kwargs: Any) -> Any:
        """依赖：Path.open。输入：待读文件路径和模式参数。输出：原文件句柄。实现：记录越书目标的任何文本或字节读取。"""

        if candidate.resolve(strict=False) == foreign_resolved:
            foreign_reads.append(candidate)
        return open_path(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guard_foreign_open)
    corpus = load_story_sources(root, GraphKey("demo", "main"))

    assert not foreign_reads
    assert "foreign-document" not in corpus.source_refs
