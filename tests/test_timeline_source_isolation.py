from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3

import pytest

from novel_rag.catalog.corpus import ValidatedCorpus, fingerprint_paths
from novel_rag.catalog.errors import CatalogValidationError
from novel_rag.composition import build_writer_service, search_graph
from novel_rag.documents import DocumentRef, load_document, read_yaml_snapshot
from novel_rag.generation.session import RunService
from novel_rag.generation.store import DraftStore, StoreConflict
from novel_rag.generation.types import DraftRef
from novel_rag.graph import GraphBuildError, GraphReadError, GraphReader, build_graph
from novel_rag.identity import GraphKey, StoryCoordinate
from novel_rag.mutations.types import fingerprint_file
from novel_rag.service import load_story_scope_registry, load_story_sources, load_valid_documents, load_validated_corpus
from writer_fixtures import make_library, put_document, write_yaml


MAIN = GraphKey("demo", "main")
CHILD = GraphKey("demo", "child")
CUTOFF = StoryCoordinate(1, 2, 3)
SHARED_COORDINATE = StoryCoordinate(1, 2, 2)


@pytest.fixture
def story(tmp_path: Path) -> tuple[Path, Path, RunService]:
    """依赖：共用作品夹具与实际无模型服务。输入：隔离目录。输出：库、工作区及服务。实现：建立父子线与分歧前、同位、分歧后和 common 合成来源。"""
    root = make_library(tmp_path)
    book = root / "stories" / MAIN.story_id
    registry = book / "common" / "registry" / "timelines.yaml"
    entries = read_yaml_snapshot(registry).data
    write_yaml(book / "snapshots" / "child.yaml", {"state": "branch begins"})
    entries["timelines"].append({
        "story_id": MAIN.story_id,
        "timeline_id": CHILD.timeline_id,
        "parent_timeline_id": MAIN.timeline_id,
        "divergence_at": "volume-01/chapter-02/scene-03",
        "divergence_snapshot": "snapshots/child.yaml",
    })
    write_yaml(registry, entries)
    put_document(root, "parent-early", "fixturemarker parent before divergence", chapter=2, scene=2)
    put_document(root, "parent-cutoff", "fixturemarker parent at divergence", chapter=2, scene=3)
    put_document(root, "parent-late", "fixturemarker parent after divergence", chapter=2, scene=4)
    put_document(root, "child-same-coordinate", "fixturemarker local at shared coordinate", timeline="child", chapter=2, scene=2)
    put_document(root, "child-late", "fixturemarker child after divergence", timeline="child", chapter=2, scene=6)
    put_document(root, "common-canon", "fixturemarker shared setting", category="canon")
    workspace = tmp_path / "workspace"
    return root, workspace, build_writer_service(root, workspace, tmp_path / "no-model.json")


def _snapshot_files(directory: Path) -> dict[Path, str]:
    """依赖：公共文件指纹。输入：临时资料树或工作区。输出：相对文件与原字节指纹。实现：按原文件读取并捕获新增、删除和改写。"""
    return {path.relative_to(directory): fingerprint_file(path) for path in directory.rglob("*") if path.is_file()}


def _bound_revision(writer: RunService, scope: GraphKey, base: DocumentRef, text: str) -> tuple[str, DraftRef]:
    """依赖：公开 prepare 和作者保存。输入：作品线、真实 DocumentRef 和修订正文。输出：run ID 与已保存 DraftRef。实现：走无模型正式入口固定基线并写入作者草稿。"""
    run_id = writer.prepare(scope, "revise", "保留分歧前的场景", "修订当前场景", base_ref=base)
    return run_id, writer.save_author_draft(run_id, 0, text)


