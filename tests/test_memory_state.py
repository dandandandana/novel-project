from __future__ import annotations

from pathlib import Path

import pytest

from novel_rag.generation.store import DraftStore, StoreConflict
from novel_rag.generation.types import NarrativeCursor, RunBinding
from novel_rag.identity import GraphKey
from novel_rag.memory.service import MemoryService
from novel_rag.memory.state import reduce_state
from novel_rag.service import load_story_sources
from writer_fixtures import make_library, put_document


def _writer_env(tmp_path: Path) -> tuple[Path, DraftStore, MemoryService, dict, dict, dict]:
    """依赖：writer_fixtures、DraftStore 与 SourceCorpus。输入：pytest 临时目录。输出：真实本书、运行、稿件和Canon引用。实现：创建规范Canon及唯一run并保存实际正文检查点。"""

    root = make_library(tmp_path)
    put_document(
        root,
        "world-canon",
        "旧信物仍保留刻痕。",
        category="canon",
        extra_metadata={"entity_ids": ["actor_a", "actor_b", "item_token"]},
    )
    scope = GraphKey("demo", "main")
    store = DraftStore(tmp_path / "workspace")
    run = store.create(
        RunBinding(
            scope=scope,
            task_kind="scene",
            narrative_cursor=NarrativeCursor("after"),
            base_ref=None,
            draft_branch="main",
        ),
        "作者路线",
        "本轮请求",
    )
    draft_ref = store.save(run["run_id"], 0, "正文：甲把信物交给乙。\n").as_dict()
    canon_ref = load_story_sources(root, scope).source_refs["world-canon"].as_dict()
    return root, store, MemoryService(root, store), run, draft_ref, canon_ref


def _state_change(
    entry_id: str,
    domain: str,
    kind: str,
    value: str,
    source_ref: dict,
    *,
    op: str = "set",
    lifetime: str = "carry",
) -> dict:
    """依赖：纯 reducer 的规范状态变化形状。输入：身份、领域、类型、值及真实来源。输出：一项可投影变化。实现：Set携带完整条目，Clear仅携带已有身份与来源。"""

    change = {"op": op, "entry_id": entry_id, "source_refs": [source_ref]}
    if op == "set":
        change["entry"] = {
            "entry_id": entry_id,
            "domain": domain,
            "kind": kind,
            "value": value,
            "lifetime": lifetime,
            "source_refs": [source_ref],
        }
    return change


def _batch(batch_id: str, source_ref: dict, changes: list[dict], **extra: object) -> dict:
    """依赖：StoredMemoryBatch纯值结构。输入：批次身份、真实来源、状态变化及可选边界。输出：规范化测试批次。实现：保留每批来源并将变化放入update。"""

    return {
        "batch_id": batch_id,
        "memory_revision": 1,
        "source_refs": [source_ref],
        "narrative_position": {"kind": "draft", "checkpoint_id": source_ref["checkpoint_id"]},
        "update": {"state_changes": changes, **extra},
    }


def test_state_domains_keep_world_claim_belief_and_open_request_distinct(tmp_path: Path) -> None:
    """依赖：reduce_state 与真实DraftRef。输入：World、CharacterView、OpenCondition四种明确状态。输出：领域与claim投影不混淆且请求不升级。实现：直接投影规范批次并检查未声明的阶段不会自动生成。"""

    _, _, _, _, draft_ref, _ = _writer_env(tmp_path)
    batch = _batch(
        "batch-state-domains",
        draft_ref,
        [
            _state_change("world-key", "World", "custody", "信物目前在乙手中。", draft_ref),
            _state_change("claim-key", "CharacterView", "claim", "甲认为信物仍在桌上。", draft_ref),
            _state_change("belief-key", "CharacterView", "belief", "乙相信刻痕来自旧主人。", draft_ref),
            _state_change("request-key", "OpenCondition", "request", "乙请求天亮后归还。", draft_ref),
        ],
    )

    view = reduce_state([batch], memory_revision=1, scope={"story_id": "demo", "timeline_id": "main"})

    assert {row["domain"] for row in view["entries"]} == {"World", "CharacterView", "OpenCondition"}
    assert {row["entry_id"] for row in view["claims"]} == {"claim-key"}
    assert {row["kind"] for row in view["entries"] if row["domain"] == "CharacterView"} == {"claim", "belief"}
    assert [(row["entry_id"], row["kind"]) for row in view["entries"] if row["domain"] == "OpenCondition"] == [
        ("request-key", "request")
    ]
    assert not any(row["kind"] == "commitment" for row in view["entries"])


