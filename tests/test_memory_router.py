from __future__ import annotations

from pathlib import Path

import pytest

from novel_rag.generation.store import DraftStore
from novel_rag.generation.types import NarrativeCursor, RunBinding
from novel_rag.identity import GraphKey
from novel_rag.memory.router import route
from novel_rag.memory.service import MemoryService
from novel_rag.service import load_story_sources
from novel_rag.graph.corpus import json_text
from novel_rag.retrieval.assembler import estimate_tokens
from writer_fixtures import make_library, put_document


def _source_ref(tmp_path: Path) -> dict:
    """依赖：writer_fixtures与load_story_sources。输入：pytest临时目录。输出：实际Canon DocumentRef。实现：创建规范本书Canon并读取其原始字节指纹。"""

    root = make_library(tmp_path)
    put_document(root, "router-canon", "router fixture", category="canon")
    return load_story_sources(root, GraphKey("demo", "main")).source_refs["router-canon"].as_dict()


def _record(record_id: str, kind: str, payload: dict, source_ref: dict) -> dict:
    """依赖：router规范Record映射。输入：稳定ID、记录类型、payload及真实来源。输出：source-only规范记录。实现：明确固定scope及来源引用。"""

    return {
        "id": record_id,
        "record_kind": kind,
        "scope": {"story_id": "demo", "timeline_id": "main"},
        "source_refs": [source_ref],
        "narrative_position": None,
        "payload": payload,
    }


def _required_link(record_id: str, subject: tuple[str, str], object_: tuple[str, str], source_ref: dict) -> dict:
    """依赖：required_context依赖闭包。输入：Link ID、依赖记录及目标记录(kind,id)。输出：规范必要上下文Link。实现：保留正向subject到object方向。"""

    return _record(
        record_id,
        "link",
        {
            "relation_type": "required_context",
            "subject_ref": {"kind": subject[0], "id": subject[1]},
            "object_ref": {"kind": object_[0], "id": object_[1]},
        },
        source_ref,
    )


def _writer_env(tmp_path: Path) -> tuple[Path, DraftStore, MemoryService, dict, dict]:
    """依赖：DraftStore、MemoryService与source-only目录。输入：pytest临时目录。输出：真实本书运行、正文检查点和服务。实现：由规范Canon登记三实体并保存实际稿件。"""

    root = make_library(tmp_path)
    put_document(
        root,
        "story-canon",
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
        "续写信物相关情节",
    )
    draft_ref = store.save(run["run_id"], 0, "正文：乙发现信物背面的旧刻痕。\n").as_dict()
    return root, store, MemoryService(root, store), run, draft_ref


def test_required_context_selects_complete_pack_or_reports_missing_dependency(tmp_path: Path) -> None:
    """依赖：route的必要依赖闭包。输入：带required_context的结果经历及依赖经历。输出：完整包整体入选，缺少依赖时结果退出并报告gap。实现：对完整及移除依赖后的规范记录分别路由。"""

    source_ref = _source_ref(tmp_path)
    result = _record("result-exp", "experience", {"text": "complete pack marker result"}, source_ref)
    prerequisite = _record("prerequisite-exp", "experience", {"text": "required earlier cause"}, source_ref)
    context = _required_link(
        "context-link",
        ("experience", "result-exp"),
        ("experience", "prerequisite-exp"),
        source_ref,
    )
    complete = route(
        {"result-exp": result, "prerequisite-exp": prerequisite, "context-link": context},
        [],
        query="complete pack marker",
        available_tokens=1024,
    )
    incomplete = route(
        {"result-exp": result, "context-link": context},
        [],
        query="complete pack marker",
        available_tokens=1024,
    )

    assert {item["id"] for item in complete["experiences"]} == {"result-exp", "prerequisite-exp"}
    assert incomplete["experiences"] == []
    assert any("result-exp" in gap and "prerequisite-exp" in gap for gap in incomplete["gaps"])