def _mismatched_history(root: Path, physical: str, declared: str) -> Path:
    """依赖：共享文档夹具。输入：相反的物理线与声明线。输出：临时 History 路径。实现：只错标 timeline，同时选用能揭示 lineage 漏洞的坐标。"""
    return put_document(
        root, f"mismatch-from-{physical}", "fixturemarker excludedsource", timeline=physical,
        chapter=2, scene=4 if physical == MAIN.timeline_id else 1,
        extra_metadata={"timeline_id": declared},
    )


@pytest.mark.parametrize(("physical", "declared"), [("main", "child"), ("child", "main")])
def test_wrong_timeline_identity_is_excluded_from_writer_sources(story, physical: str, declared: str) -> None:
    """依赖：真实 v3 corpus、read_document、recall 及 context。输入：两种反向错标。输出：合法来源仍可用且错标只有诊断。实现：同一临时库沿各消费入口检查实际原文引用。"""
    root, _, writer = story
    bad = _mismatched_history(root, physical, declared)
    child = load_story_sources(root, CHILD)
    run_id = writer.prepare(CHILD, "discuss", "fixturemarker", "查看当前资料", base_ref=child.source_refs["child-late"])
    latest = writer.harness_tool(run_id, "read_document", {"document_id": "child-late"})
    inherited = writer.harness_tool(run_id, "read_document", {"document_id": "parent-cutoff"})
    rejected = writer.harness_tool(run_id, "read_document", {"document_id": bad.stem})
    recall = writer.harness_tool(run_id, "recall", {"query": "fixturemarker"})
    context = json.loads(writer.harness_context(run_id)["messages"][-1]["content"])

    assert latest["source_ref"]["scope"] == CHILD.as_dict()
    assert inherited["source_ref"] == child.source_refs["parent-cutoff"].as_dict()
    assert inherited["source_ref"]["scope"] == MAIN.as_dict()
    assert inherited["source_ref"]["source_hash"] == fingerprint_file(child.read("parent-cutoff")[0].path)
    expected = {"parent-early", "parent-cutoff", "child-same-coordinate", "child-late", "common-canon"}
    assert set(child.source_refs) == expected
    assert bad.stem not in load_story_sources(root, MAIN).source_refs
    assert {hit["document_id"] for hit in child.search("fixturemarker")} == expected
    assert rejected["ok"] is False
    assert {hit["document_id"] for hit in recall["references"]} == expected
    assert {hit["document_id"] for hit in context["references"]} == expected
    location = bad.relative_to(root / "stories" / MAIN.story_id).as_posix()
    assert any(location in gap and "source_invalid" in gap and f"{physical}/{declared}" in gap
               and str(root) not in gap for gap in child.gaps)
    assert any(location in gap for gap in recall["gaps"])


@pytest.mark.parametrize(("physical", "declared"), [("main", "child"), ("child", "main")])
def test_invalid_history_is_rejected_by_formal_validation_and_projection(story, physical: str, declared: str) -> None:
    """依赖：正式校验和 v2 corpus 装配。输入：物理线错误但声明已注册的 History。输出：具体路径问题与禁止建图。实现：直接走库级读取入口核对拒绝。"""
    root, _, _ = story
    bad = _mismatched_history(root, physical, declared)
    documents, issues = load_valid_documents(root, story_id=MAIN.story_id, include_shared=False)

    assert any(issue.path == bad and ("timeline" in issue.message or "时间线" in issue.message) for issue in issues)
    assert all(document.path != bad for document in documents)
    with pytest.raises(CatalogValidationError, match=bad.stem):
        load_validated_corpus(root, MAIN.story_id, timeline_id=CHILD.timeline_id, include_shared=False)


