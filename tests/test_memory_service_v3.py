from __future__ import annotations

from pathlib import Path

import pytest

from novel_rag.generation.store import DraftStore, StoreConflict
from novel_rag.generation.types import NarrativeCursor, RunBinding
from novel_rag.graph.corpus import json_text
from novel_rag.identity import GraphKey, StoryCoordinate
from novel_rag.memory.service import MemoryService
from novel_rag.retrieval.assembler import estimate_tokens
from novel_rag.service import load_story_sources
from writer_fixtures import make_library, put_document


def _create_run(
    root: Path,
    store: DraftStore,
    *,
    coordinate: StoryCoordinate | None = None,
    endpoint: str = "after",
    branch: str = "main",
    outline: str = "作者路线：沿原文继续。",
    request: str = "本轮续写请求。",
) -> dict:
    """依赖：真实DraftStore与RunBinding。输入：库根、存储、游标和分支。输出：持久化v3 run。实现：在demo/main作用域固定故事边界与作者输入快照。"""

    return store.create(
        RunBinding(
            scope=GraphKey("demo", "main"),
            task_kind="scene",
            narrative_cursor=NarrativeCursor(endpoint, coordinate),
            base_ref=None,
            draft_branch=branch,
        ),
        outline,
        request,
    )


def _set_change(entry_id: str, value: str, *, op: str = "set") -> dict:
    """依赖：MemoryService状态变化输入形状。输入：稳定状态ID、值及Set/Clear操作。输出：一项状态变化。实现：Set提供合法World条目，Clear只引用既有ID。"""

    change = {"op": op, "entry_id": entry_id}
    if op == "set":
        change["entry"] = {
            "domain": "World",
            "kind": "condition",
            "value": value,
            "lifetime": "carry",
        }
    return change


def _formal_batch(source_ref: dict, *, state: dict | None = None,
                  experiences: list[dict] | None = None,
                  links: list[dict] | None = None) -> dict:
    """依赖：MemoryService.batches与project_records规范结构。输入：真实DocumentRef及可选状态/经历/Link。输出：可由summary YAML回读的正式批次。实现：保持批次、记录和source_refs字段与存储合同一致。"""

    state_changes = []
    if state is not None:
        change = {
            "op": state.get("op", "set"),
            "entry_id": state["entry_id"],
            "source_refs": [source_ref],
        }
        if change["op"] == "set":
            change["entry"] = {
                "entry_id": state["entry_id"],
                "domain": state.get("domain", "World"),
                "kind": "condition",
                "value": state["value"],
                "lifetime": state.get("lifetime", "carry"),
                "source_refs": [source_ref],
                "narrative_position": state.get("narrative_position"),
            }
        state_changes.append(change)
    return {
        "batch_id": state.get("batch_id", "formal-memory-batch") if state else "formal-memory-batch",
        "memory_revision": 1,
        "source_refs": [source_ref],
        "narrative_position": state.get("narrative_position") if state else None,
        "update": {
            "state_changes": state_changes,
            "experiences": experiences or [],
            "links": links or [],
        },
    }


def _formal_record(record_id: str, kind: str, payload: dict, source_ref: dict,
                   position: dict) -> dict:
    """依赖：project_records的正式Record结构。输入：稳定ID、记录类型、payload、真实来源及生效位置。输出：一个create记录变化。实现：显式绑定demo/main与source_refs，不预造索引。"""

    return {
        "op": "create",
        "id": record_id,
        "record": {
            "id": record_id,
            "record_kind": kind,
            "scope": {"story_id": "demo", "timeline_id": "main"},
            "source_refs": [source_ref],
            "narrative_position": position,
            "payload": payload,
        },
    }


def _write_projection(root: Path, batch: dict, *, document_id: str = "memory-projection") -> Path:
    """依赖：writer_fixtures.put_document与Summary metadata校验。输入：正式库根及StoredMemoryBatch。输出：被真实SourceCorpus读取的summary路径。实现：在YAML metadata中保存memory_projection及原批次。"""

    return put_document(
        root,
        document_id,
        "按批次保存的记忆展示文本。",
        category="summary",
        extra_metadata={
            "memory_kind": "memory_projection",
            "memory_schema_version": 3,
            "memory_batches": [batch],
        },
    )


