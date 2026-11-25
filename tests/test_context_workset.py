"""焦点模型视图、完整必要包及原结果恢复；使用既有临时作品，不调用LLM。"""
import json

import pytest

from novel_rag.generation.context import active_recall_selection, build_context, context_binding, result_source_refs, semantic_result_page
from novel_rag.identity import GraphKey
from novel_rag.memory.router import route
from novel_rag.model_api import ToolCall
from test_context_delivery import delivery_runtime, read_pages
from writer_fixtures import put_document


def test_semantic_delivery_preserves_discovery_reason_on_units_and_oversize():
    """依赖：semantic_result_page原包投影。输入：未确认对应的线索候选及交付窗。输出：正常/过大包入口均保留原候选理由。实现：交付不能将弱候选变为确认的相关事实。"""
    reason = {"record_id": "old-clue", "reason": "线索候选（未确认对应）", "pack_ids": ["old-clue"]}
    packet = {"memory_revision": 1, "hooks": [{"id": "old-clue", "payload": {"nature": "unresolved", "text": "旧刻痕"}}],
              "selection_reasons": [reason], "state_view": {}, "gaps": []}
    page = semantic_result_page(packet, "discovery-call", page_characters=4096)
    assert page["units"][0]["selection_reasons"] == [reason]
    small = semantic_result_page(packet, "discovery-call", page_characters=1)
    assert small["undelivered"][0]["selection_reasons"] == [reason]
    assert not small["undelivered"][0]["evidence_complete"]


@pytest.mark.parametrize("field", ["holder", "target"])
def test_actor_state_precedes_ordinary_matching_seeds(field):
    """依赖：真实router。输入：80同词普通节点及人物状态。输出：64访问限制前保留holder/target焦点与原information。实现：重现旧状态ID靠后被挤掉的反例。"""
    records = {f"ordinary-{i:03}": {"id": f"ordinary-{i:03}", "record_kind": "note", "payload": {"text": "marker"}, "source_refs": []}
               for i in range(80)}
    state = {"entry_id": "zz-belief", "domain": "CharacterView", "kind": "belief", "value": "marker:旧广播仍说桥关闭", field: "actor_zhou",
             "information": {"channel": "广播", "source": None, "certainty": "听闻", "basis": "只听到旧节目"}}
    packet = route(records, [state], focus=["actor_zhou"], query="marker")
    assert packet["state_entries"] == [state]
    assert any("访问上限" in gap for gap in packet["gaps"])


def test_selection_presence_failure_temporary_and_clear():
    """依赖：原调用选择派生。输入：替换/省略/空值/失败/续页/旧行。输出：持续选择稳定且可清空。实现：按调用序模拟持久原行，区别真实presence和补默认参数。"""
    rows = [{"name": "recall", "call_id": "legacy", "result": {}},
            {"name": "recall", "call_id": "one", "arguments": {"focus": ["a"], "query": "桥"}, "result": {}},
            {"name": "recall", "call_id": "temporary", "arguments": {"query": "乙的报道"}, "result": {}},
            {"name": "recall", "call_id": "failed", "arguments": {"focus": ["b"]}, "result": {"ok": False}},
            {"name": "recall", "call_id": "page", "arguments": {"continuation": {}}, "result": {"delivery": "frozen_json_page"}}]
    assert active_recall_selection({"tool_results": rows}) == {"focus": ["a"], "query": "桥", "invocation_key": "one"}
    rows.append({"name": "recall", "call_id": "replace", "arguments": {"focus": ["a", "b"]}, "result": {}})
    assert active_recall_selection({"tool_results": rows})["query"] == ""
    rows.append({"name": "recall", "call_id": "clear", "arguments": {"focus": [], "query": "临时"}, "result": {}})
    assert active_recall_selection({"tool_results": rows}) is None