def test_zero_change_scene_boundary_clears_scene_state_but_keeps_carry(tmp_path: Path) -> None:
    """依赖：reduce_state显式场景边界。输入：旧场景状态、carry状态及零变化新边界。输出：仅carry继续可见。实现：使用两份真实稿件来源按顺序投影批次。"""

    _, store, _, run, first_ref, _ = _writer_env(tmp_path)
    second_ref = store.save(run["run_id"], 1, "正文：天亮后，乙仍持有信物。\n").as_dict()
    first = _batch(
        "batch-scene-one",
        first_ref,
        [
            _state_change("scene-wound", "World", "injury", "伤口仍在疼痛。", first_ref, lifetime="scene"),
            _state_change("carry-promise", "OpenCondition", "promise", "乙答应天亮归还。", first_ref),
        ],
    )
    boundary = _batch(
        "batch-scene-boundary",
        second_ref,
        [],
        scene_boundary={"kind": "begin_scene", "scene_id": "scene-next"},
    )
    boundary["boundary_visibility"] = "valid"

    view = reduce_state([first, boundary], memory_revision=2)

    assert [row["entry_id"] for row in view["entries"]] == ["carry-promise"]
    assert view["entries"][0]["lifetime"] == "carry"
    assert view["recorded_through"] == boundary["narrative_position"]


def test_set_clear_and_stale_source_never_restore_an_older_value(tmp_path: Path) -> None:
    """依赖：reduce_state的顺序Set/Clear与失效处理。输入：多次Set、Clear及源失效。输出：旧值不复活且失效键显式标记。实现：使用真实不同稿件引用构造独立规范批次。"""

    _, store, _, run, first_ref, _ = _writer_env(tmp_path)
    second_ref = store.save(run["run_id"], 1, "正文：改写后的信物交接。\n").as_dict()
    third_ref = store.save(run["run_id"], 2, "正文：再一次改写。\n").as_dict()
    batches = [
        _batch("batch-old", first_ref, [_state_change("custody", "World", "holder", "信物在甲手中。", first_ref)]),
        _batch("batch-new", second_ref, [_state_change("custody", "World", "holder", "信物在乙手中。", second_ref)]),
        _batch(
            "batch-stale",
            second_ref,
            [
                _state_change("custody", "World", "holder", "信物在乙手中。", second_ref)
                | {"visibility": "stale"}
            ],
        ),
        _batch("batch-clear-set", third_ref, [_state_change("cleared-key", "World", "condition", "仍有效。", third_ref)]),
        _batch(
            "batch-clear",
            third_ref,
            [_state_change("cleared-key", "World", "condition", "", third_ref, op="clear")],
        ),
    ]

    view = reduce_state(batches, memory_revision=3)

    assert view["entries"] == []
    assert view["invalidated_keys"] == ["custody"]
    assert "custody" in view["unknowns"]


def _create_record(local_ref: str, kind: str, payload: dict) -> dict:
    """依赖：MemoryService接受的RecordWrite形状。输入：本批局部身份、记录类型与payload。输出：create操作。实现：不预造稳定ID，由服务按local_ref分配。"""

    return {"op": "create", "local_ref": local_ref, "record": {"record_kind": kind, "payload": payload}}


def _link(local_ref: str, relation: str, subject: dict, object_: dict) -> dict:
    """依赖：MemoryService端点校验。输入：局部Link身份、关系和两端引用。输出：Link create操作。实现：只保存拓扑字段且保持方向原样。"""

    return _create_record(
        local_ref,
        "link",
        {"relation_type": relation, "subject_ref": subject, "object_ref": object_},
    )