def _future_boundary_batch(draft_ref: dict, position: dict) -> dict:
    """依赖：正式MemoryBatch与已保存DraftRef。输入：真实稿件引用和未来文档生效位置。输出：future scene boundary批次。实现：将有效稿源与较晚正式位置分开保存供游标裁剪。"""

    return {
        "batch_id": "future-scene-boundary",
        "memory_revision": 2,
        "draft_ref": draft_ref,
        "source_refs": [draft_ref],
        "narrative_position": position,
        "update": {
            "state_changes": [],
            "scene_boundary": {"kind": "begin_scene", "scene_id": "future-scene"},
        },
    }


def _document_position(coordinate: StoryCoordinate) -> dict:
    """依赖：StoryCoordinate。输入：完整正式来源坐标。输出：Document narrative_position。实现：转换为SourceRef合同使用的纯映射。"""

    return {"kind": "document", "coordinate": {
        "volume": coordinate.volume,
        "chapter": coordinate.chapter,
        "scene": coordinate.scene,
    }}


def test_early_history_is_recallable_without_memory_batches_or_index(tmp_path: Path) -> None:
    """依赖：writer_fixtures、真实SourceCorpus与MemoryService。输入：早期History、游标未来History及另一作品来源。输出：query/focus均返回早期原文入口且越界来源排除。实现：不创建索引或记忆批次，直接经真实YAML与Store回读。"""

    root = make_library(tmp_path)
    put_document(root, "early-history", "铜钥匙的独特线索留在井边。", chapter=1, scene=1)
    put_document(root, "future-history", "铜钥匙未来线索在塔顶。", chapter=1, scene=3)
    put_document(root, "foreign-history", "铜钥匙独特线索属于另一作品。", story="other")
    store = DraftStore(tmp_path / "workspace")
    run = _create_run(root, store, coordinate=StoryCoordinate(1, 1, 2))
    service = MemoryService(root, store)

    by_query = service.recall(run["run_id"], query="独特线索")
    by_focus = service.recall(run["run_id"], focus=["early-history"])
    query_ids = {item["document_id"] for item in by_query["references"]}
    focus_ids = {item["document_id"] for item in by_focus["references"]}

    assert "early-history" in query_ids
    assert "future-history" not in query_ids
    assert "foreign-history" not in query_ids
    assert "early-history" in focus_ids
    assert "future-history" not in focus_ids
    assert "foreign-history" not in focus_ids
    assert store.load(run["run_id"])["memory_batches"] == []


@pytest.mark.parametrize("source_change", ["modify", "delete"])
def test_invalid_source_advances_memory_revision_once_and_rejects_old_cas(
    tmp_path: Path,
    source_change: str,
) -> None:
    """依赖：真实summary YAML、DocumentRef、MemoryService与DraftStore CAS。输入：以History字节为来源的正式状态投影及随后修改/删除的同一源。输出：效力变化只推进一次revision，旧expected_memory_revision整批拒绝。实现：改变实际源文件后重复recall并尝试旧版本remember。"""

    root = make_library(tmp_path)
    source_path = put_document(root, "memory-source", "来源原文：铜钥匙在井边。", chapter=1, scene=1)
    initial_corpus = load_story_sources(root, GraphKey("demo", "main"))
    source_ref = initial_corpus.source_refs["memory-source"].as_dict()
    batch = _formal_batch(source_ref, state={
        "entry_id": "formal-state-key",
        "value": "source validity marker: 铜钥匙仍在井边。",
    })
    _write_projection(root, batch)
    store = DraftStore(tmp_path / "workspace")
    run = _create_run(root, store)
    service = MemoryService(root, store)
    input_ref = run["binding"]["input_snapshot_refs"][0]
    service.remember(
        run["run_id"],
        "seed-memory-revision",
        draft_ref=None,
        expected_memory_revision=0,
        update={"notes": [{
            "op": "create",
            "local_ref": "seed-note",
            "record": {
                "record_kind": "note",
                "payload": {"text": "用于验证来源失效前已有的memory revision。"},
                "source_refs": [input_ref],
            },
        }]},
    )
    before_revision = store.load(run["run_id"])["memory_revision"]
    baseline = service.recall(run["run_id"], query="source validity marker")

    if source_change == "modify":
        put_document(root, "memory-source", "来源原文已被作者改成另一场景。", chapter=1, scene=1)
    else:
        source_path.unlink()

    first = service.recall(run["run_id"], query="source validity marker")
    after_first = store.load(run["run_id"])
    second = service.recall(run["run_id"], query="source validity marker")
    after_second = store.load(run["run_id"])

    assert baseline["memory_revision"] == before_revision
    assert [row["entry_id"] for row in baseline["state_view"]["entries"]] == ["formal-state-key"]
    assert first["state_view"]["entries"] == []
    assert "formal-state-key" in first["state_view"]["invalidated_keys"]
    assert first["memory_revision"] == before_revision + 1
    assert first["state_view"]["state_revision"] == before_revision + 1
    assert second["memory_revision"] == first["memory_revision"]
    assert after_second["memory_revision"] == after_first["memory_revision"]
    old_batches = after_second["memory_batches"]
    old_commits = after_second["tool_commits"]
    old_cas_update = {"notes": [{
        "op": "create",
        "local_ref": "must-not-commit",
        "record": {
            "record_kind": "note",
            "payload": {"text": "过期CAS不能部分保存此有效批次。"},
            "source_refs": [input_ref],
        },
    }]}
    with pytest.raises(StoreConflict, match="记忆版本已变化"):
        service.remember(
            run["run_id"],
            "old-memory-revision-after-source-change",
            draft_ref=None,
            expected_memory_revision=before_revision,
            update=old_cas_update,
        )
    unchanged = store.load(run["run_id"])
    assert unchanged["memory_batches"] == old_batches
    assert unchanged["tool_commits"] == old_commits