def test_semantic_page_keeps_required_pack_and_oversize_advances():
    """依赖：共同语义投影。输入：结果/必要前因、巨型包及独立后项。输出：完整包不拆；过大包游标前进且原JSON可恢复。实现：同原packet按两种窗口检查包完整性和知识字段。"""
    prerequisite = {"entry_id": "known", "domain": "CharacterView", "kind": "unknown", "holder": "a", "value": "暗槽位置未知",
                    "narrative_position": {"kind": "draft", "checkpoint_id": "point"}, "information": {"source": None, "certainty": "未知"}}
    result = {"memory_revision": 2, "state_view": {"entries": [prerequisite], "coverage": "bound"},
              "experiences": [{"id": "result", "payload": {"text": "门前等候"}}], "notes": [{"id": "later", "payload": {"text": "后项"}}],
              "selection_reasons": [{"record_id": "result", "pack_ids": ["result", "known"]}], "references": [], "gaps": []}
    page = semantic_result_page(result, "attempt-key", page_characters=4096)
    package = next(unit for unit in page["units"] if "result" in unit["record_ids"])
    assert set(package["record_ids"]) == {"result", "known"} and package["evidence_complete"]
    assert next(row["record"] for row in package["records"] if row["kind"] == "entries") == prerequisite
    result["experiences"][0]["payload"]["text"] = "雨" * 6000
    page = semantic_result_page(result, "attempt-key", page_characters=1000)
    assert not page["delivery_complete"] and page["undelivered"][0]["evidence_complete"] is False
    assert page["next_arguments"]["continuation"]["index"] == 1
    assert "start_character" in page["undelivered"][0]["read_arguments"]["continuation"]
    following = semantic_result_page(result, "attempt-key", index=1, page_characters=1000)
    assert following["units"][0]["record_ids"] == ["later"]


def test_binding_only_checks_explicit_current_materials(delivery_runtime):
    """依赖：真实Memory快照及context绑定。输入：prepare后新增查询源/旧日志/本窗口材料。输出：显式材料能发现失效，旧历史不造成持续renew。实现：实际读取/改写来源并对照两份manifest。"""
    root, writer, run_id = delivery_runtime
    put_document(root, "late-only", "独立资料", category="canon")
    read = writer.harness_tool(run_id, "read_document", {"document_id": "late-only"})
    definitions = writer.tool_dispatcher(run_id).definitions()
    before = context_binding(writer.store.load(run_id), writer.memory, writer.store, definitions, delivered_results=[read])
    assert any(row["source_ref"] == read["source_ref"] and row["status"] == "valid" for row in before["manifest"]["materials"])
    put_document(root, "late-only", "已改写的独立资料", category="canon")
    after = context_binding(writer.store.load(run_id), writer.memory, writer.store, definitions, delivered_results=[read])
    assert any(row["source_ref"] == read["source_ref"] and row["status"] == "stale" for row in after["manifest"]["materials"])
    fresh = context_binding(writer.store.load(run_id), writer.memory, writer.store, definitions)
    assert read["source_ref"] not in fresh["material_refs"]
    payload = json.loads(build_context(fresh["run"], writer.memory, writer.store, definitions, view="model", context_state=fresh)[1]["content"])
    assert payload["snapshot_semantics"] == "attempt_initial_snapshot"


def test_model_semantic_default_and_explicit_json_compatibility(delivery_runtime):
    """依赖：实际harness工具/原冻结结果。输入：同查询语义默认与显式字符窗。输出：模型可读语义、旧JSON可续，非法投影拒绝。实现：只用现有作品和真实工具回执，保留内部键定位。"""
    _, writer, run_id = delivery_runtime
    semantic = writer.harness_tool(run_id, "recall", {"query": "bridge-marker"}, delivery="model")
    assert semantic["delivery"] == "frozen_semantic_page"
    legacy = writer.harness_tool(run_id, "recall", {"query": "bridge-marker", "page_characters": 80}, delivery="model")
    assert legacy["delivery"] == "frozen_json_page"
    following = writer.harness_tool(run_id, "recall", legacy["next_arguments"], delivery="model")
    assert following["character_range"][0] == 80
    cursor = dict(semantic["result_ref"], index=0, projection_version=99)
    rejected = writer.harness_tool(run_id, "recall", {"continuation": cursor}, delivery="model")
    assert rejected["ok"] is False and "projection_version" in rejected["error"]["message"]