def test_real_remember_resolves_same_batch_local_refs_and_five_link_directions(tmp_path: Path) -> None:
    """依赖：MemoryService、DraftStore及实际Canon实体。输入：架构示例式同批事件、状态、伏笔与五条Link。输出：稳定ID映射及正确端点方向。实现：提交真实正文来源并从权威run批次核对成员唯一性。"""

    _, store, service, run, draft_ref, _ = _writer_env(tmp_path)
    update = {
        "event_lines": [_create_record("borrow_line", "event_line", {"title": "借用信物"})],
        "experiences": [_create_record("handoff", "experience", {"text": "甲把信物交给乙，约定天亮归还。"})],
        "state_changes": [
            {
                "op": "set",
                "local_ref": "return_due",
                "entry": {
                    "domain": "OpenCondition",
                    "kind": "promise",
                    "holder": "actor_b",
                    "target": "actor_a",
                    "value": "乙应在天亮归还信物，目前尚未履行。",
                    "lifetime": "carry",
                },
            }
        ],
        "hooks": [_create_record("mark", "hook", {"nature": "written_clue", "text": "信物背面有旧刻痕。", "explanation_candidates": []})],
        "links": [
            _link("membership", "belongs_to", {"local_ref": "handoff"}, {"local_ref": "borrow_line"}),
            _link("item", "involves", {"local_ref": "handoff"}, {"kind": "entity", "id": "item_token"}),
            _link("pending", "uses_state", {"local_ref": "borrow_line"}, {"local_ref": "return_due"}),
            _link("condition", "required_context", {"local_ref": "handoff"}, {"local_ref": "return_due"}),
            _link("setup", "plants", {"local_ref": "handoff"}, {"local_ref": "mark"}),
        ],
    }

    result = service.remember(
        run["run_id"],
        "call-five-links",
        draft_ref=draft_ref,
        expected_memory_revision=0,
        update=update,
    )
    batch = store.load(run["run_id"])["memory_batches"][0]
    mapping = result["local_ref_to_stable_id"]

    assert set(mapping) == {"borrow_line", "handoff", "return_due", "mark", "membership", "item", "pending", "condition", "setup"}
    assert len(set(mapping.values())) == len(mapping)
    assert result["memory_revision"] == 1
    assert len(batch["update"]["links"]) == 5
    by_ref = {write["local_ref"]: write["record"]["payload"] for write in batch["update"]["links"]}
    assert by_ref["membership"]["subject_ref"] == {"id": mapping["handoff"], "kind": "experience"}
    assert by_ref["membership"]["object_ref"] == {"id": mapping["borrow_line"], "kind": "event_line"}
    assert by_ref["item"]["subject_ref"] == {"id": mapping["handoff"], "kind": "experience"}
    assert by_ref["item"]["object_ref"] == {"id": "item_token", "kind": "entity"}
    assert by_ref["pending"]["subject_ref"] == {"id": mapping["borrow_line"], "kind": "event_line"}
    assert by_ref["pending"]["object_ref"] == {"id": mapping["return_due"], "kind": "state"}
    assert by_ref["condition"]["subject_ref"] == {"id": mapping["handoff"], "kind": "experience"}
    assert by_ref["condition"]["object_ref"] == {"id": mapping["return_due"], "kind": "state"}
    assert by_ref["setup"]["subject_ref"] == {"id": mapping["handoff"], "kind": "experience"}
    assert by_ref["setup"]["object_ref"] == {"id": mapping["mark"], "kind": "hook"}


def test_invalid_link_and_author_input_fact_reject_whole_batch(tmp_path: Path) -> None:
    """依赖：MemoryService整批校验与DraftStore原子提交。输入：反向Link及纯作者输入支持的混合事实。输出：两批均拒绝且revision、批次、调用回执不变。实现：真实run上先后触发端点和来源域错误。"""

    _, store, service, run, draft_ref, _ = _writer_env(tmp_path)
    invalid_topology = {
        "event_lines": [_create_record("line", "event_line", {"title": "线"})],
        "experiences": [_create_record("exp", "experience", {"text": "经过"})],
        "notes": [_create_record("valid-note", "note", {"text": "同批本可写入"})],
        "links": [_link("reversed", "belongs_to", {"local_ref": "line"}, {"local_ref": "exp"})],
    }
    with pytest.raises(ValueError, match="Link方向/端点非法"):
        service.remember(run["run_id"], "call-invalid-link", draft_ref=draft_ref, expected_memory_revision=0, update=invalid_topology)
    after_link = store.load(run["run_id"])
    assert after_link["memory_revision"] == 0
    assert after_link["memory_batches"] == []
    assert "call-invalid-link" not in after_link["tool_commits"]

    input_ref = after_link["binding"]["input_snapshot_refs"][0]
    input_only_update = {
        "notes": [
            {
                "op": "create",
                "local_ref": "input-note",
                "record": {"record_kind": "note", "payload": {"text": "作者原始请求笔记"}, "source_refs": [input_ref]},
            }
        ],
        "experiences": [
            {
                "op": "create",
                "local_ref": "input-fact",
                "record": {"record_kind": "experience", "payload": {"text": "不能由请求变成已经发生的事实"}, "source_refs": [input_ref]},
            }
        ],
    }
    with pytest.raises(ValueError, match="作者计划不是已发生事实"):
        service.remember(run["run_id"], "call-input-fact", draft_ref=None, expected_memory_revision=0, update=input_only_update)
    after_input = store.load(run["run_id"])
    assert after_input["memory_revision"] == 0
    assert after_input["memory_batches"] == []
    assert "call-input-fact" not in after_input["tool_commits"]