def test_experience_and_link_effective_positions_clip_before_after_graph(tmp_path: Path) -> None:
    """依赖：真实SourceCorpus游标、summary YAML、MemoryService与router。输入：较早原文来源、较晚生效的Experience及连接边。输出：before端点不见未来节点且不能经未来Link桥接，after端点可见。实现：同一正式投影分别绑定真实before/after run。"""

    root = make_library(tmp_path)
    put_document(root, "early-source", "早期原文：甲留下铜钥匙。", chapter=1, scene=1)
    source_ref = load_story_sources(root, GraphKey("demo", "main")).source_refs["early-source"].as_dict()
    early_position = _document_position(StoryCoordinate(1, 1, 1))
    effective_position = _document_position(StoryCoordinate(1, 1, 3))
    experiences = [
        _formal_record("early-exp", "experience", {"text": "早期种子：甲留下铜钥匙。"}, source_ref, early_position),
        _formal_record("late-exp", "experience", {"text": "late effective experience marker"}, source_ref, effective_position),
        _formal_record("far-exp", "experience", {"text": "未来桥之后的远端经历"}, source_ref, early_position),
    ]
    links = [
        _formal_record("future-edge-in", "link", {
            "relation_type": "follows",
            "subject_ref": {"kind": "experience", "id": "early-exp"},
            "object_ref": {"kind": "experience", "id": "late-exp"},
        }, source_ref, effective_position),
        _formal_record("future-edge-out", "link", {
            "relation_type": "follows",
            "subject_ref": {"kind": "experience", "id": "late-exp"},
            "object_ref": {"kind": "experience", "id": "far-exp"},
        }, source_ref, effective_position),
    ]
    batch = _formal_batch(source_ref, experiences=experiences, links=links)
    _write_projection(root, batch)
    store = DraftStore(tmp_path / "workspace")
    before_run = _create_run(root, store, coordinate=StoryCoordinate(1, 1, 3), endpoint="before", branch="before")
    after_run = _create_run(root, store, coordinate=StoryCoordinate(1, 1, 3), endpoint="after", branch="after")
    service = MemoryService(root, store)

    before = service.recall(before_run["run_id"], query="早期种子")
    after = service.recall(after_run["run_id"], query="早期种子")
    before_ids = {item["id"] for item in before["experiences"]}
    after_ids = {item["id"] for item in after["experiences"]}

    assert "early-exp" in before_ids
    assert "late-exp" not in before_ids
    assert "far-exp" not in before_ids
    assert {"early-exp", "late-exp", "far-exp"} <= after_ids