@pytest.mark.parametrize("with_root", [True, False])
def test_direct_graph_builder_rejects_nonstrict_mismatched_source(story, tmp_path: Path, with_root: bool) -> None:
    """依赖：非严格 ValidatedCorpus 与真实 GraphBuilder。输入：明确物理 timeline 的错标来源。输出：构建错误且无目标 DB。实现：分别验证有库根和仅绝对规范路径的直接调用。"""
    root, _, _ = story
    bad = _mismatched_history(root, MAIN.timeline_id, CHILD.timeline_id)
    corpus = ValidatedCorpus.from_documents(
        [load_document(bad)],
        root=root if with_root else None,
        graph_key=CHILD,
        timeline_registry=load_story_scope_registry(root, CHILD),
        strict=False,
    )
    target = CHILD.graph_path(tmp_path / "index")

    with pytest.raises(GraphBuildError, match=r"(?i)timeline|时间线"):
        build_graph(CHILD, corpus, target)
    assert not target.exists()


def test_offline_reader_rejects_existing_graph_with_mismatched_source_identity(story, tmp_path: Path, monkeypatch) -> None:
    """依赖：真实图构建、SQLite 与正式指纹。输入：旧图记录的错位来源和匹配的字节指纹。输出：无库根图消费定位拒绝。实现：只在临时索引模拟旧投影，把读者从指纹一致带到身份检查。"""
    root, _, _ = story
    corpus = load_validated_corpus(root, MAIN.story_id, timeline_id=CHILD.timeline_id, include_shared=False)
    index_root = tmp_path / "index"
    graph = build_graph(CHILD, corpus, index_root)
    with GraphReader(graph.path) as reader:
        assert reader.search("local at shared coordinate")[0].document_id == "child-same-coordinate"
    source, _ = load_story_sources(root, CHILD).read("child-same-coordinate")
    misplaced = root / "stories" / MAIN.story_id / "timelines" / MAIN.timeline_id / "history" / source.path.name
    source.path.rename(misplaced)
    digest = fingerprint_paths((misplaced if doc.path == source.path else doc.path for doc in corpus.documents), root=root)
    with closing(sqlite3.connect(graph.path)) as connection, connection:
        update = connection.execute("UPDATE documents SET source_file = ? WHERE document_id = ?",
                                    (str(misplaced), source.document_id))
        assert update.rowcount == 1
        connection.execute("UPDATE graph_manifest SET source_fingerprint = ? WHERE id = 1", (digest,))
    unchanged_graph = fingerprint_file(graph.path)

    with pytest.raises(GraphReadError, match=r"(?i)timeline|时间线"):
        search_graph(index_root, "fixturemarker", CHILD, include_shared=False)
    assert fingerprint_file(graph.path) == unchanged_graph

    misplaced.unlink()
    path_type = type(misplaced)
    resolve = path_type.resolve

    def resolve_dangling_source(candidate, *args, **kwargs):
        """依赖：真实 Path.resolve。输入：路径调用。输出：测试符号链接目标或正常绝对路径。实现：只模拟已登记文件指向库内非资料目录。"""
        if candidate == misplaced:
            return root / "elsewhere" / misplaced.name
        return resolve(candidate, *args, **kwargs)

    monkeypatch.setattr(path_type, "resolve", resolve_dangling_source)
    with pytest.raises(GraphReadError, match=misplaced.name):
        search_graph(index_root, "fixturemarker", CHILD, include_shared=False)
    assert fingerprint_file(graph.path) == unchanged_graph


