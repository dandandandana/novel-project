"""信息迷雾的实际工具/来源/采用回归；不模拟人物理解或调用真实模型。"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

import pytest

from native_http_fixture import NativeEndpoint
from novel_rag.composition import build_writer_service
from novel_rag.config import validate_memory_metadata
from novel_rag.documents import read_yaml_mapping
from novel_rag.generation.context import INFORMATION_FOG_PROMPT
from novel_rag.generation.store import DraftStore
from novel_rag.generation.tools import writing_resources
from novel_rag.generation.types import NarrativeCursor, RunBinding
from novel_rag.graph.corpus import json_text
from novel_rag.identity import GraphKey, StoryCoordinate
from novel_rag.memory.service import MemoryService
from novel_rag.writeback.adopt import AdoptionService
from test_writer_session import _runtime, _text_response, _tool_outputs, _tool_response
from writer_fixtures import make_library


@pytest.fixture
def information_runtime(tmp_path: Path):
    """依赖：既有临时库/真实RunService。输入：隔离目录。输出：库/服务/run/真实检查点。实现：无模型准备第三章并保存含转述和隐秘事实的正文。"""
    root = make_library(tmp_path)
    service = build_writer_service(root, tmp_path / "workspace", tmp_path / "no-model.json")
    run_id = service.prepare(GraphKey("demo", "main"), "write", "东岸来信", "继续",
                             target_coordinate=StoryCoordinate(1, 3, 1))
    ref = service.harness_tool(run_id, "save_draft", {
        "text": "甲读完密信，知道密道在井底。甲只对乙说东岸桥断了。丙虽同族，却未参与交谈。",
        "expected_revision": 0}, "save-information")
    return root, service, run_id, ref


@pytest.mark.parametrize("source", ["甲（乙所认知的身份）", None])
def test_information_roundtrips_with_acquisition_position_and_no_automatic_propagation(information_runtime, source) -> None:
    """依赖：真实remember/recall/采用/新Store。输入：明确转述范围与已知或未知来源。输出：信息完整往返、仅乙持有且章前不可见。实现：实际发布第三章后按before/after重读，旧条目不补来源，文件Ref与来源标签分开。"""
    root, writer, run_id, ref = information_runtime
    information = {"channel": "当面转述", "source": source, "certainty": "听闻，尚未核验",
                   "basis": "乙在场听到甲只说桥断；未听到密道位置，丙缺席。"}
    arguments = {"draft_ref": ref, "expected_memory_revision": 0, "update": {"state_changes": [
        {"op": "set", "local_ref": "bridge-news", "entry": {"domain": "CharacterView", "kind": "belief",
            "holder": "actor_b", "value": "东岸桥可能断了。", "lifetime": "carry", "information": information}},
        {"op": "set", "local_ref": "secret", "entry": {"domain": "World", "kind": "location",
            "value": "密道在井底。", "lifetime": "carry"}},
        {"op": "set", "local_ref": "legacy", "entry": {"domain": "CharacterView", "kind": "knowledge",
            "holder": "actor_a", "value": "甲知道密道位置。", "lifetime": "carry"}}]}}
    result = writer.harness_tool(run_id, "remember", arguments, "remember-information")
    assert result["memory_revision"] == 1
    assert writer.harness_tool(run_id, "remember", arguments, "remember-information") == result
    packet = writer.harness_tool(run_id, "recall", {"focus": ["actor_b", "actor_a"], "query": "东岸 密道"})
    entries = {row["entry_id"]: row for row in packet["state_view"]["entries"]}
    entry_id = result["local_ref_to_stable_id"]["bridge-news"]
    assert entries[entry_id]["information"] == information
    assert entries[entry_id]["source_refs"] == [ref]
    assert entries[entry_id]["narrative_position"] == {"kind": "draft", "checkpoint_id": ref["checkpoint_id"]}
    assert "密道" not in entries[entry_id]["value"]
    assert {row.get("holder") for row in entries.values() if row["domain"] == "CharacterView"} == {"actor_a", "actor_b"}
    assert "information" not in entries[result["local_ref_to_stable_id"]["legacy"]]

    adopted = AdoptionService(root, writer.store, writer.memory).adopt(run_id, 1, None, StoryCoordinate(1, 3, 1), "adopt-information")
    assert adopted["memory_state"] == "complete"
    summary_file = next((root / "stories" / "demo" / "timelines" / "main" / "summaries").glob("memory-*.yaml"))
    metadata = read_yaml_mapping(summary_file)["metadata"]
    assert validate_memory_metadata(metadata) == []
    formal_entry = metadata["memory_batches"][0]["update"]["state_changes"][0]["entry"]
    assert formal_entry["information"] == information
    assert formal_entry["source_refs"] == [adopted["source_ref"]]
    assert formal_entry["narrative_position"] == {"kind": "document", "endpoint": "after",
                                                "coordinate": {"volume": 1, "chapter": 3, "scene": 1}}
    invalid_metadata = deepcopy(metadata)
    invalid_metadata["memory_batches"][0]["update"]["state_changes"][0]["entry"]["information"]["source"] = {"kind": "draft"}
    assert any("information.source" in error for error in validate_memory_metadata(invalid_metadata))
    invalid_metadata = deepcopy(metadata)
    invalid_metadata["memory_batches"][0]["update"]["state_changes"][0]["entry"]["learned_at"] = {"kind": "draft", "claimed_point": "第一章之前"}
    assert any("state entry未知字段" in error for error in validate_memory_metadata(invalid_metadata))

    store = DraftStore(writer.store.root)
    memory = MemoryService(root, store)
    for endpoint, visible in (("before", False), ("after", True)):
        reader = store.create(RunBinding(scope=GraphKey("demo", "main"), task_kind="scene",
            narrative_cursor=NarrativeCursor(endpoint, StoryCoordinate(1, 3, 1)), base_ref=None,
            draft_branch="information-reader"), "东岸桥", "查询")
        rows = memory.recall(reader["run_id"], focus=["actor_b"], query="东岸桥")["state_view"]["entries"]
        selected = [row for row in rows if row["entry_id"] == entry_id]
        assert bool(selected) is visible
        if visible:
            assert selected[0]["information"] == information
            assert selected[0]["source_refs"] == [adopted["source_ref"]]


@pytest.mark.parametrize(("replacement", "error_path"), [
    ({"holder": ["actor_a", "actor_b"]}, "holder"),
    ({"kind": ["belief"]}, "kind"),
    ({"target": {"id": "actor_a"}}, "target"),
    ({"information": "错误对象"}, "information"),
    ({"domain": "World"}, "仅供CharacterView"),
    ({"information": {"channel": "书信", "source": None, "basis": "只读到桥断。"}}, "certainty"),
    ({"information": {"channel": "书信", "source": {"kind": "draft"}, "certainty": "未核实", "basis": "只读到桥断。"}}, "source"),
    ({"information": {"channel": "书信", "source": None, "certainty": 99, "basis": "只读到桥断。"}}, "certainty"),
    ({"information": {"channel": "书信", "source": None, "certainty": "未核实", "basis": ""}}, "basis"),
    ({"information": {"channel": "书信", "source": None, "certainty": "未核实", "basis": "只读到桥断。", "learned_at": "第一章"}}, "未知字段"),
    ({"learned_at": {"kind": "draft", "claimed_point": "第一章之前"}}, "state entry未知字段"),
    ({"narrative_position": {"kind": "draft", "checkpoint_id": "自造检查点"}}, "state entry未知字段"),
])
def test_bad_information_or_identity_rejects_whole_batch_without_corrupting_recall(information_runtime, replacement, error_path) -> None:
    """依赖：实际工具提交表/唯一状态validator。输入：含合法项和坏身份/信息的同一批。输出：整批拒绝、无版本/批次/回执变化且recall可用。实现：保留真实正文，覆盖已复现list holder污染及嵌套来源/时点伪造。"""
    _root, writer, run_id, ref = information_runtime
    entry = {"domain": "CharacterView", "kind": "belief", "holder": "actor_b", "value": "桥可能断了。",
             "lifetime": "carry", "information": {"channel": "书信", "source": None, "certainty": "未核实", "basis": "只读到桥断。"}}
    entry.update(replacement)
    result = writer.harness_tool(run_id, "remember", {"draft_ref": ref, "expected_memory_revision": 0,
        "update": {"state_changes": [
            {"op": "set", "local_ref": "valid-first", "entry": {"domain": "World", "kind": "weather", "value": "下雨。", "lifetime": "carry"}},
            {"op": "set", "local_ref": "bad-second", "entry": entry}]}}, "remember-bad-information")
    assert result["ok"] is False and result["error"]["code"] == "source_invalid"
    assert error_path in result["error"]["message"]
    run = writer.store.load(run_id)
    assert run["memory_revision"] == 0 and run["memory_batches"] == [] and run["draft_ref"] == ref
    assert "harness:remember:remember-bad-information" not in run["tool_commits"]
    packet = writer.harness_tool(run_id, "recall", {"focus": ["actor_b"]})
    assert packet["state_view"]["entries"] == []


def test_selected_parent_checkpoint_excludes_information_received_later(information_runtime) -> None:
    """依赖：实际父检查点/MemoryService可见性。输入：早前缀与后来收到消息的第二检查点。输出：早父稿续写没有后来的人物认知。实现：同一父run真实追加、记忆，再从第一检查点准备子run。"""
    _root, writer, parent_id, early = information_runtime
    parent_text = writer.store.load(parent_id)["draft_text"]
    late = writer.harness_tool(parent_id, "save_draft", {"text": parent_text + "乙随后读到第二封信，才知道城门关闭。", "expected_revision": 1}, "save-later-letter")
    result = writer.harness_tool(parent_id, "remember", {"draft_ref": late, "expected_memory_revision": 0,
        "update": {"state_changes": [{"op": "set", "local_ref": "late-news", "entry": {
            "domain": "CharacterView", "kind": "belief", "holder": "actor_b", "value": "城门关闭。", "lifetime": "carry",
            "information": {"channel": "书信", "source": None, "certainty": "来信所述，未亲见",
                            "basis": "乙在第二检查点才实际读到信，不能在先前获知。"}}}]}}, "remember-later-letter")
    assert result["memory_revision"] == 1
    child_id = writer.prepare(GraphKey("demo", "main"), "write", "等待来信", "从较早稿继续", base_ref=early)
    assert writer.harness_tool(child_id, "recall", {"focus": ["actor_b"], "query": "城门"})["state_view"]["entries"] == []
    assert writer.harness_tool(parent_id, "recall", {"focus": ["actor_b"], "query": "城门"})["state_view"]["entries"][0]["information"]["source"] is None


def test_harness_context_exposes_information_rules_and_same_five_tool_schema(information_runtime) -> None:
    """依赖：实际harness_context及唯一dispatcher。输入：无模型run。输出：常驻规则、四项Schema及原五工具。实现：检查真实交接messages和可见声明，非只检查资源存在。"""
    _root, writer, run_id, _ref = information_runtime
    context = writer.harness_context(run_id)
    assert INFORMATION_FOG_PROMPT in context["messages"][0]["content"]
    assert "群体成员身份不授予全部内部信息" in context["messages"][0]["content"]
    assert "作者指定全知叙述" in context["messages"][0]["content"]
    assert {row["name"] for row in context["tools"]} == {"recall", "read_document", "read_writing_reference", "save_draft", "remember"}
    remember = next(row for row in context["tools"] if row["name"] == "remember")
    schema = remember["parameters"]["properties"]["update"]["properties"]["state_changes"]["items"]["properties"]["entry"]["properties"]["information"]
    assert set(schema["required"]) == {"channel", "source", "certainty", "basis"}
    assert schema["properties"]["source"]["type"] == ["string", "null"]
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_native_requests_receive_information_rules_and_on_demand_independent_reference(tmp_path: Path, mode: str) -> None:
    """依赖：真实NativeEndpoint/RunService及两协议。输入：读取信息传递参考后终稿。输出：实际请求包含边界和Schema，原文结构参考仅按需返回。实现：真实本地HTTP双turn检查，未调用模型或正式作品。"""
    async def scenario() -> None:
        """依赖：既有原生响应脚本/工具结果读取器。输入：信息参考调用和终稿。输出：线上装配/返回断言。实现：录制两轮请求并核验独立来源及未知/转述规则。"""
        calls = [{"call_id": "information-reference", "name": "read_writing_reference", "arguments": {"resource_id": "information_transmission"}}]
        with NativeEndpoint([{ "mode": mode, **_tool_response(mode, calls)},
                             {"mode": mode, **_text_response(mode, "乙收起信，只说桥断了，未提密道。") }]) as endpoint:
            writer, _store, _memory, _config = _runtime(make_library(tmp_path), tmp_path / "workspace", endpoint, mode)
            run_id = writer.start(GraphKey("demo", "main"), "write", "转述来信", "只传实际说出部分", profile_name="fixture")
            result = await writer.run(run_id)
            assert result["status"] == "completed"
            assert len(endpoint.requests) == 2 and endpoint.callback_errors == []
            first = json_text(endpoint.requests[0]["body"])
            assert "信息迷雾" in first and "共享信息不表示双方知道彼此也知道" in first
            assert "certainty" in first and "basis" in first
            assert "第八十三章" not in first
            observed = _tool_outputs(endpoint.requests[1]["body"], mode)["information-reference"]
            assert observed == writing_resources()["information_transmission"]
            assert observed["source"]["provided_fragment"] is False
            assert observed["source"]["asset"] == "docs/references/xuanjian-information-notes.md"
    asyncio.run(scenario())