def test_clear_then_set_reuses_the_same_stable_state_id(tmp_path: Path) -> None:
    """依赖：真实DraftStore检查点、MemoryService.remember与Store CAS。输入：同一正文分支上的Set、Clear、再Set。输出：Clear后原stable entry_id可重新Set并成为有效状态。实现：每次更新均用实际保存的前缀正文和递增memory_revision提交。"""

    root = make_library(tmp_path)
    store = DraftStore(tmp_path / "workspace")
    run = _create_run(root, store)
    service = MemoryService(root, store)
    first_text = "第一段正文：铜钥匙仍在桌上。\n"
    first_ref = store.save(run["run_id"], 0, first_text).as_dict()
    created = service.remember(
        run["run_id"], "state-set-first", draft_ref=first_ref,
        expected_memory_revision=0,
        update={"state_changes": [{
            "op": "set",
            "local_ref": "stable-state",
            "entry": {"domain": "World", "kind": "condition", "value": "铜钥匙在桌上。", "lifetime": "carry"},
        }]},
    )
    stable_id = created["local_ref_to_stable_id"]["stable-state"]
    second_text = first_text + "第二段正文：甲拿起铜钥匙。\n"
    second_ref = store.save(run["run_id"], 1, second_text).as_dict()
    cleared = service.remember(
        run["run_id"], "state-clear", draft_ref=second_ref,
        expected_memory_revision=1,
        update={"state_changes": [_set_change(stable_id, "", op="clear")]},
    )
    third_text = second_text + "第三段正文：乙将钥匙收好。\n"
    third_ref = store.save(run["run_id"], 2, third_text).as_dict()

    reset = service.remember(
        run["run_id"], "state-set-again", draft_ref=third_ref,
        expected_memory_revision=cleared["memory_revision"],
        update={"state_changes": [_set_change(stable_id, "铜钥匙已由乙收好。") ]},
    )

    packet = service.recall(run["run_id"], query="铜钥匙已由乙收好")
    assert reset["memory_revision"] == 3
    assert [row["entry_id"] for row in packet["state_view"]["entries"]] == [stable_id]
    assert packet["state_view"]["entries"][0]["value"] == "铜钥匙已由乙收好。"


def test_cross_branch_and_invalidated_state_ids_are_rejected(tmp_path: Path) -> None:
    """依赖：真实分支DraftRef、MemoryService来源验证与StoreConflict。输入：一支已返回的状态ID及另一支/改写后的稿源。输出：跨branch和来源已失效的旧ID均拒绝整批。实现：建立兄弟run并以不保留前缀的真实正文改写触发失效。"""

    root = make_library(tmp_path)
    store = DraftStore(tmp_path / "workspace")
    first_run = _create_run(root, store, branch="branch-a")
    service = MemoryService(root, store)
    first_ref = store.save(first_run["run_id"], 0, "A分支：甲握住铜钥匙。\n").as_dict()
    result = service.remember(
        first_run["run_id"], "branch-a-state", draft_ref=first_ref,
        expected_memory_revision=0,
        update={"state_changes": [{
            "op": "set",
            "local_ref": "branch-a-state",
            "entry": {"domain": "World", "kind": "condition", "value": "A分支持有钥匙。", "lifetime": "carry"},
        }]},
    )
    stable_id = result["local_ref_to_stable_id"]["branch-a-state"]
    sibling = _create_run(root, store, branch="branch-b")
    sibling_ref = store.save(sibling["run_id"], 0, "B分支：乙拿到另一把钥匙。\n").as_dict()
    foreign_change = {"state_changes": [_set_change(stable_id, "B分支不可借用A分支状态。")]}

    with pytest.raises(ValueError, match="状态ID未知"):
        service.remember(
            sibling["run_id"], "cross-branch-state", draft_ref=sibling_ref,
            expected_memory_revision=0, update=foreign_change,
        )

    rewritten_ref = store.save(
        first_run["run_id"], 1, "A分支被整体改写：旧正文前缀已不存在。\n"
    ).as_dict()
    current_revision = store.load(first_run["run_id"])["memory_revision"]
    with pytest.raises(ValueError, match="状态ID未知"):
        service.remember(
            first_run["run_id"], "stale-state-after-rewrite", draft_ref=rewritten_ref,
            expected_memory_revision=current_revision,
            update={"state_changes": [_set_change(stable_id, "失效来源不能再次写活。 ")]},
        )
    assert "cross-branch-state" not in store.load(sibling["run_id"])["tool_commits"]
    assert "stale-state-after-rewrite" not in store.load(first_run["run_id"])["tool_commits"]