@pytest.mark.parametrize("recorded_root", [True, False])
def test_offline_reader_rejects_ancestor_after_cutoff_in_old_graph(story, tmp_path: Path, recorded_root: bool) -> None:
    """依赖：公开图读取、SQLite 和注册表。输入：旧图纳入的物理父线已越界文档。输出：离线拒绝。实现：保持物理身份和清单指纹匹配，仅用真实分歧点排除旧投影。"""
    root, _, _ = story
    corpus = load_validated_corpus(root, MAIN.story_id, timeline_id=CHILD.timeline_id, include_shared=False)
    index_root = tmp_path / "index"
    graph = build_graph(CHILD, corpus, index_root)
    source, _ = load_story_sources(root, CHILD).read("parent-cutoff")
    with GraphReader(graph.path) as reader:
        assert source.document_id in {row.document_id for row in reader.search("parent at divergence")}

    moved = read_yaml_snapshot(source.path).data
    moved["metadata"].update(scene=5, scope="common")
    write_yaml(source.path, moved)
    fingerprint_root = root if recorded_root else None
    digest = fingerprint_paths((doc.path for doc in corpus.documents), root=fingerprint_root)
    with closing(sqlite3.connect(graph.path)) as connection, connection:
        projected_metadata = dict(moved["metadata"], timeline_id=CHILD.timeline_id)
        connection.execute("UPDATE documents SET metadata_json = ? WHERE document_id = ?",
                           (json.dumps(projected_metadata), source.document_id))
        connection.execute("UPDATE graph_manifest SET source_fingerprint = ?, source_root = ? WHERE id = 1",
                           (digest, str(root) if recorded_root else ""))
    unchanged_graph = fingerprint_file(graph.path)
    source_hash = fingerprint_file(source.path)

    with pytest.raises(GraphReadError, match=r"parent-cutoff\.yaml.*cutoff"):
        search_graph(index_root, "fixturemarker", CHILD, include_shared=False)
    assert fingerprint_file(graph.path) == unchanged_graph
    assert fingerprint_file(source.path) == source_hash


@pytest.mark.parametrize("common_timeline", ["main", "common"])
def test_valid_lineage_and_common_survive_cutoff_in_both_projections(story, tmp_path: Path, common_timeline: str) -> None:
    """依赖：同库 v3 读取与正式 v2 建图。输入：分歧前后、common 和声明 common 但物理属于父线的 History。输出：父线原件有效，子线严格裁切。实现：将 corpus 与 SQLite 可检索 ID 同时对账。"""
    root, _, _ = story
    put_document(root, "common-canon", "fixturemarker shared setting", category="canon", timeline=common_timeline)
    put_document(root, "parent-late-labelled-common", "fixturemarker physical parent", chapter=2, scene=5,
                 extra_metadata={"scope": "common"})
    parent = load_story_sources(root, MAIN)
    child = load_story_sources(root, CHILD)
    assert "parent-late-labelled-common" in parent.source_refs
    expected = {"parent-early", "parent-cutoff", "child-same-coordinate", "child-late", "common-canon"}
    assert set(child.source_refs) == expected
    assert child.read("common-canon")[1] == parent.read("common-canon")[1]
    assert child.source_refs["common-canon"].scope.timeline_id == common_timeline

    graph_corpus = load_validated_corpus(root, MAIN.story_id, timeline_id=CHILD.timeline_id, include_shared=False)
    assert set(graph_corpus.document_ids) == expected
    graph = build_graph(CHILD, graph_corpus, tmp_path / "index")
    with GraphReader(graph.path) as reader:
        assert {row.document_id for row in reader.search("fixturemarker", limit=20)} == expected


def test_legacy_history_path_keeps_registered_timeline_identity(tmp_path: Path) -> None:
    """依赖：真实 legacy fallback 和来源快照。输入：迁移前平铺的合法 History。输出：原路径、main Ref 及原字节指纹。实现：只在合成库撤掉空目标目录以激活兼容分支。"""
    root = make_library(tmp_path)
    path = put_document(root, "old-history", "plain legacy fixture")
    legacy = root / "stories" / MAIN.story_id / "history" / path.name
    write_yaml(legacy, read_yaml_snapshot(path).data)
    path.unlink()
    path.parent.rmdir()

    corpus = load_story_sources(root, MAIN)
    document, ref = corpus.read("old-history")
    assert document.path == legacy
    assert ref.scope == MAIN and ref.source_hash == fingerprint_file(legacy)
    assert load_validated_corpus(root, MAIN.story_id, timeline_id=MAIN.timeline_id,
                                 include_shared=False).document_ids == ("old-history",)