def test_shared_required_state_is_deduplicated_inside_the_budget(tmp_path: Path) -> None:
    """依赖：route有界完整包选择与真实DocumentRef。输入：两条seed共同依赖同一状态及固定token预算。输出：两段经历和唯一状态均完整入选。实现：采用紧凑规范payload并在有限预算下检查包内去重。"""

    source_ref = _source_ref(tmp_path)
    first = _record("exp-first", "experience", {"text": "paired marker first"}, source_ref)
    second = _record("exp-second", "experience", {"text": "paired marker second"}, source_ref)
    first_link = _required_link("context-first", ("experience", "exp-first"), ("state", "state-shared"), source_ref)
    second_link = _required_link("context-second", ("experience", "exp-second"), ("state", "state-shared"), source_ref)
    state = {
        "entry_id": "state-shared",
        "domain": "World",
        "kind": "condition",
        "value": "same shared requirement",
        "lifetime": "carry",
        "source_refs": [source_ref],
    }

    packet = route(
        {"exp-first": first, "exp-second": second, "context-first": first_link, "context-second": second_link},
        [state],
        query="paired marker",
        available_tokens=710,
    )

    assert {item["id"] for item in packet["experiences"]} == {"exp-first", "exp-second"}
    assert [item["entry_id"] for item in packet["state_entries"]] == ["state-shared"]
    assert not packet["gaps"]
    assert estimate_tokens(json_text(packet)) <= 710


def _create_record(local_ref: str, kind: str, payload: dict) -> dict:
    """依赖：MemoryService的RecordWrite输入。输入：本批局部引用、kind和payload。输出：create写操作。实现：不预设稳定ID或写出第二份拓扑。"""

    return {"op": "create", "local_ref": local_ref, "record": {"record_kind": kind, "payload": payload}}


def _link(local_ref: str, relation: str, subject: dict, object_: dict) -> dict:
    """依赖：MemoryService Link端点合同。输入：关系、方向两端与local_ref。输出：Link create操作。实现：按subject/object保存显式边。"""

    return _create_record(
        local_ref,
        "link",
        {"relation_type": relation, "subject_ref": subject, "object_ref": object_},
    )


def test_old_item_hook_is_recalled_and_recall_does_not_create_history(tmp_path: Path) -> None:
    """依赖：真实MemoryService remember/recall、DraftStore及Canon实体。输入：信物经历、written_clue Hook和显式involves/plants Link。输出：以旧物为focus召回线索且重复读取不写历史。实现：真实提交一次后前后比较权威run快照。"""

    root, store, service, run, draft_ref = _writer_env(tmp_path)
    update = {
        "experiences": [_create_record("old-item-exp", "experience", {"text": "乙在旧信物上发现一道刻痕。"})],
        "hooks": [
            _create_record(
                "old-item-hook",
                "hook",
                {"nature": "written_clue", "text": "刻痕的来历仍未确定。", "explanation_candidates": []},
            )
        ],
        "links": [
            _link("old-item-involves", "involves", {"local_ref": "old-item-exp"}, {"kind": "entity", "id": "item_token"}),
            _link("clue-setup", "plants", {"local_ref": "old-item-exp"}, {"local_ref": "old-item-hook"}),
        ],
    }
    committed = service.remember(
        run["run_id"],
        "call-old-item-clue",
        draft_ref=draft_ref,
        expected_memory_revision=0,
        update=update,
    )
    before = store.load(run["run_id"])

    first = service.recall(run["run_id"], focus=["item_token"])
    second = service.recall(run["run_id"], focus=["item_token"])
    after = store.load(run["run_id"])

    hook_id = committed["local_ref_to_stable_id"]["old-item-hook"]
    assert any(item["id"] == hook_id and item["payload"]["nature"] == "written_clue" for item in first["hooks"])
    assert any(item["id"] == hook_id and item["payload"]["nature"] == "written_clue" for item in second["hooks"])
    assert first["memory_revision"] == second["memory_revision"] == 1
    assert before["memory_revision"] == after["memory_revision"] == 1
    assert before["memory_batches"] == after["memory_batches"]
    assert len(after["memory_batches"]) == 1