def test_author_input_plan_does_not_advance_body_recorded_through(tmp_path: Path) -> None:
    """依赖：MemoryService.remember/recall、DraftStore输入快照与reduce_state。输入：正文来源状态后追加作者输入支持的计划笔记。输出：状态recorded_through仍停在正文检查点。实现：使用真实author_input引用提交计划并比较正文来源位置。"""

    root = make_library(tmp_path)
    store = DraftStore(tmp_path / "workspace")
    run = _create_run(root, store, outline="路线：稍后再揭开铜钥匙来历。", request="续写，并保留未知。")
    service = MemoryService(root, store)
    draft_ref = store.save(run["run_id"], 0, "正文：甲发现铜钥匙仍在井边。\n").as_dict()
    service.remember(
        run["run_id"], "body-state-before-plan", draft_ref=draft_ref,
        expected_memory_revision=0,
        update={"state_changes": [{
            "op": "set",
            "local_ref": "body-state",
            "entry": {"domain": "OpenCondition", "kind": "unknown", "value": "continuity marker: 铜钥匙来历未明。", "lifetime": "carry"},
        }]},
    )
    before = service.recall(run["run_id"], query="continuity marker")
    input_ref = run["binding"]["input_snapshot_refs"][0]
    service.remember(
        run["run_id"], "author-plan-after-body", draft_ref=None,
        expected_memory_revision=1,
        update={"notes": [{
            "op": "create",
            "local_ref": "author-plan-note",
            "record": {
                "record_kind": "note",
                "payload": {"text": "continuity marker: 作者计划稍后揭开铜钥匙来历。"},
                "source_refs": [input_ref],
            },
        }]},
    )

    after = service.recall(run["run_id"], query="continuity marker")

    assert before["state_view"]["recorded_through"] == {"kind": "draft", "checkpoint_id": draft_ref["checkpoint_id"]}
    assert after["state_view"]["recorded_through"] == before["state_view"]["recorded_through"]
    assert [row["entry_id"] for row in after["state_view"]["entries"]] == [
        before["state_view"]["entries"][0]["entry_id"]
    ]


def test_stale_expected_revision_is_rejected_before_any_recall(tmp_path: Path) -> None:
    """依赖：真实History字节、正式memory_projection、MemoryService与DraftStore CAS。输入：已记录DocumentRef遭外部改写、随后直接以旧版本remember。输出：remember自身发现效力变化并拒绝整批，后续重复recall不再推进版本。实现：来源改写后不调用recall即提交有效作者输入note，再检查run及回读。"""

    root = make_library(tmp_path)
    put_document(root, "cas-source", "采用前原文：铜钥匙仍在井边。", chapter=1, scene=1)
    source_ref = load_story_sources(root, GraphKey("demo", "main")).source_refs["cas-source"].as_dict()
    projection = _formal_batch(source_ref, state={
        "entry_id": "cas-state",
        "value": "direct CAS marker: 铜钥匙在井边。",
    })
    _write_projection(root, projection)
    store = DraftStore(tmp_path / "workspace")
    run = _create_run(root, store)
    service = MemoryService(root, store)
    input_ref = run["binding"]["input_snapshot_refs"][0]
    service.remember(
        run["run_id"],
        "cas-revision-seed",
        draft_ref=None,
        expected_memory_revision=0,
        update={"notes": [{
            "op": "create",
            "local_ref": "cas-seed-note",
            "record": {
                "record_kind": "note",
                "payload": {"text": "建立来源改写前的CAS基线。"},
                "source_refs": [input_ref],
            },
        }]},
    )
    baseline_run = store.load(run["run_id"])
    source_path = put_document(root, "cas-source", "作者在调用read前已改写了原文。", chapter=1, scene=1)
    old_revision = baseline_run["memory_revision"]
    old_batches = baseline_run["memory_batches"]
    old_commits = baseline_run["tool_commits"]
    update = {"notes": [{
        "op": "create",
        "local_ref": "must-not-land",
        "record": {
            "record_kind": "note",
            "payload": {"text": "这个过期CAS批次不能写入。"},
            "source_refs": [input_ref],
        },
    }]}

    with pytest.raises(StoreConflict, match="记忆版本已变化"):
        service.remember(
            run["run_id"], "stale-cas-before-recall", draft_ref=None,
            expected_memory_revision=old_revision, update=update,
        )

    conflicted_run = store.load(run["run_id"])
    first = service.recall(run["run_id"], query="direct CAS marker")
    after_first = store.load(run["run_id"])
    second = service.recall(run["run_id"], query="direct CAS marker")
    after_second = store.load(run["run_id"])

    assert source_path.is_file()
    assert conflicted_run["memory_revision"] == old_revision + 1
    assert conflicted_run["memory_batches"] == old_batches
    assert conflicted_run["tool_commits"] == old_commits
    assert "cas-state" in first["state_view"]["invalidated_keys"]
    assert first["memory_revision"] == old_revision + 1
    assert second["memory_revision"] == first["memory_revision"]
    assert after_first["memory_revision"] == after_second["memory_revision"]


