"""候选继续查找与冻结交付分页分开；真实工具与隔离资料验证，不修改归档作品。"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from novel_rag.composition import build_writer_service
from novel_rag.generation.context import active_recall_selection
from novel_rag.generation.context import context_binding
from novel_rag.identity import GraphKey
from novel_rag.memory.router import route
from writer_fixtures import make_library, put_document, write_yaml


@pytest.fixture
def navigation_runtime(tmp_path: Path, request: pytest.FixtureRequest):
    """依赖：原Writer/真实remember及临时库。输入：pytest目录/显式条数（默认70）。输出：有正文来源Hook的run/ID。实现：原保存与整批提交建夹具，保留不同原性质和完整文字。"""
    count = getattr(request, "param", 70)
    root = make_library(tmp_path)
    put_document(root, "background", "可修改的原始背景资料。", category="canon")
    writer = build_writer_service(root, tmp_path / "workspace", tmp_path / "no-model.json")
    run_id = writer.prepare(GraphKey("demo", "main"), "write", "保留线索歧义。", "继续故事。")
    text = "\n".join(f"第{i:03}块铜牌的刻痕还未辨明。" for i in range(count))
    draft = writer.harness_tool(run_id, "save_draft", {"text": text, "expected_revision": 0}, "save")
    update = {"hooks": [{"op": "create", "local_ref": f"clue-{i}", "record": {
        "record_kind": "hook", "payload": {"nature": "unresolved" if i % 2 else "unexplained",
        "text": f"第{i:03}块铜牌的刻痕还未辨明。", "explanation_candidates": []}}} for i in range(count)]}
    remembered = writer.harness_tool(run_id, "remember", {"draft_ref": draft, "expected_memory_revision": 0, "update": update}, "remember")
    assert remembered.get("ok") is not False, remembered
    return root, writer, run_id, remembered["local_ref_to_stable_id"]


@pytest.mark.parametrize("navigation_runtime", [130], indirect=True)
def test_real_candidate_search_continues_64_64_2_and_replays_after_restart(navigation_runtime, tmp_path: Path) -> None:
    """依赖：真实harness/Store。输入：130Hook及原cursor。输出：64/64/2、公开回执无控制列表及重启重放相等。实现：逐字段核原文/性质/来源/位置，原行和版本保持。"""
    root, writer, run_id, ids = navigation_runtime
    before = writer.store.load(run_id)
    page = writer.harness_tool(run_id, "recall", {"query": "无名物件"})
    pages = [page]
    arguments = page["candidate_search"]["next_arguments"]
    original_key = arguments["continuation"]["call_id"]
    original_row = next(row for row in writer.store.load(run_id)["tool_results"] if row["call_id"] == original_key)
    receipt = writer.harness_tool(run_id, "read_document", {"context_slot": "tool_receipt", "invocation_key": original_key})
    public_row = json.loads(receipt["text"])
    assert "candidate_search_state" not in public_row
    assert '"frontier"' not in receipt["text"] and '"visited_ids"' not in receipt["text"]
    assert public_row["arguments"] == original_row["arguments"]
    assert public_row["result"] == original_row["result"]
    public_snapshot = writer.store.snapshot(run_id)
    snapshot_row = next(row for row in public_snapshot["tool_results"] if row["call_id"] == original_key)
    assert snapshot_row == public_row
    assert next(row for row in writer.store.load(run_id)["tool_results"] if row["call_id"] == original_key) == original_row
    second = writer.harness_tool(run_id, "recall", arguments, "page-two")
    restarted = build_writer_service(root, tmp_path / "workspace", tmp_path / "no-model.json")
    assert restarted.harness_tool(run_id, "recall", arguments, "page-two") == second
    pages.append(second)
    pages.append(restarted.harness_tool(run_id, "recall", second["candidate_search"]["next_arguments"]))
    assert [len(packet["hooks"]) for packet in pages] == [64, 64, 2]
    assert pages[-1]["candidate_search"]["next_arguments"] is None
    assert pages[-1]["candidate_search"]["complete"] is True
    assert pages[-1]["candidate_search"]["visited_count"] == 130
    found = [row for packet in pages for row in packet["hooks"]]
    originals = [write["record"] for write in before["memory_batches"][0]["update"]["hooks"]]
    assert len({row["id"] for row in found}) == 130
    assert {row["id"] for row in found} == set(ids.values())
    for original in originals:
        actual = next(row for row in found if row["id"] == original["id"])
        assert all(actual[key] == original[key] for key in ("payload", "source_refs", "narrative_position"))
    assert all("线索候选（未确认对应）" == reason["reason"] for packet in pages for reason in packet["selection_reasons"])
    after = restarted.store.load(run_id)
    assert after["memory_revision"] == before["memory_revision"]
    assert after["memory_batches"] == before["memory_batches"]
    assert after["draft_ref"] == before["draft_ref"] and after["tool_commits"] == before["tool_commits"]
    assert active_recall_selection(after) is None


def test_candidate_cursor_does_not_replace_existing_focus(navigation_runtime) -> None:
    """依赖：原持续选择派生/真实recall。输入：已有焦点后临时发现与继续查找。输出：持续focus/Q原样保持。实现：核对工具行参数，不把页进度当作者焦点。"""
    _, writer, run_id, ids = navigation_runtime
    writer.harness_tool(run_id, "recall", {"focus": [ids["clue-0"]], "query": "原话题"})
    previous = active_recall_selection(writer.store.load(run_id))
    root = writer.harness_tool(run_id, "recall", {"query": "无名物件"})
    writer.harness_tool(run_id, "recall", root["candidate_search"]["next_arguments"])
    assert active_recall_selection(writer.store.load(run_id)) == previous


@pytest.mark.parametrize("view", ["semantic", "json"])
def test_delivery_pages_and_unvisited_candidates_have_separate_entries(navigation_runtime, view: str) -> None:
    """依赖：原语义/字符交付及候选导航。输入：小交付窗口与130Hook。输出：原交付页仍限首64根，候选入口另取下一批。实现：只转发返回入口，核本run原完整结果未改。"""
    _, writer, run_id, _ = navigation_runtime
    arguments = {"query": "无名物件", **({"page_characters": 1200} if view == "json" else {})}
    page = writer.harness_tool(run_id, "recall", arguments, delivery="model")
    search_arguments = page["candidate_search"]["next_arguments"]
    assert search_arguments["continuation"]["kind"] == "candidates"
    assert page["next_arguments"]["continuation"].get("kind") in {"semantic", None}
    frozen_key = page["result_ref"]["call_id"]
    frozen = next(row["result"] for row in writer.store.load(run_id)["tool_results"] if row["call_id"] == frozen_key)
    assert len(frozen["hooks"]) == 64
    following = writer.harness_tool(run_id, "recall", page["next_arguments"], delivery="model")
    assert following["candidate_search"]["next_arguments"] == search_arguments
    assert next(row["result"] for row in writer.store.load(run_id)["tool_results"] if row["call_id"] == frozen_key) == frozen
    next_candidates = writer.harness_tool(run_id, "recall", search_arguments)
    assert len(next_candidates["hooks"]) == 6
    assert {row["id"] for row in next_candidates["hooks"]}.isdisjoint(row["id"] for row in frozen["hooks"])
    assert "frontier" not in page["candidate_search"] and "visited_ids" not in page["candidate_search"]


@pytest.mark.parametrize("mutation", ["source", "remember", "aliases"])
def test_candidate_cursor_rejects_source_or_memory_changes(navigation_runtime, mutation: str) -> None:
    """依赖：真实源字节/remember效力。输入：取得cursor后变更未选Canon或新增记忆。输出：snapshot_stale且不沿旧frontier拼新内容。实现：保留原cursor和参数，核失败无正文或新候选泄露。"""
    root, writer, run_id, _ = navigation_runtime
    if mutation == "source":
        put_document(root, "late-background", "prepare后新增、未进入首包的资料。", category="canon")
    first = writer.harness_tool(run_id, "recall", {"query": "无名物件"})
    if mutation == "source":
        corpus = writer.memory.corpus(writer.store.load(run_id))
        source = corpus.read("late-background")[0].path
        source.write_bytes(source.read_bytes() + b"\n# changed unselected source\n")
    elif mutation == "aliases":
        write_yaml(root / "stories" / "demo" / "common" / "registry" / "aliases.yaml", {
            "aliases": [{"canonical_id": "new-entity", "names": ["新别名"]}]})
    else:
        run = writer.store.load(run_id)
        writer.harness_tool(run_id, "remember", {"draft_ref": run["draft_ref"], "expected_memory_revision": run["memory_revision"],
            "update": {"notes": [{"op": "create", "local_ref": "new-note", "record": {"record_kind": "note", "payload": {"text": "新的记忆。"}}}]}}, "new-note")
    result = writer.harness_tool(run_id, "recall", first["candidate_search"]["next_arguments"])
    assert result["ok"] is False and result["error"]["code"] == "snapshot_stale"
    assert "hooks" not in result


def test_candidate_cursor_rejects_cross_run_hash_and_extra_parameters(navigation_runtime) -> None:
    """依赖：本run原tool_results/参数合同。输入：异run、假hash、额外query及cursor字段。输出：范围或形状拒绝。实现：只改返回cursor并核无候选/事实泄露。"""
    _, writer, run_id, _ = navigation_runtime
    first = writer.harness_tool(run_id, "recall", {"query": "无名物件"})
    arguments = first["candidate_search"]["next_arguments"]
    other = writer.prepare(GraphKey("demo", "main"), "write", "其他任务", "查线索")
    assert writer.harness_tool(other, "recall", arguments)["error"]["code"] == "scope_denied"
    fake = deepcopy(arguments)
    fake["continuation"]["content_hash"] = "sha256:" + "0" * 64
    assert writer.harness_tool(run_id, "recall", fake)["error"]["code"] == "source_invalid"
    fake = deepcopy(arguments)
    fake["continuation"]["offset"] = 128
    assert writer.harness_tool(run_id, "recall", fake)["error"]["code"] == "source_invalid"
    assert writer.harness_tool(run_id, "recall", {**arguments, "query": "换查询"})["error"]["code"] == "source_invalid"


def test_router_frontier_preserves_distance_cycles_and_dependency_packages() -> None:
    """依赖：原route/方向边与必要闭包。输入：链/循环/共享依赖及OpenCondition。输出：每页有界新候选、原跳数/包约束与终止。实现：用小max_nodes区分继续frontier和从根重扫。"""
    records = {str(i): {"id": str(i), "record_kind": "experience", "payload": {"text": f"事件{i}"}, "source_refs": []} for i in range(5)}
    for i, (left, right) in enumerate([(0, 1), (1, 0), (1, 2), (2, 1), (2, 3), (3, 4)]):
        records[f"link{i}"] = {"id": f"link{i}", "record_kind": "link", "source_refs": [], "payload": {
            "relation_type": "follows", "subject_ref": {"kind": "experience", "id": str(left)}, "object_ref": {"kind": "experience", "id": str(right)}}}
    first = route(records, [], focus=["0"], max_nodes=1, max_hops=2)
    second = route(records, [], focus=["0"], max_nodes=1, max_hops=2, candidate_search=first["candidate_search_state"])
    third = route(records, [], focus=["0"], max_nodes=1, max_hops=2, candidate_search=second["candidate_search_state"])
    found = [row["id"] for packet in (first, second, third) for row in packet["experiences"]]
    assert len(found) == len(set(found)) == 3
    assert set(found) == {"0", "1", "2"}
    assert third["candidate_search"]["complete"]
    assert any("关联跳数上限" in gap for gap in third["gaps"])


def test_later_candidates_keep_pending_and_shared_dependencies_but_reject_author_bridge() -> None:
    """依赖：原router/作者材料判定/必要闭包。输入：71Hook、Pending、共享经历和作者计划桥。输出：后批完整依赖、性质与信息边界保持。实现：两批遍历，不让未访问事实借计划补前提。"""
    records = {f"h-{i:03}": {"id": f"h-{i:03}", "record_kind": "hook", "source_refs": [],
        "payload": {"nature": "unresolved", "text": f"原线索{i}", "explanation_candidates": []}} for i in range(71)}
    records["dep"] = {"id": "dep", "record_kind": "experience", "source_refs": [], "payload": {"text": "实际经历"}}
    records["plan"] = {"id": "plan", "record_kind": "hook", "source_refs": [],
        "payload": {"nature": "author_plan", "text": "尚未发生的作者计划", "explanation_candidates": []}}
    for i, (subject, target, kind) in enumerate([("h-000", "dep", "experience"), ("h-068", "dep", "experience"), ("h-069", "plan", "hook")]):
        records[f"required-{i}"] = {"id": f"required-{i}", "record_kind": "link", "source_refs": [], "payload": {
            "relation_type": "required_context", "subject_ref": {"kind": "hook", "id": subject}, "object_ref": {"kind": kind, "id": target}}}
    pending = {"entry_id": "pending", "domain": "OpenCondition", "kind": "promise", "value": "尚待归还", "lifetime": "carry", "source_refs": []}
    first = route(records, [pending])
    second = route(records, [pending], candidate_search=first["candidate_search_state"])
    assert first["state_entries"] + second["state_entries"] == [pending]
    assert second["candidate_search"]["complete"]
    assert any(row["id"] == "h-068" for row in second["hooks"])
    assert any(row["id"] == "dep" for row in first["experiences"])
    assert any(row["id"] == "dep" for row in second["experiences"])
    assert not any(row["id"] in {"h-069", "plan"} for packet in (first, second) for row in packet["hooks"])
    assert any("作者材料" in gap for gap in second["gaps"])
    assert "plan" not in second["candidate_search_state"]["visited_ids"]


def test_current_working_view_requires_root_recall_instead_of_forging_candidate_cursor(navigation_runtime) -> None:
    """依赖：原context_binding/持续焦点。输入：超过64个明确焦点的工作集。输出：实时视图只给根查询入口，实际回执仍有候选cursor。实现：区分本次实时编译与原冻结tool_results身份。"""
    _, writer, run_id, ids = navigation_runtime
    arguments = {"focus": list(ids.values()), "query": "原焦点"}
    first = writer.harness_tool(run_id, "recall", arguments)
    assert first["candidate_search"]["next_arguments"] is not None
    state = context_binding(writer.store.load(run_id), writer.memory, writer.store, writer.tool_dispatcher(run_id).definitions())
    working = state["working_view"]
    assert working["candidate_search"]["next_arguments"] is None
    assert working["candidate_search"]["read_arguments"] == arguments
    assert working["read_arguments"] == arguments