@pytest.mark.parametrize("hook_id", ["0-old-clue", "hook-old-clue", "zz-old-clue"])
@pytest.mark.parametrize("query", ["最初捡到的那枚金属小物还有什么没有弄明白", "ordinary marker 是怎么回事"])
def test_paraphrase_discovers_clues_before_ordinary_noise(tmp_path: Path, hook_id: str, query: str) -> None:
    """依赖：route和真实来源。输入：无名称的问句、80普通节点、旧伏笔与未决条件。输出：ID变化不影响少量线索入选且标候选。实现：复现无命中及碰巧命中普通文字的两种饥饿。"""
    ref = _source_ref(tmp_path)
    records = {f"ordinary-{i:03}": _record(f"ordinary-{i:03}", "note", {"text": "ordinary marker"}, ref)
               for i in range(80)}
    records[hook_id] = _record(hook_id, "hook", {"nature": "unresolved", "text": "青铜扣三短一长刻痕的作用未知；尚未揭晓。"}, ref)
    pending = {"entry_id": "state-pending", "domain": "OpenCondition", "kind": "pending",
               "value": "尚未归还的信物", "source_refs": [ref]}
    packet = route(records, [pending], query=query)
    assert [row["id"] for row in packet["hooks"]] == [hook_id]
    assert any(row["entry_id"] == "state-pending" for row in packet["state_entries"])
    assert any(row["record_id"] == hook_id and "候选" in row["reason"] for row in packet["selection_reasons"])
    assert any("未被本次查询选入" in gap for gap in packet["gaps"])
    if "ordinary marker" in query:
        assert any("未访问" in gap for gap in packet["gaps"])


def test_discovery_keeps_ambiguity_and_excludes_author_plans(tmp_path: Path) -> None:
    """依赖：route及作者材料边界。输入：多个自然性质的Hook和大量计划。输出：保留各线索原文/性质而不认定唯一指代，计划不饿掉事实。实现：无词面命中时检查完整候选理由。"""
    ref = _source_ref(tmp_path)
    records = {f"plan-{i:03}": _record(f"plan-{i:03}", "hook", {"nature": "author_plan", "text": "未来预定回收"}, ref)
               for i in range(80)}
    for index, nature in enumerate(("unresolved", "written_clue", "inferred_echo")):
        key = f"clue-{index}"
        records[key] = _record(key, "hook", {"nature": nature, "text": f"线索{index}的旧痕迹", "explanation_candidates": []}, ref)
    packet = route(records, [], query="以前那个尚未解释的小东西")
    assert {row["payload"]["nature"] for row in packet["hooks"]} == {"unresolved", "written_clue", "inferred_echo"}
    assert all("候选" in row["reason"] for row in packet["selection_reasons"])
    assert not any(row["payload"]["nature"] == "author_plan" for row in packet["hooks"])


def test_explicit_focus_does_not_discover_unrelated_clues(tmp_path: Path) -> None:
    """依赖：route定向查询合同。输入：明确Note焦点及无关伏笔。输出：只选焦点而不并列全库线索。实现：候选发现不能改变已给身份的范围。"""
    ref = _source_ref(tmp_path)
    records = {"salary": _record("salary", "note", {"text": "工钱账目"}, ref),
               "clue": _record("clue", "hook", {"nature": "unresolved", "text": "旧物刻痕"}, ref)}
    packet = route(records, [], focus=["salary"], query="工钱")
    assert packet["hooks"] == []
    assert [row["id"] for row in packet["notes"]] == ["salary"]