def test_child_cannot_adopt_inherited_history_even_when_cas_matches(story) -> None:
    """依赖：公开作者准备、保存和采用。输入：子线合法继承 Ref、正确父源 CAS 和稳定操作 ID。输出：明确权限拒绝、可重复重试且无错写。实现：先验原文使用，再核正式树、草稿和回执不变。"""
    root, workspace, writer = story
    inherited = load_story_sources(root, CHILD).source_refs["parent-cutoff"]
    run_id, draft = _bound_revision(writer, CHILD, inherited, "子线保留的修订草稿")
    read = writer.harness_tool(run_id, "read_document", {"source_ref": inherited.as_dict()})
    assert "fixturemarker parent at divergence" in read["text"]
    formal_before = _snapshot_files(root / "stories")
    workspace_before = _snapshot_files(workspace)
    operation_id = "repeat-child-adopt-inherited"

    try:
        for _ in range(2):
            with pytest.raises(ValueError, match="scope_denied") as refusal:
                writer.adopt_draft(run_id, draft.draft_revision, inherited.source_hash, CUTOFF, operation_id)
            assert "demo/child" in str(refusal.value) and "demo/main" in str(refusal.value)
    finally:
        assert _snapshot_files(root / "stories") == formal_before
        assert _snapshot_files(workspace) == workspace_before
    assert writer.run_result(run_id)["draft_ref"] == draft.as_dict()


def test_child_can_adopt_a_different_coordinate_using_inherited_reference(story) -> None:
    """依赖：真实作者采用和册章场身份。输入：父线 Ref 作为修改参考及空白子线坐标。输出：仅创建本线 History。实现：核对采用回执、独立正文身份和全部既有资料哈希。"""
    root, _, writer = story
    inherited = load_story_sources(root, CHILD).source_refs["parent-cutoff"]
    run_id, draft = _bound_revision(writer, CHILD, inherited, "子线另一场的正式正文")
    target = StoryCoordinate(1, 2, 5)
    formal = root / "stories"
    before = _snapshot_files(formal)

    receipt = writer.adopt_draft(run_id, draft.draft_revision, None, target, "new-child-coordinate")

    document, actual = load_story_sources(root, CHILD).read(receipt["document_id"])
    assert document.document_id != inherited.document_id
    assert actual.scope == CHILD and actual.coordinate == target and actual.source_revision == 1
    assert receipt["source_ref"] == actual.as_dict()
    assert document.body["content"] == "子线另一场的正式正文"
    assert document.path.is_relative_to(formal / CHILD.story_id / "timelines" / CHILD.timeline_id)
    assert _snapshot_files(formal) == {**before, document.path.relative_to(formal): actual.source_hash}


@pytest.mark.parametrize(("scope", "document_id"), [(MAIN, "parent-early"), (CHILD, "child-same-coordinate")])
def test_owned_history_updates_its_exact_ref_and_replays_receipt(story, scope: GraphKey, document_id: str) -> None:
    """依赖：作者采用和权威来源在同坐标上的精确 Ref。输入：两条线各自合法原件与旧哈希。输出：作用域、指纹、修订号与实际文件相同。实现：同时验证另一条线原件、同 ID 复验、改参数和过期 CAS。"""
    root, _, writer = story
    document, base = load_story_sources(root, scope).read(document_id)
    run_id, draft = _bound_revision(writer, scope, base, "正确来自所属时间线的修订")
    formal = root / "stories"
    before = _snapshot_files(formal)
    op_id = "replace-exact-current-document"
    receipt = writer.adopt_draft(run_id, draft.draft_revision, base.source_hash, SHARED_COORDINATE, op_id)

    actual = load_story_sources(root, scope).source_refs[document_id]
    assert receipt["adopted"] is True and receipt["source_ref"] == actual.as_dict()
    assert actual.scope == scope and actual.source_revision == base.source_revision + 1
    assert receipt["draft_ref"] == draft.as_dict()
    assert receipt["source_hash"] == fingerprint_file(document.path) != base.source_hash
    assert load_document(document.path).body["content"] == "正确来自所属时间线的修订"
    assert _snapshot_files(formal) == {**before, document.path.relative_to(formal): actual.source_hash}

    after = _snapshot_files(formal)
    assert writer.adopt_draft(run_id, draft.draft_revision, base.source_hash, SHARED_COORDINATE, op_id) == receipt
    with pytest.raises(StoreConflict, match="revision_conflict"):
        writer.adopt_draft(run_id, draft.draft_revision, actual.source_hash, SHARED_COORDINATE, op_id)
    with pytest.raises(StoreConflict, match="revision_conflict"):
        writer.adopt_draft(run_id, draft.draft_revision, base.source_hash, SHARED_COORDINATE, "new-operation-old-cas")
    assert _snapshot_files(formal) == after


