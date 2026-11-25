"""无默认 token 上限的真实工具、上下文与两种内置协议回归。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from native_http_fixture import NativeEndpoint
from novel_rag.composition import build_writer_service
from novel_rag.generation.context import WRITER_PROMPT, build_context
from novel_rag.graph.corpus import json_text
from novel_rag.identity import GraphKey, StoryCoordinate
from novel_rag.retrieval.assembler import estimate_tokens
from test_memory_service_v3 import _document_position, _formal_batch, _formal_record, _write_projection
from test_writer_session import _runtime, _text_response, _tool_response, _tool_outputs, _user_payload
from writer_fixtures import make_library, put_document


def test_default_recall_preserves_large_required_context_pack(tmp_path: Path) -> None:
    """依赖：真实源/MemoryService/规范批次fixtures。输入：超过12000的经历及必要前因。输出：默认完整包，显式小容量整包退出。实现：正式YAML投影经同一recall对照，无截断或新历史。"""
    root = make_library(tmp_path)
    put_document(root, "memory-origin", "正式来源：甲取得借用许可。")
    writer = build_writer_service(root, tmp_path / "workspace", tmp_path / "no-model.json")
    run_id = writer.prepare(GraphKey("demo", "main"), "write", "largepackmarker", "继续")
    source = writer.memory.corpus(writer.store.load(run_id)).source_refs["memory-origin"].as_dict()
    position = _document_position(StoryCoordinate(1, 1, 1))
    result_text, cause_text = "largepackmarker: " + "甲" * 9000, "必要借用条件：" + "乙" * 9000
    experiences = [
        _formal_record("large-result", "experience", {"text": result_text}, source, position),
        _formal_record("large-cause", "experience", {"text": cause_text}, source, position),
    ]
    link = _formal_record("large-required", "link", {
        "relation_type": "required_context",
        "subject_ref": {"kind": "experience", "id": "large-result"},
        "object_ref": {"kind": "experience", "id": "large-cause"},
    }, source, position)
    _write_projection(root, _formal_batch(source, experiences=experiences, links=[link]))
    before = writer.store.load(run_id)

    packet = writer.harness_tool(run_id, "recall", {"query": "largepackmarker"})
    bounded = writer.memory.recall(run_id, query="largepackmarker", available_tokens=2048)

    assert {row["id"]: row["payload"]["text"] for row in packet["experiences"]} == {
        "large-result": result_text, "large-cause": cause_text}
    assert estimate_tokens(json_text(packet)) > 12000
    assert not any("预算" in gap for gap in packet["gaps"])
    assert "large-result" not in {row["id"] for row in bounded["experiences"]}
    assert any("整包" in gap for gap in bounded["gaps"])
    assert writer.store.load(run_id)["memory_batches"] == before["memory_batches"]


def test_explicit_recall_capacity_counts_complete_character_claim(tmp_path: Path) -> None:
    """依赖：真实五工具/整包估算。输入：1000字人物声称和2048显式容量。输出：默认全文，受限包不超过容量且不截value。实现：保存真实检查点后比较两条召回路径。"""
    writer = build_writer_service(make_library(tmp_path), tmp_path / "workspace", tmp_path / "no-model.json")
    run_id = writer.prepare(GraphKey("demo", "main"), "write", "甲的声称", "继续")
    draft = writer.harness_tool(run_id, "save_draft", {"text": "甲作出了声称。", "expected_revision": 0}, "save")
    value = "证" * 1000
    result = writer.harness_tool(run_id, "remember", {"draft_ref": draft, "expected_memory_revision": 0,
        "update": {"state_changes": [{"op": "set", "local_ref": "testimony", "entry": {
            "domain": "CharacterView", "kind": "claim", "holder": "甲", "value": value, "lifetime": "carry"}}]}}, "remember")
    focus = [result["local_ref_to_stable_id"]["testimony"]]

    full = writer.memory.recall(run_id, focus=focus)
    bounded = writer.memory.recall(run_id, focus=focus, available_tokens=2048)

    assert full["state_view"]["entries"][0]["value"] == value
    assert full["state_view"]["claims"][0]["value"] == value
    assert estimate_tokens(json_text(full)) > 2048
    assert estimate_tokens(json_text(bounded)) <= 2048
    assert bounded["state_view"]["entries"] == bounded["state_view"]["claims"] == []


def test_default_recall_returns_all_matching_originals_inside_scope(tmp_path: Path) -> None:
    """依赖：SourceCorpus.search/五工具。输入：十份相关Canon和其他书同词资料。输出：默认全部本书命中，旧显式条数仍有效。实现：真实YAML范围过滤并核对超过旧预算的完整来源片段。"""
    root = make_library(tmp_path)
    expected = {f"matched-{index}" for index in range(10)}
    for document_id in sorted(expected):
        put_document(root, document_id, "targetmarker: " + "甲" * 400, category="canon")
    put_document(root, "foreign-match", "targetmarker: 其他作品的私有正文。", story="other", category="canon")
    writer = build_writer_service(root, tmp_path / "workspace", tmp_path / "no-model.json")
    run_id = writer.prepare(GraphKey("demo", "main"), "write", "targetmarker", "继续")
    corpus = writer.memory.corpus(writer.store.load(run_id))

    packet = writer.harness_tool(run_id, "recall", {"query": "targetmarker"})

    assert {row["document_id"] for row in packet["references"]} == expected
    assert estimate_tokens(json_text(packet)) > 2048
    assert len(corpus.search("targetmarker")) == 8
    assert {row["document_id"] for row in corpus.search("targetmarker", limit=None)} == expected


def test_open_condition_claim_is_not_a_character_claim(tmp_path: Path) -> None:
    """依赖：五工具/StateView领域合同。输入：kind同名的未完成赔偿诉求。输出：OpenCondition保留且claims为空。实现：真实remember/recall验证预算装配未改变领域分类。"""
    writer = build_writer_service(make_library(tmp_path), tmp_path / "workspace", tmp_path / "no-model.json")
    run_id = writer.prepare(GraphKey("demo", "main"), "write", "赔偿", "继续")
    draft = writer.harness_tool(run_id, "save_draft", {"text": "乙要求赔偿，甲尚未回应。", "expected_revision": 0}, "save")
    writer.harness_tool(run_id, "remember", {"draft_ref": draft, "expected_memory_revision": 0,
        "update": {"state_changes": [{"op": "set", "local_ref": "petition", "entry": {
            "domain": "OpenCondition", "kind": "claim", "value": "乙的赔偿诉求待回应。", "lifetime": "carry"}}]}}, "remember")

    packet = writer.harness_tool(run_id, "recall", {"query": "赔偿"})

    assert [row["domain"] for row in packet["state_view"]["entries"]] == ["OpenCondition"]
    assert packet["state_view"]["claims"] == []


def test_explicit_context_capacity_keeps_memory_or_reports_limit(tmp_path: Path) -> None:
    """依赖：真实build_context/Store/五工具。输入：大纲超过旧12000及两种显式容量。输出：成功总有memory，容量不足明确拒绝且输入保留。实现：默认完整装配后按真实序列化成本对照调用。"""
    writer = build_writer_service(make_library(tmp_path), tmp_path / "workspace", tmp_path / "no-model.json")
    outline = "甲" * 13000
    run_id = writer.prepare(GraphKey("demo", "main"), "write", outline, "继续")
    run = writer.store.load(run_id)
    definitions = writer.tool_dispatcher(run_id).definitions()
    messages = build_context(run, writer.memory, writer.store, definitions)
    payload = json.loads(messages[1]["content"])
    capacity = estimate_tokens(WRITER_PROMPT + json_text(payload) + json_text(definitions)) + 128

    fits = build_context(run, writer.memory, writer.store, definitions, context_tokens=capacity)
    with pytest.raises(ValueError, match="context_limit"):
        build_context(run, writer.memory, writer.store, definitions, context_tokens=2048)

    assert payload["outline_original"] == outline and "memory" in payload
    assert "memory" in json.loads(fits[1]["content"])
    assert estimate_tokens(WRITER_PROMPT + fits[1]["content"] + json_text(definitions)) <= capacity
    assert writer.store.load(run_id)["request_snapshot"]["outline"] == outline


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_native_writer_accepts_large_context_without_injecting_unrelated_prose(tmp_path: Path, mode: str) -> None:
    """依赖：真实RunService/NativeEndpoint/两协议fixtures。输入：大纲超过12000/明确基线及十章无关正文。输出：原纲按真实Ref完整回读、无关正文不注入。实现：录制model首包、作者输入读取和recall后的原生请求。"""
    async def scenario() -> None:
        """依赖：真实异步会话与已有端点脚本。输入：原纲读取/recall和终稿turn。输出：实际请求及完整原文断言。实现：两协议三轮录制验证，薄交付不能伪造完整输入。"""
        root = make_library(tmp_path)
        for index in range(10):
            put_document(root, f"unrelated-{index}", f"ZEBRA_UNRELATED_PROSE_{index}", chapter=1, scene=index + 1)
        put_document(root, "related-canon", "keymarker: 旧钥匙能打开铁门。", category="canon",
                     extra_metadata={"entity_ids": ["actor_a"]})
        put_document(root, "selected-base", "BASE_PROSE_KEEP: 门口留着一把旧钥匙。", chapter=2, scene=1,
                     extra_metadata={"entity_ids": ["actor_a"]})
        outline = "keymarker\n" + "甲" * 13000
        calls = [{"call_id": "large-context-recall", "name": "recall", "arguments": {"query": "keymarker"}}]
        def read_outline(record: dict) -> dict:
            """依赖：原生context codec。输入：实际首请求。输出：携带真实InputRef的读取工具turn。实现：复制来源而不猜run ID，显式窗口足以读本夹具全文。"""
            context = _user_payload(record["body"], mode)
            return _tool_response(mode, [{"call_id": "large-input-read", "name": "read_document",
                                         "arguments": {"source_ref": context["author_inputs"]["outline"]["source_ref"], "max_characters": 20000}}])

        def recall_after_outline(record: dict) -> dict:
            """依赖：原生工具输出codec。输入：实际作者输入回执。输出：recall turn。实现：先验证全文逐字一致且类型为author_input，再查询本书参考。"""
            returned = _tool_outputs(record["body"], mode)["large-input-read"]
            assert returned["text"] == outline and returned["kind"] == "author_input"
            assert returned["delivery_complete"] is True
            return _tool_response(mode, calls)

        with NativeEndpoint([
            {"mode": mode, "callback": read_outline},
            {"mode": mode, "callback": recall_after_outline},
            {"mode": mode, **_text_response(mode, "甲拿起旧钥匙，推开铁门。")},
        ]) as endpoint:
            writer, _store, _memory, _config = _runtime(root, tmp_path / "workspace", endpoint, mode)
            run_id = writer.start(GraphKey("demo", "main"), "write", outline, "沿钥匙线索继续", profile_name="fixture")

            result = await writer.run(run_id)

            assert result["status"] == "completed"
            assert len(endpoint.requests) == 3
            context = _user_payload(endpoint.requests[0]["body"], mode)
            assert context["outline_original"] is None
            assert context["author_inputs"]["outline"]["total_characters"] == len(outline)
            assert context["author_inputs"]["outline"]["inline"] is False
            assert "BASE_PROSE_KEEP" in context["body_context"]
            assert any(row["document_id"] == "related-canon" for row in context["references"])
            assert context["baseline"]["source_ref"]["document_id"] == "selected-base"
            assert all("text" not in row for row in context["references"])
            assert all(any(entity["entity_id"] == "actor_a" for entity in row["entity_refs"])
                       for row in context["references"] if row["document_id"] in {"related-canon", "selected-base"})
            assert "ZEBRA_UNRELATED_PROSE" not in json_text(endpoint.requests)
            assert estimate_tokens(json_text(endpoint.requests[0]["body"])) < 12000
            assert all(estimate_tokens(json_text(row["body"])) > 12000 for row in endpoint.requests[1:])
            assert endpoint.callback_errors == []

    asyncio.run(scenario())