def test_future_formal_scene_boundary_does_not_clear_current_scene_state(tmp_path: Path) -> None:
    """依赖：真实DraftRef、正式summary批次、游标与reduce_state。输入：当前scene状态及较晚正式生效的begin_scene边界。输出：future boundary被标记且不解除当前状态。实现：两个有序真实summary YAML保存状态来源和有效稿源边界，再按当前游标回读。"""

    root = make_library(tmp_path)
    put_document(root, "scene-source", "原文：甲仍在屋内。", chapter=1, scene=1)
    source_ref = load_story_sources(root, GraphKey("demo", "main")).source_refs["scene-source"].as_dict()
    early_position = _document_position(StoryCoordinate(1, 1, 1))
    current_state = _formal_batch(source_ref, state={
        "entry_id": "current-scene-state",
        "domain": "World",
        "lifetime": "scene",
        "value": "scene status marker: 甲仍在屋内。",
        "narrative_position": early_position,
    })
    _write_projection(root, current_state, document_id="a-state-projection")
    store = DraftStore(tmp_path / "workspace")
    run = _create_run(root, store, coordinate=StoryCoordinate(1, 1, 2))
    draft_ref = store.save(run["run_id"], 0, "当前正文：甲尚未离开屋内。\n").as_dict()
    future_boundary = _future_boundary_batch(
        draft_ref,
        _document_position(StoryCoordinate(1, 1, 3)),
    )
    _write_projection(root, future_boundary, document_id="z-future-boundary")
    service = MemoryService(root, store)

    loaded, _ = service.batches(store.load(run["run_id"]))
    packet = service.recall(run["run_id"], query="scene status marker")

    boundary_batch = next(batch for batch in loaded if batch["batch_id"] == "future-scene-boundary")
    assert boundary_batch["boundary_visibility"] == "future"
    assert [row["entry_id"] for row in packet["state_view"]["entries"]] == ["current-scene-state"]