@pytest.mark.parametrize("state", ["prepared", "adopted"])
def test_legacy_wrong_scope_journal_retry_rejects_but_other_child_adoption_succeeds(story, state: str) -> None:
    """依赖：真实采用与 DraftStore journal。输入：旧子线意图曾指向父线同坐标文件，含 prepared/adopted 两种状态。输出：旧 ID 保持隔离，新合法 ID 仍可提交。实现：复用实际回执结构模拟旧错写，再检查字节、回执和恢复。"""
    root, workspace, writer = story
    store = DraftStore(workspace)
    child, base = load_story_sources(root, CHILD).read("child-same-coordinate")
    parent, _ = load_story_sources(root, MAIN).read("parent-early")
    child_bytes = child.path.read_bytes()
    draft_text = "子线原本准备写的合成正文"
    run_id, draft = _bound_revision(writer, CHILD, base, draft_text)
    pre_adoption_run = store.load(run_id)
    old_id = "old-cross-scope-operation"
    genuine = writer.adopt_draft(run_id, draft.draft_revision, base.source_hash, SHARED_COORDINATE, old_id)
    journal = store.adoption_path(CHILD, old_id)
    intent = json.loads(journal.read_text(encoding="utf-8"))
    child.path.write_bytes(child_bytes)
    store.write(pre_adoption_run)

    parent_metadata = dict(parent.metadata)
    parent_metadata.update(adoption_id=old_id, source_revision=genuine["source_revision"],
                           version=str(genuine["source_revision"]))
    write_yaml(parent.path, {"metadata": parent_metadata, "content": draft_text})
    parent_hash = fingerprint_file(parent.path)
    incorrect = dict(genuine, document_id=parent.document_id, source_hash=parent_hash,
                     source_ref=dict(genuine["source_ref"], document_id=parent.document_id, source_hash=parent_hash))
    intent.update(target=str(parent.path), target_key=parent.path.relative_to(root).as_posix(),
                  document_id=parent.document_id, state=state, result=incorrect if state == "adopted" else None)
    journal.write_text(json.dumps(intent, ensure_ascii=False), encoding="utf-8")
    journal_bytes = journal.read_bytes()
    before = _snapshot_files(root / "stories")
    workspace_before = _snapshot_files(workspace)
    restarted = build_writer_service(root, workspace, workspace.parent / "no-model.json")

    try:
        with pytest.raises(ValueError, match="scope_denied"):
            restarted.adopt_draft(run_id, draft.draft_revision, base.source_hash, SHARED_COORDINATE, old_id)
    finally:
        assert _snapshot_files(root / "stories") == before
        assert _snapshot_files(workspace) == workspace_before

    receipt = restarted.adopt_draft(run_id, draft.draft_revision, base.source_hash, SHARED_COORDINATE, "valid-child-operation")
    actual = load_story_sources(root, CHILD).source_refs[child.document_id]
    assert receipt["adopted"] is True and receipt["source_ref"] == actual.as_dict()
    assert actual.scope == CHILD and receipt["draft_ref"] == draft.as_dict()
    assert fingerprint_file(parent.path) == parent_hash
    assert journal.read_bytes() == journal_bytes