def test_author_plan_word_hits_do_not_starve_fact_candidates(tmp_path: Path) -> None:
    """依赖：route非作者线索优先级。输入：80词面命中的计划、3无命中的实际Hook。输出：访问截断前保留全部实际候选。实现：计划可按词面提供参考，但不能占满事实候选队列。"""
    ref = _source_ref(tmp_path)
    records = {f"plan-{i:03}": _record(f"plan-{i:03}", "hook", {"nature": "author_plan", "text": "最初捡到的某物在未来揭晓"}, ref)
               for i in range(80)}
    for i in range(3):
        key = f"old-{i}"
        records[key] = _record(key, "hook", {"nature": "unresolved", "text": "旧刻痕尚未解释"}, ref)
    packet = route(records, [], query="最初捡到的那枚金属小物还有什么没有弄明白")
    assert {row["id"] for row in packet["hooks"] if row["payload"]["nature"] != "author_plan"} == {"old-0", "old-1", "old-2"}
    assert all("候选" in row["reason"] for row in packet["selection_reasons"] if row["record_id"].startswith("old-"))
    plan = route(records, [], focus=["plan-079"])
    assert [row["id"] for row in plan["hooks"]] == ["plan-079"]


def test_required_context_cannot_use_author_plan_as_fact_bridge(tmp_path: Path) -> None:
    """依赖：route必要闭包与作者计划隔离。输入：事实Hook到计划再到经历的必要边。输出：事实包拒选并显示计划缺口，不顺桥召回经历。实现：实际正文来源的Link也不能解除计划性质。"""
    ref = _source_ref(tmp_path)
    records = {"fact": _record("fact", "hook", {"nature": "unresolved", "text": "已出现的刻痕"}, ref),
               "plan": _record("plan", "hook", {"nature": "author_plan", "text": "未来写作构想"}, ref),
               "remote": _record("remote", "experience", {"text": "另一条无关经历"}, ref),
               "first": _required_link("first", ("hook", "fact"), ("hook", "plan"), ref),
               "second": _required_link("second", ("hook", "plan"), ("experience", "remote"), ref)}
    packet = route(records, [], focus=["fact"])
    assert packet["hooks"] == []
    assert packet["experiences"] == []
    assert any("fact" in gap and "作者" in gap for gap in packet["gaps"])


def test_more_than_visit_limit_reports_unvisited_clues(tmp_path: Path) -> None:
    """依赖：route有界候选访问。输入：70条有效Hook及无名称问句。输出：64条完整候选与真实6项访问缺口。实现：候选发现不谎称全库检索完毕。"""
    ref = _source_ref(tmp_path)
    records = {f"hook-{i:03}": _record(f"hook-{i:03}", "hook", {"nature": "unresolved", "text": f"旧线索{i}"}, ref)
               for i in range(70)}
    packet = route(records, [], query="那个小物还有什么未弄懂")
    assert len(packet["hooks"]) == 64
    assert any("还有6项未访问" in gap for gap in packet["gaps"])


def test_real_recall_paraphrase_preserves_sources_and_revision(tmp_path: Path) -> None:
    """依赖：MemoryService真实提交/读取。输入：正文支持的旧线索与无实体问句。输出：真实稳定ID/source进入候选且读取不写记忆。实现：通过remember规范化后以空focus调用recall。"""
    _, store, service, run, draft_ref = _writer_env(tmp_path)
    committed = service.remember(run["run_id"], "paraphrase-clue", draft_ref=draft_ref, expected_memory_revision=0,
        update={"hooks": [_create_record("old-clue", "hook", {"nature": "unresolved", "text": "青铜扣三短一长刻痕的作用未知；尚未揭晓。"})]})
    before = store.load(run["run_id"])
    packet = service.recall(run["run_id"], focus=[], query="最初捡到的那枚金属小物还有什么没有弄明白")
    assert [row["id"] for row in packet["hooks"]] == [committed["local_ref_to_stable_id"]["old-clue"]]
    assert packet["hooks"][0]["source_refs"] == [draft_ref]
    assert packet["memory_revision"] == before["memory_revision"] == 1
    assert store.load(run["run_id"])["memory_batches"] == before["memory_batches"]