def test_memory_packet_2048_budget_keeps_required_context_as_a_whole(tmp_path: Path) -> None:
    """依赖：真实SourceCorpus、memory_projection、MemoryService与统一token估算。输入：含StateView/来源的可装入完整经历包及超预算长经历required_context。输出：完整返回结构不超过2048 tokens，经历只完整出现或整包缺省。实现：按真实YAML与DocumentRef分别查询可容纳包和超限包，不裁剪经历文本。"""

    root = make_library(tmp_path)
    put_document(root, "budget-source", "预算测试使用的正式原文来源。", chapter=1, scene=1)
    source_ref = load_story_sources(root, GraphKey("demo", "main")).source_refs["budget-source"].as_dict()
    early_position = _document_position(StoryCoordinate(1, 1, 1))
    fit_state = {
        "entry_id": "budget-state",
        "value": "fitpackmarker state evidence: " + "丙" * 80,
        "narrative_position": early_position,
    }
    experiences = [
        _formal_record(
            "fit-result", "experience",
            {"text": "fitpackmarker result: " + "甲" * 600}, source_ref, early_position,
        ),
        _formal_record(
            "fit-required", "experience",
            {"text": "fit package required context: " + "乙" * 160}, source_ref, early_position,
        ),
        _formal_record(
            "long-result", "experience",
            {"text": "longpackmarker result: " + "丁" * 2400}, source_ref, early_position,
        ),
        _formal_record(
            "long-required", "experience",
            {"text": "long experience required context: " + "戊" * 120}, source_ref, early_position,
        ),
    ]
    links = [
        _formal_record("fit-required-link", "link", {
            "relation_type": "required_context",
            "subject_ref": {"kind": "experience", "id": "fit-result"},
            "object_ref": {"kind": "experience", "id": "fit-required"},
        }, source_ref, early_position),
        _formal_record("fit-state-link", "link", {
            "relation_type": "required_context",
            "subject_ref": {"kind": "experience", "id": "fit-result"},
            "object_ref": {"kind": "state", "id": "budget-state"},
        }, source_ref, early_position),
        _formal_record("long-required-link", "link", {
            "relation_type": "required_context",
            "subject_ref": {"kind": "experience", "id": "long-result"},
            "object_ref": {"kind": "experience", "id": "long-required"},
        }, source_ref, early_position),
    ]
    _write_projection(root, _formal_batch(source_ref, state=fit_state, experiences=experiences, links=links))
    store = DraftStore(tmp_path / "workspace")
    run = _create_run(root, store)
    service = MemoryService(root, store)

    complete = service.recall(run["run_id"], query="fitpackmarker", available_tokens=2048)
    oversized = service.recall(run["run_id"], query="longpackmarker", available_tokens=2048)
    complete_experience_ids = {row["id"] for row in complete["experiences"]}
    oversized_experience_ids = {row["id"] for row in oversized["experiences"]}
    complete_text = json_text(complete)
    oversized_text = json_text(oversized)

    assert estimate_tokens(complete_text) <= 2048
    assert "state_view" in complete and "references" in complete
    assert "budget-source" in {row["document_id"] for row in complete["references"]}
    assert [row["entry_id"] for row in complete["state_view"]["entries"]] == ["budget-state"]
    assert source_ref in complete["state_view"]["source_refs"]
    assert {"fit-result", "fit-required"} <= complete_experience_ids
    assert next(row for row in complete["experiences"] if row["id"] == "fit-result")["payload"]["text"] == "fitpackmarker result: " + "甲" * 600
    assert estimate_tokens(oversized_text) <= 2048
    assert "long-result" not in oversized_experience_ids
    assert "longpackmarker result: " + "丁" * 2400 not in oversized_text
    assert any("long-result" in gap and "整包" in gap for gap in oversized["gaps"])


def test_formal_summary_replay_uses_source_order_not_summary_filename_order(tmp_path: Path) -> None:
    """依赖：真实History DocumentRef、summary memory_batches、MemoryService与reducer。输入：较早History Set和较晚History Clear，但summary文件名按反向时间排序。输出：新服务按来源顺序回读后状态保持清除。实现：不写run候选，只从实际YAML摘要扫描并断言字典序确实与坐标相反。"""

    root = make_library(tmp_path)
    put_document(root, "early-history", "较早正文：甲把铜钥匙放回抽屉。", chapter=1, scene=1)
    put_document(root, "later-history", "较晚正文：甲确认铜钥匙已经归还。", chapter=2, scene=1)
    corpus = load_story_sources(root, GraphKey("demo", "main"))
    early_ref = corpus.source_refs["early-history"].as_dict()
    later_ref = corpus.source_refs["later-history"].as_dict()
    earlier_set = _formal_batch(early_ref, state={
        "batch_id": "earlier-history-set",
        "entry_id": "ordered-state",
        "value": "钥匙暂存在抽屉。",
        "narrative_position": _document_position(StoryCoordinate(1, 1, 1)),
    })
    later_clear = _formal_batch(later_ref, state={
        "batch_id": "later-history-clear",
        "op": "clear",
        "entry_id": "ordered-state",
        "narrative_position": _document_position(StoryCoordinate(1, 2, 1)),
    })
    later_summary_path = _write_projection(root, later_clear, document_id="a-later-clear")
    earlier_summary_path = _write_projection(root, earlier_set, document_id="z-earlier-set")
    assert early_ref["coordinate"]["chapter"] < later_ref["coordinate"]["chapter"]
    assert later_summary_path.name < earlier_summary_path.name
    store = DraftStore(tmp_path / "workspace")
    run = _create_run(root, store, coordinate=StoryCoordinate(1, 2, 1))
    assert store.load(run["run_id"])["memory_batches"] == []
    service = MemoryService(root, DraftStore(store.root))

    replayed_batches, _ = service.batches(store.load(run["run_id"]))
    packet = service.recall(run["run_id"])

    assert [batch["batch_id"] for batch in replayed_batches] == ["earlier-history-set", "later-history-clear"]
    assert packet["state_view"]["entries"] == []
    assert "ordered-state" not in packet["state_view"]["invalidated_keys"]