def test_memory_compare_and_set_conflict_leaves_committed_snapshot_unchanged(tmp_path: Path) -> None:
    """依赖：MemoryService.remember、真实DocumentRef和StoreConflict。输入：一批成功记忆及过期expected revision。输出：旧CAS被拒绝且已提交快照字节不变。实现：前后读取同一run权威JSON内容。"""

    _, store, service, run, _, canon_ref = _writer_env(tmp_path)
    update = {
        "notes": [
            {
                "op": "create",
                "local_ref": "canon-note",
                "record": {"record_kind": "note", "payload": {"text": "Canon刻痕仍待解释。"}, "source_refs": [canon_ref]},
            }
        ]
    }
    first = service.remember(run["run_id"], "call-cas-good", draft_ref=None, expected_memory_revision=0, update=update)
    path = store._run_path(run["run_id"])
    committed = path.read_bytes()

    with pytest.raises(StoreConflict, match="记忆版本已变化"):
        service.remember(run["run_id"], "call-cas-stale", draft_ref=None, expected_memory_revision=0, update={})

    current = store.load(run["run_id"])
    assert first["memory_revision"] == 1
    assert path.read_bytes() == committed
    assert current["memory_revision"] == 1
    assert len(current["memory_batches"]) == 1
    assert "call-cas-stale" not in current["tool_commits"]


def test_real_memory_call_id_retry_survives_new_store_without_duplicate_batch(tmp_path: Path) -> None:
    """依赖：MemoryService与DraftStore持久幂等提交。输入：真实稿源、稳定call_id及完整参数。输出：新Store重试恢复同一ID映射且不重复版本。实现：跨Store实例重放相同remember参数并读取磁盘权威快照。"""

    root, store, service, run, draft_ref, _ = _writer_env(tmp_path)
    update = {
        "event_lines": [_create_record("line", "event_line", {"title": "借用线"})],
        "experiences": [_create_record("handoff", "experience", {"text": "甲将信物交给乙。"})],
        "links": [_link("membership", "belongs_to", {"local_ref": "handoff"}, {"local_ref": "line"})],
    }
    original = service.remember(run["run_id"], "call-retry-semantic", draft_ref=draft_ref, expected_memory_revision=0, update=update)
    restarted_store = DraftStore(store.root)
    restarted_service = MemoryService(root, restarted_store)

    retried = restarted_service.remember(run["run_id"], "call-retry-semantic", draft_ref=draft_ref, expected_memory_revision=0, update=update)
    current = restarted_store.load(run["run_id"])

    assert retried == original
    assert retried["local_ref_to_stable_id"] == original["local_ref_to_stable_id"]
    assert current["memory_revision"] == 1
    assert len(current["memory_batches"]) == 1
    assert len(current["tool_commits"]) == 1


def test_rewritten_draft_source_invalidates_state_without_reappearance_on_recall(tmp_path: Path) -> None:
    """依赖：真实DraftStore检查点前缀校验及MemoryService.recall。输入：以旧正文为来源的Set后保存不兼容改稿。输出：状态退出默认视图且重复recall不造新历史。实现：以真实来源失效触发Reducer并比较提交前后批次。"""

    root, store, service, run, draft_ref, _ = _writer_env(tmp_path)
    update = {
        "state_changes": [
            {
                "op": "set",
                "local_ref": "injury",
                "entry": {"domain": "World", "kind": "injury", "value": "甲的手腕仍在疼痛。", "lifetime": "carry"},
            }
        ]
    }
    result = service.remember(run["run_id"], "call-state-before-rewrite", draft_ref=draft_ref, expected_memory_revision=0, update=update)
    state_id = result["local_ref_to_stable_id"]["injury"]
    rewritten = "改写后的完整正文没有保留原来的前缀。\n"
    store.save(run["run_id"], 1, rewritten)
    before_recall = store.load(run["run_id"])

    first_packet = service.recall(run["run_id"], focus=["actor_a"])
    second_packet = service.recall(run["run_id"], focus=["actor_a"])
    after_recall = store.load(run["run_id"])

    assert first_packet["state_view"]["entries"] == []
    assert state_id in first_packet["state_view"]["invalidated_keys"]
    assert second_packet["state_view"]["entries"] == []
    assert before_recall["memory_revision"] == after_recall["memory_revision"]
    assert before_recall["memory_batches"] == after_recall["memory_batches"]
    assert len(after_recall["memory_batches"]) == 1