def test_runtime_workset_survives_temporary_lookup_and_clears(delivery_runtime):
    """依赖：真实save/remember/recall/模型编译。输入：World开放与人物旧误信、临时查询和清空。输出：刷新工作集保持原性质/获知来源且选择可解除。实现：同run实际成功调用记录驱动，不额外存状态。"""
    _, writer, run_id = delivery_runtime
    draft = writer.harness_tool(run_id, "save_draft", {"text": "桥开放，甲仍只相信旧广播。", "expected_revision": 0}, "work-save")
    writer.harness_tool(run_id, "remember", {"draft_ref": draft, "expected_memory_revision": 0, "update": {"state_changes": [
        {"op": "set", "local_ref": "world", "entry": {"domain": "World", "kind": "bridge", "value": "桥已经开放", "lifetime": "carry"}},
        {"op": "set", "local_ref": "belief", "entry": {"domain": "CharacterView", "holder": "actor_a", "kind": "belief", "value": "桥仍关闭",
         "lifetime": "carry", "information": {"channel": "广播", "source": None, "certainty": "听闻", "basis": "只听过旧节目"}}}]}}, "work-remember")
    writer.harness_tool(run_id, "recall", {"focus": ["actor_a"], "query": "桥"}, delivery="model")
    writer.harness_tool(run_id, "recall", {"query": "另一篇文章"}, delivery="model")
    payload = json.loads(writer.harness_context(run_id, view="model")["messages"][1]["content"])
    assert payload["working_selection"]["focus"] == ["actor_a"]
    entries = [item["record"] for unit in payload["working_set"]["units"] for item in unit.get("records", []) if item["kind"] == "entries"]
    belief = next(row for row in entries if row["domain"] == "CharacterView")
    assert belief["information"]["source"] is None and belief["kind"] == "belief" and belief["narrative_position"]
    assert any(row["domain"] == "World" for row in entries)
    writer.harness_tool(run_id, "recall", {"focus": []}, delivery="model")
    cleared = json.loads(writer.harness_context(run_id, view="model")["messages"][1]["content"])
    assert "working_set" not in cleared


def test_free_values_do_not_become_material_refs(delivery_runtime):
    """依赖：声明式来源提取。输入：真实Ref与同名自由value/information/error字段。输出：仅协议来源进入绑定。实现：用异形资料证明不递归提升世界内叙述权限。"""
    _, writer, run_id = delivery_runtime
    ref = writer.store.load(run_id)["binding"]["base_ref"]
    assert result_source_refs({"value": {"source_ref": ref}, "information": {"source_ref": ref}, "error": {"source_ref": ref}}) == []
    assert result_source_refs({"source_ref": ref, "payload": {"source_refs": [ref]}}) == [ref]


def test_partial_public_turn_is_readable_without_fact_reference(delivery_runtime):
    """依赖：Store公开接收前缀与原read_document。输入：未完成公开文本及技术读取。输出：精确可续且没有正文Ref，hash变化拒绝。实现：不自动保存草稿、不读取推理。"""
    _, writer, run_id = delivery_runtime
    writer.store.receive(run_id, "public-pending", "未完成说明🙂" * 100)
    payload = json.loads(writer.harness_context(run_id, view="model")["messages"][1]["content"])
    descriptor = next(row for row in payload["technical_turns"] if row["turn_id"] == "public-pending")
    arguments = dict(descriptor["read_arguments"], max_characters=30)
    page = writer.harness_tool(run_id, "read_document", arguments, delivery="model")
    assert page["kind"] == "technical_turn" and page["source_ref"] is None and page["next_arguments"]["turn_id"] == "public-pending"
    writer.store.receive(run_id, "public-pending", "未完成说明🙂" * 101)
    stale = writer.harness_tool(run_id, "read_document", page["next_arguments"], delivery="model")
    assert stale["ok"] is False and stale["error"]["code"] == "revision_conflict"
    assert writer.store.load(run_id)["draft_ref"] is None


def test_technical_receipt_pages_preserve_original_operation(delivery_runtime):
    """依赖：实际写回执/共同技术读取。输入：长稿保存及其原调用键。输出：原行JSON精确恢复且不作为正文Ref。实现：转发返回续页，核验原参数、回执及无重复草稿。"""
    _, writer, run_id = delivery_runtime
    text = "甲在桥边等候。" * 200
    draft = writer.harness_tool(run_id, "save_draft", {"text": text, "expected_revision": 0}, "receipt-save")
    payload = json.loads(writer.harness_context(run_id, view="model")["messages"][1]["content"])
    card = next(row for row in payload["technical_operations"] if row["draft_ref"] == draft)
    arguments, fragments = dict(card["read_arguments"], max_characters=100), []
    while arguments:
        page = writer.harness_tool(run_id, "read_document", arguments, delivery="model")
        assert page["source_ref"] is None and page["kind"] == "technical_receipt"
        fragments.append(page["text"])
        arguments = page["next_arguments"]
    receipt = json.loads("".join(fragments))
    assert receipt["result"] == draft and receipt["arguments"]["text"] == text
    assert writer.store.load(run_id)["draft_revision"] == 1