def test_relocated_source_is_not_used_as_bound_baseline_or_adoption_target(story) -> None:
    """依赖：正式 DocumentRef、model context 与采用。输入：相同源字节移入物理错误线。输出：基线失效、读和采用拒绝且保留草稿。实现：在创建 run 后改变路径，核对无正式写入或预提交记录。"""
    root, workspace, writer = story
    document, base = load_story_sources(root, CHILD).read("child-same-coordinate")
    run_id, draft = _bound_revision(writer, CHILD, base, "保持原稿而非采用到错误时间线")
    moved = root / "stories" / MAIN.story_id / "timelines" / MAIN.timeline_id / "history" / document.path.name
    document.path.rename(moved)
    context = json.loads(writer.harness_context(run_id, view="model")["messages"][-1]["content"])
    read = writer.harness_tool(run_id, "read_document", {"source_ref": base.as_dict()})
    assert fingerprint_file(moved) == base.source_hash
    formal_before = _snapshot_files(root / "stories")
    workspace_before = _snapshot_files(workspace)

    with pytest.raises(ValueError, match=r"(?i)scope_denied|source_invalid|revision_conflict"):
        writer.adopt_draft(run_id, draft.draft_revision, base.source_hash, SHARED_COORDINATE, "wrong-physical-target")
    assert _snapshot_files(root / "stories") == formal_before
    assert _snapshot_files(workspace) == workspace_before
    assert context["baseline_status"] == "stale" and context["edit_reference"] is None
    assert context["baseline"]["read_arguments"] is None
    assert read["ok"] is False
    assert writer.run_result(run_id)["draft_ref"] == draft.as_dict()


def test_adoption_rejects_changed_draft_checkpoint_before_source_write(story) -> None:
    """依赖：已保存 DraftRef 与实际正文版本。输入：保存后发生字节漂移的所选草稿。输出：来源错误、正式资料和操作记账不变。实现：只篡改合成目录内的草稿字节后调用正式采用。"""
    root, workspace, writer = story
    base = load_story_sources(root, CHILD).source_refs["child-same-coordinate"]
    run_id, draft = _bound_revision(writer, CHILD, base, "原始合成修订草稿")
    draft_path = workspace / MAIN.story_id / CHILD.timeline_id / "runs" / run_id / "drafts" / f"{draft.draft_revision}.txt"
    draft_path.write_text("不同的合成草稿内容", encoding="utf-8")
    formal_before = _snapshot_files(root / "stories")
    workspace_before = _snapshot_files(workspace)

    with pytest.raises(StoreConflict, match="source_invalid"):
        writer.adopt_draft(run_id, draft.draft_revision, base.source_hash, SHARED_COORDINATE, "changed-draft")
    assert _snapshot_files(root / "stories") == formal_before
    assert _snapshot_files(workspace) == workspace_before


def test_new_cas_does_not_rebase_the_bound_document_ref(story) -> None:
    """依赖：原准备、采用与文档快照。输入：RunBinding 已固定旧 Ref，外部编辑后提供新哈希。输出：旧绑定拒绝且正式资料和工作区不变。实现：区分调用者 CAS 与不可改的运行基线。"""
    root, workspace, writer = story
    original, base = load_story_sources(root, CHILD).read("child-same-coordinate")
    run_id, draft = _bound_revision(writer, CHILD, base, "基于旧正文的待采用稿")
    revised = read_yaml_snapshot(original.path).data
    revised["metadata"].update(source_revision=base.source_revision + 1, version=str(base.source_revision + 1))
    revised["text"] = "隔离夹具中发生在运行准备后的作者修改"
    write_yaml(original.path, revised)
    actual_hash = fingerprint_file(original.path)
    assert actual_hash != base.source_hash
    formal_before = _snapshot_files(root / "stories")
    workspace_before = _snapshot_files(workspace)

    with pytest.raises(StoreConflict, match="revision_conflict"):
        writer.adopt_draft(run_id, draft.draft_revision, actual_hash, SHARED_COORDINATE, "fresh-cas-stale-baseline")
    assert _snapshot_files(root / "stories") == formal_before
    assert _snapshot_files(workspace) == workspace_before