def test_older_stale_set_cannot_poison_newer_valid_set_at_same_chapter(tmp_path: Path) -> None:
    """依赖：read_yaml快照生成的正式DocumentRef、YAML memory_projection与真实MemoryService。输入：同一History文档revision 1的旧Set及revision 2的当前Set，summary名称按旧版本在先。输出：仅新有效值存在且旧stale批次不将其失效。实现：同一章实际改写source_revision并用新Store实例回读正式YAML批次。"""

    root = make_library(tmp_path)
    put_document(
        root, "versioned-history", "第一版原文：钥匙在桌上。", chapter=1, scene=1,
        extra_metadata={"source_revision": 1},
    )
    old_ref = load_story_sources(root, GraphKey("demo", "main")).source_refs["versioned-history"].as_dict()
    put_document(
        root, "versioned-history", "第二版原文：钥匙已收进柜中。", chapter=1, scene=1,
        extra_metadata={"source_revision": 2},
    )
    new_ref = load_story_sources(root, GraphKey("demo", "main")).source_refs["versioned-history"].as_dict()
    assert old_ref["source_revision"] == 1
    assert new_ref["source_revision"] == 2
    assert old_ref["source_hash"] != new_ref["source_hash"]
    assert old_ref["coordinate"] == new_ref["coordinate"]
    old_set = _formal_batch(old_ref, state={
        "entry_id": "revisioned-state",
        "value": "revision state marker: 钥匙仍在桌上。",
        "narrative_position": _document_position(StoryCoordinate(1, 1, 1)),
    })
    new_set = _formal_batch(new_ref, state={
        "entry_id": "revisioned-state",
        "value": "revision state marker: 钥匙已收进柜中。",
        "narrative_position": _document_position(StoryCoordinate(1, 1, 1)),
    })
    _write_projection(root, old_set, document_id="a-old-revision-set")
    _write_projection(root, new_set, document_id="z-current-revision-set")
    store = DraftStore(tmp_path / "workspace")
    run = _create_run(root, store, coordinate=StoryCoordinate(1, 1, 1))
    assert store.load(run["run_id"])["memory_batches"] == []
    service = MemoryService(root, DraftStore(store.root))

    packet = service.recall(run["run_id"], query="revision state marker")

    assert [row["entry_id"] for row in packet["state_view"]["entries"]] == ["revisioned-state"]
    assert packet["state_view"]["entries"][0]["value"] == "revision state marker: 钥匙已收进柜中。"
    assert "revisioned-state" not in packet["state_view"]["invalidated_keys"]


def test_invalid_v3_memory_container_becomes_source_loader_gap(tmp_path: Path) -> None:
    """依赖：writer_fixtures、validate_document与真实SourceLoader。输入：正常History及容器字段错误的v3 summary YAML。输出：有效来源仍可读且坏summary成为source_invalid gap。实现：经load_story_sources读取真实文件并确认加载不中断。"""

    root = make_library(tmp_path)
    put_document(root, "valid-history", "有效正文：甲仍在旅途中。", chapter=1, scene=1)
    broken_path = put_document(
        root,
        "broken-memory-summary",
        "该摘要容器无效。",
        category="summary",
        extra_metadata={
            "memory_schema_version": 3,
            "memory_kind": "memory_projection",
            "memory_batches": [{"batch_id": "broken-batch", "changes": []}],
        },
    )

    corpus = load_story_sources(root, GraphKey("demo", "main"))

    assert "valid-history" in corpus.source_refs
    assert "broken-memory-summary" not in corpus.source_refs
    assert any(
        broken_path.name in gap and "source_invalid" in gap and "memory batch需要update映射" in gap
        for gap in corpus.gaps
    )