def test_read_long_outline_history_does_not_claim_new_window_contains_it(delivery_runtime):
    """依赖：真实原纲分页/共同绑定与新首包。输入：含CRLF/Unicode末段约束的长纲读完。输出：历史完整交付仍需在新窗口重读，原任务逐字保留。实现：转发原读取页，检查实际范围与新head分离，不运行模型。"""
    _, writer, _ = delivery_runtime
    outline = "原路线🙂\r\n" * 800 + "末段约束：真实身份保持未揭示。"
    run_id = writer.prepare(GraphKey("demo", "main"), "write", outline, "")
    original = json.loads(writer.harness_context(run_id, view="model")["messages"][1]["content"])
    assert original["author_inputs"]["outline"]["current_included_range"] == []
    assert original["author_inputs"]["request"]["current_included_range"] == [0, 0]
    actual, pages = read_pages(writer, run_id, original["author_inputs"]["outline"]["read_arguments"])
    assert actual == outline and pages[-1]["next_arguments"] is None
    state = context_binding(writer.store.load(run_id), writer.memory, writer.store, writer.tool_dispatcher(run_id).definitions())
    coverage = state["recovery_materials"]["author_inputs"]["outline"]
    assert coverage["current_included_range"] == [] and coverage["needs_read"] and coverage["needs_reread"]
    assert coverage["historical_delivered"] == [{"attempt_id": None, "range_basis": "source_characters", "paragraph_range": [1, 1],
                                               "character_ranges": [[0, len(outline)]], "read_count": len(pages), "observation": "persisted_tool_delivery"}]
    rebuilt = json.loads(build_context(state["run"], writer.memory, writer.store, writer.tool_dispatcher(run_id).definitions(),
                                      view="model", context_state=state)[1]["content"])
    assert rebuilt["outline_original"] is None and rebuilt["author_inputs"]["outline"] == coverage
    again, _ = read_pages(writer, run_id, coverage["read_arguments"])
    assert again == outline and writer.store.load(run_id)["draft_ref"] is None


def test_author_paragraph_selection_keeps_relative_delivery_coordinates(delivery_runtime):
    """依赖：真实段落读取与输入覆盖。输入：只读长纲第二段一页。输出：选区相对范围，不伪称全文前20字已交付。实现：读页返回范围直接进入覆盖卡，整纲仍按原Ref可达。"""
    _, writer, _ = delivery_runtime
    outline = "第一段" * 900 + "\n\n" + "第二段" * 800 + "\n\n末段身份约束。"
    run_id = writer.prepare(GraphKey("demo", "main"), "write", outline, "写下一节。")
    ref = next(ref for ref in writer.store.load(run_id)["binding"]["input_snapshot_refs"] if ref["input_slot"] == "outline")
    page = writer.harness_tool(run_id, "read_document", {"source_ref": ref, "start_paragraph": 2, "end_paragraph": 2, "max_characters": 20})
    payload = json.loads(writer.harness_context(run_id, view="model")["messages"][1]["content"])
    coverage = payload["author_inputs"]["outline"]
    assert page["text"] == ("第二段" * 800)[:20]
    assert coverage["historical_delivered"][0]["range_basis"] == "selected_paragraphs"
    assert coverage["historical_delivered"][0]["character_ranges"] == [[0, 20]]
    assert coverage["historical_delivered"][0]["paragraph_range"] == [2, 2]
    assert coverage["current_included_range"] == [] and coverage["needs_reread"]