@pytest.mark.parametrize("kind", ["canon", "summary"])
def test_child_cannot_edit_inherited_canon_or_summary(story, kind: str) -> None:
    """依赖：正式资料编辑入口。输入：分歧前可读的父线设定或摘要及真实 CAS。输出：跨时间线拒绝和原字节不变。实现：每种资料都实际从子线读取再尝试编辑。"""
    root, workspace, writer = story
    document_id = "parent-editable-reference"
    if kind == "canon":
        common, _ = load_story_sources(root, MAIN).read("common-canon")
        payload = read_yaml_snapshot(common.path).data
        payload["metadata"].update(document_id=document_id, chapter=2, scene=2)
        original = root / "stories" / MAIN.story_id / "timelines" / MAIN.timeline_id / "canon" / f"{document_id}.yaml"
        write_yaml(original, payload)
        edit = {"text": "子线不应修改父线设定"}
    else:
        original = put_document(root, document_id, "分歧前的父线摘要", category=kind, chapter=2, scene=2)
        edit = "子线不应修改父线摘要"
    document, ref = load_story_sources(root, CHILD).read(document_id)
    assert document.path == original and ref.scope == MAIN
    formal_before = _snapshot_files(root / "stories")
    workspace_before = _snapshot_files(workspace)

    try:
        with pytest.raises(ValueError, match="scope_denied") as refusal:
            writer.edit_document(CHILD, document_id, ref.source_revision, ref.source_hash, edit)
        assert "demo/child" in str(refusal.value) and "demo/main" in str(refusal.value)
    finally:
        assert _snapshot_files(root / "stories") == formal_before
        assert _snapshot_files(workspace) == workspace_before


@pytest.mark.parametrize("common_timeline", ["main", "common"])
def test_child_can_edit_common_canon_without_touching_same_name_local_canon(story, common_timeline: str) -> None:
    """依赖：SourceCorpus 和原作者资料编辑入口。输入：共同与本线同文件名、同标题的不同 ID 设定。输出：仅共同原件更新。实现：核 Ref/hash 与父子线所见原件，不以标题或名称定位写入。"""
    root, _, writer = story
    put_document(root, "common-canon", "fixturemarker shared setting", category="canon", timeline=common_timeline)
    common, base = load_story_sources(root, CHILD).read("common-canon")
    child_file = root / "stories" / CHILD.story_id / "timelines" / CHILD.timeline_id / "canon" / common.path.name
    local_payload = read_yaml_snapshot(common.path).data
    local_payload["metadata"].update(document_id="child-same-name-canon", timeline_id=CHILD.timeline_id)
    write_yaml(child_file, local_payload)
    local, local_ref = load_story_sources(root, CHILD).read("child-same-name-canon")
    assert common.metadata["title"] == local.metadata["title"]
    assert common.path.name == local.path.name
    formal = root / "stories"
    before = _snapshot_files(formal)

    receipt = writer.edit_document(CHILD, common.document_id, base.source_revision, base.source_hash,
                                   {"text": "共同设定的新版本"})

    updated = load_story_sources(root, CHILD).source_refs[common.document_id]
    assert receipt["source_ref"] == updated.as_dict()
    assert updated.scope == base.scope and updated.source_revision == base.source_revision + 1
    assert updated == load_story_sources(root, MAIN).source_refs[common.document_id]
    assert load_document(common.path).body["text"] == "共同设定的新版本"
    assert fingerprint_file(child_file) == local_ref.source_hash
    assert _snapshot_files(formal) == {**before, common.path.relative_to(formal): updated.source_hash}