def test_default_recovery_identifies_original_pending_and_commit_without_receipt(delivery_runtime):
    """依赖：原turn/内部键/Store提交与共同读取。输入：提交后缺回执行及同provider ID新attempt未执行。输出：原已知回执/未决意图分开，原参数可恢复且不泄推理。实现：临时库模拟持久窗口，不重放写入。"""
    _, writer, run_id = delivery_runtime
    arguments = {"text": "确定落盘的旧稿。", "expected_revision": 0}
    call_id = "provider/shared:id"
    writer.store.prepare_turn(run_id, "turn-old", "attempt-old", {})
    writer.store.commit_turn(run_id, "turn-old", {"text": "公开说明。", "tool_calls": [{"call_id": call_id, "name": "save_draft", "arguments": arguments}],
                                                   "continuation": [{"type": "reasoning", "opaque": "HIDDEN_OPAQUE"}]})
    committed_key = writer.store.invocation_key("attempt-old", call_id)
    draft = writer.execute_tool(run_id, ToolCall(committed_key, "save_draft", arguments), attempt_id="attempt-old",
                                provider_call_id=call_id, turn_id="turn-old")
    with writer.store.lock:
        run = writer.store.load(run_id)
        run["tool_results"] = []
        writer.store.write(run)
    new_arguments = {"text": "尚未执行的下一稿。", "expected_revision": 1}
    writer.store.prepare_turn(run_id, "turn-new", "attempt-new", {})
    writer.store.commit_turn(run_id, "turn-new", {"text": "未执行的公开计划。", "tool_calls": [{"call_id": call_id, "name": "save_draft", "arguments": new_arguments}]})
    pending_key = writer.store.invocation_key("attempt-new", call_id)
    payload = json.loads(writer.harness_context(run_id, view="model")["messages"][1]["content"])
    committed = next(card for card in payload["technical_operations"] if card["invocation_key"] == committed_key)
    pending = next(card for card in payload["technical_operations"] if card["invocation_key"] == pending_key)
    assert committed["effect_status"] == "committed" and not committed["pending"] and committed["draft_ref"] == draft
    assert committed["provider_call_id"] == pending["provider_call_id"] == call_id and committed_key != pending_key
    assert pending["effect_status"] == "unknown" and pending["pending"] and pending["attempt_id"] == "attempt-new"
    assert "HIDDEN_OPAQUE" not in json.dumps(payload, ensure_ascii=False)
    for card, expected in ((committed, arguments), (pending, new_arguments)):
        text, pages = read_pages(writer, run_id, card["read_arguments"])
        receipt = json.loads(text)
        assert receipt["arguments"] == expected and all(page["source_ref"] is None for page in pages)
        assert receipt["invocation_key"] == card["invocation_key"]
    assert writer.store.load(run_id)["draft_revision"] == 1


def test_oversized_workset_head_gives_real_recall_entry(delivery_runtime):
    """依赖：真实记忆写入/焦点/共同模型首包。输入：超过交付窗的完整人物条目。输出：首包不回退全量注入，未交付包仍可同recall恢复。实现：真实长value保存在原批次，检查工作集导览和原查询入口。"""
    _, writer, run_id = delivery_runtime
    text = "桥边长信只交给甲，乙未读。" * 600
    draft = writer.harness_tool(run_id, "save_draft", {"text": text, "expected_revision": 0}, "oversize-save")
    writer.harness_tool(run_id, "remember", {"draft_ref": draft, "expected_memory_revision": 0, "update": {"state_changes": [
        {"op": "set", "local_ref": "long-belief", "entry": {"domain": "CharacterView", "holder": "actor_a", "kind": "belief",
         "value": text, "lifetime": "carry", "information": {"channel": "书信", "source": None, "certainty": "听闻", "basis": "甲读信"}}}]}}, "oversize-remember")
    writer.harness_tool(run_id, "recall", {"focus": ["actor_a"], "query": "长信"}, delivery="model")
    payload = json.loads(writer.harness_context(run_id, view="model")["messages"][1]["content"])
    workset = payload["working_set"]
    assert workset["undelivered"] and not workset["delivery_complete"]
    assert workset["undelivered"][0]["read_arguments"] == {"focus": ["actor_a"], "query": "长信"}
    assert text not in json.dumps(payload, ensure_ascii=False)
    packet = writer.memory.recall(run_id, focus=["actor_a"], query="长信")
    assert text == next(row["value"] for row in packet["state_view"]["entries"] if row.get("holder") == "actor_a")
