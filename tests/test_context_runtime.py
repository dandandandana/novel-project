"""Real RunService/context integration with native codecs and an in-memory HTTP transport."""
from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from typing import Callable

import httpx
import pytest

import novel_rag
from novel_rag.generation.session import RunService
from novel_rag.generation.store import DraftStore, StoreConflict
from novel_rag.identity import GraphKey
from novel_rag.memory.service import MemoryService
from novel_rag.model_api import OpenAICompatibleModel, ToolCall
from novel_rag.mutations.types import fingerprint_bytes
from writer_fixtures import make_library, put_document


_SOURCE_FILES = (
    "novel_rag/generation/session.py", "novel_rag/generation/store.py",
    "novel_rag/generation/context.py", "novel_rag/generation/tools.py",
    "novel_rag/model_api.py", "novel_rag/memory/service.py",
    "novel_rag/model_config/types.py", "novel_rag/model_config/store.py",
    "novel_rag/harness.py", "novel_rag/memory/router.py", "novel_rag/memory/schema.py",
)


class _ModelConfiguration:
    """Use the real native client without reading or writing a model configuration."""

    def __init__(self, model: OpenAICompatibleModel):
        """依赖：原生client。输入：fixture client。输出：配置适配。实现：只保存已装配对象。"""
        self.model = model

    def build_model(self, _profile_name=None) -> OpenAICompatibleModel:
        """依赖：已装配client。输入：兼容profile参数。输出：同一client。实现：不读取凭证或配置。"""
        return self.model


@dataclass
class _Runtime:
    root: Path
    store: DraftStore
    memory: MemoryService
    service: RunService
    model: OpenAICompatibleModel
    run_id: str
    requests: list[dict] = field(default_factory=list)
    script: Callable[[dict, int], dict | httpx.Response] | None = None

    def exchange(self, request: httpx.Request) -> httpx.Response:
        """依赖：HTTPX MockTransport/原生codec。输入：真正序列化的POST。输出：预设响应。实现：记录JSON，禁止外部网络和隐式多余调用。"""
        assert request.url.host == "fixture.invalid"
        assert request.method == "POST"
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        self.requests.append(body)
        assert self.script is not None, "native request was sent before assigning its script"
        result = self.script(body, len(self.requests))
        return result if isinstance(result, httpx.Response) else httpx.Response(200, json=result)

    def run(self) -> dict:
        """依赖：实际RunService。输入：当前fixture run。输出：最终安全快照/中断异常。实现：运行真实异步循环和持久化工具，不替换ModelTurn或业务owner。"""
        return asyncio.run(self.service.run(self.run_id))


def _source_hashes() -> dict[str, str]:
    """依赖：公共指纹/实际导入包。输入：无。输出：本轮相关源码hash或缺失错误。实现：逐项读取运行包实现，缺文件直接失败，不省略身份检查。"""
    root = Path(novel_rag.__file__).resolve().parent
    return {name: fingerprint_bytes((root / Path(name).relative_to("novel_rag")).read_bytes()) for name in _SOURCE_FILES}


@pytest.fixture
def runtime_factory(tmp_path: Path, monkeypatch, request):
    """依赖：共享writer_fixtures/原生HTTPX。输入：pytest隔离目录。输出：真实运行工厂。实现：仅替换网络transport，按需留下实际请求、Store及源码身份。"""
    runtimes: list[_Runtime] = []
    original_client = httpx.AsyncClient
    before = _source_hashes()

    def create(mode: str, *, task_kind: str = "write", **policy) -> _Runtime:
        """依赖：已有库夹具/Store/Memory/RunService。输入：原生协议和显式策略。输出：完整临时运行。实现：正式基线、作者输入和工具都走公共入口。"""
        root = make_library(tmp_path / mode)
        put_document(root, "base-history", "CURRENT_FORMAL_BASE", chapter=1)
        store = DraftStore(tmp_path / mode / "workspace")
        memory = MemoryService(root, store)
        model = OpenAICompatibleModel(base_url="https://fixture.invalid/v1", model="scripted-native",
                                      mode=mode, api_key=None, timeout=2, retries=7, **policy)
        service = RunService(root, store, memory, _ModelConfiguration(model))
        run_id = service.start(GraphKey("demo", "main"), task_kind,
                               "原纲🙂：沿作者路线继续，保留结尾约束。", "原要求：按真实来源写作。")
        runtime = _Runtime(root, store, memory, service, model, run_id)
        transport = httpx.MockTransport(runtime.exchange)

        def client(*args, **kwargs):
            """依赖：原HTTPX AsyncClient。输入：生产transport参数。输出：资源管理相同的client。实现：强制仅使用内存transport，无socket/外部HTTP。"""
            return original_client(*args, **kwargs, transport=transport)

        monkeypatch.setattr(httpx, "AsyncClient", client)
        runtimes.append(runtime)
        return runtime

    yield create
    artifact = os.environ.get("NOVEL_CONTEXT_RUNTIME_EVIDENCE")
    if artifact:
        directory = Path(artifact)
        directory.mkdir(parents=True, exist_ok=True)
        after = _source_hashes()
        payload = {"test": request.node.nodeid, "source_hashes_before": before,
                   "source_hashes_after": after, "source_snapshot_stable": before == after,
                   "runs": [{"mode": run.model.mode, "requests": run.requests,
                             "stored_run": run.store.load(run.run_id), "snapshot": run.store.snapshot(run.run_id)}
                            for run in runtimes]}
        name = re.sub(r"[^a-zA-Z0-9_.-]", "-", request.node.nodeid)
        (directory / (name + ".json")).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _reply(mode: str, *, calls: list[ToolCall] | None = None, text: str = "",
           opaque: str | None = None, length: bool = False) -> dict:
    """依赖：原生Chat/Responses公开格式。输入：预设工具、公开文本及合成opaque项。输出：独立JSON响应。实现：由生产codec解码，测试不伪造规范ModelTurn。"""
    calls = calls or []
    if mode == "chat":
        message = {"role": "assistant", "content": text or None}
        if calls:
            message["tool_calls"] = [{"id": call.call_id, "type": "function", "function": {
                "name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)}} for call in calls]
        return {"choices": [{"message": message, "finish_reason": "length" if length else "tool_calls" if calls else "stop"}],
                "usage": {"prompt_tokens": 17, "completion_tokens": 5}}
    output = []
    if opaque:
        output.append({"type": "reasoning", "id": "rs-fixture", "encrypted_content": opaque})
    if text:
        output.append({"type": "message", "id": "msg-fixture", "role": "assistant",
                       "content": [{"type": "output_text", "text": text}]})
    output.extend({"type": "function_call", "id": "fc-" + call.call_id, "call_id": call.call_id,
                   "name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)} for call in calls)
    return {"id": "resp-fixture", "status": "incomplete" if length else "completed", "output": output,
            "usage": {"input_tokens": 17, "output_tokens": 5}}


def _messages(body: dict, mode: str) -> list[dict]:
    """依赖：原生请求形状。输入：真实POST body/协议。输出：实际消息数组。实现：读取Chat messages或Responses input。"""
    return body["messages" if mode == "chat" else "input"]


def _context(body: dict, mode: str) -> dict:
    """依赖：共同编译公开JSON。输入：真实请求。输出：实际首个user上下文。实现：解析交付原文，不从内部helper推断发送。"""
    return json.loads(next(item["content"] for item in _messages(body, mode) if item.get("role") == "user"))


def _outputs(body: dict, mode: str) -> dict[str, dict]:
    """依赖：协议原ID/JSON。输入：实际后续请求。输出：按provider call_id的回执。实现：只解码真正发送的tool/function_call_output。"""
    if mode == "chat":
        return {item["tool_call_id"]: json.loads(item["content"]) for item in body["messages"] if item.get("role") == "tool"}
    return {item["call_id"]: json.loads(item["output"]) for item in body["input"] if item.get("type") == "function_call_output"}


def _assert_paired(body: dict, mode: str) -> None:
    """依赖：真实协议消息。输入：一个实际请求。输出：配对断言。实现：独立计数原call ID与结果，拒绝孤立调用/回执。"""
    messages = _messages(body, mode)
    if mode == "chat":
        calls = [call["id"] for item in messages if item.get("role") == "assistant" for call in item.get("tool_calls", [])]
        outputs = [item["tool_call_id"] for item in messages if item.get("role") == "tool"]
    else:
        calls = [item["call_id"] for item in messages if item.get("type") == "function_call"]
        outputs = [item["call_id"] for item in messages if item.get("type") == "function_call_output"]
    assert Counter(calls) == Counter(outputs)


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_author_rewrite_refreshes_next_native_request_and_preserves_author_selection(runtime_factory, monkeypatch, mode):
    """依赖：真实记忆/稿源和native循环。输入：读旧稿后作者改写。输出：下一请求无旧值且作者指针保留。实现：复制B原反例，在已完成工具边界修改临时稿。"""
    runtime = runtime_factory(mode)
    old_ref = runtime.store.save(runtime.run_id, 0, "OLD_RECORDED_DRAFT", origin="model").as_dict()
    remembered = runtime.memory.remember(runtime.run_id, "fixture-seed", draft_ref=old_ref, expected_memory_revision=0,
        update={"state_changes": [{"op": "set", "local_ref": "old-state", "entry": {
            "domain": "World", "kind": "condition", "value": "OLD_CURRENT_CONDITION", "lifetime": "carry"}}]})
    entry_id = remembered["local_ref_to_stable_id"]["old-state"]
    original_execute = runtime.service.execute_tool
    observations = {}

    def execute_then_edit(run_id, call, **kwargs):
        """依赖：原execute_tool/Store。输入：实际调用。输出：原结果。实现：旧稿读完后作者CAS保存，再从Memory独立核失效。"""
        result = original_execute(run_id, call, **kwargs)
        if kwargs.get("provider_call_id", call.call_id) == "read-old-draft":
            observations["author_ref"] = runtime.store.save(run_id, 1, "AUTHOR_REWRITTEN_CURRENT_DRAFT", origin="author").as_dict()
            observations["fresh"] = runtime.memory.recall(run_id, focus=[entry_id])
        return result

    monkeypatch.setattr(runtime.service, "execute_tool", execute_then_edit)

    def script(body, step):
        """依赖：实际请求/公开描述符。输入：请求序号。输出：原生响应。实现：新窗口沿实际read_arguments读取作者稿后才结束。"""
        if step == 1:
            return _reply(mode, calls=[ToolCall("recall-old", "recall", {"focus": [entry_id]}),
                ToolCall("read-old-draft", "read_document", {"source_ref": old_ref})], opaque="OLD_ATTEMPT_OPAQUE")
        if step == 2:
            assert "OLD_CURRENT_CONDITION" not in json.dumps(body)
            assert "OLD_RECORDED_DRAFT" not in json.dumps(body)
            assert "OLD_ATTEMPT_OPAQUE" not in json.dumps(body)
            selected = _context(body, mode)["selected_draft"]
            assert selected["source_ref"] == observations["author_ref"]
            return _reply(mode, calls=[ToolCall("read-author-draft", "read_document", selected["read_arguments"])])
        assert step == 3
        assert _outputs(body, mode)["read-author-draft"]["text"] == "AUTHOR_REWRITTEN_CURRENT_DRAFT"
        return _reply(mode, text="LATE_GENERATED_BODY")

    runtime.script = script
    final = runtime.run()
    assert final["status"] == "completed"
    assert len(runtime.requests) == 3
    assert final["draft_ref"] == observations["author_ref"]
    assert final["draft_text"] == "AUTHOR_REWRITTEN_CURRENT_DRAFT"
    assert final["generated_draft_text"] == "LATE_GENERATED_BODY"
    assert not any(entry.get("value") == "OLD_CURRENT_CONDITION" for entry in observations["fresh"]["state_view"]["entries"])
    stored = runtime.store.load(runtime.run_id)
    assert "OLD_CURRENT_CONDITION" in json.dumps(stored["memory_batches"])
    assert "OLD_RECORDED_DRAFT" in json.dumps(stored["tool_results"])
    assert stored["turns"][0]["attempt_id"] != stored["turns"][1]["attempt_id"]
    assert stored["binding"] == final["binding"]
    for body in runtime.requests:
        _assert_paired(body, mode)


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_late_query_source_change_renews_without_a_memory_revision_change(runtime_factory, monkeypatch, mode):
    """依赖：真实查询来源效力。输入：prepare后加入且随后改写的Canon。输出：旧查询正文退出下一请求。实现：记忆版本仍为0时验证实际已交付Ref失效。"""
    runtime = runtime_factory(mode)
    assert not any(ref.get("document_id") == "late-canon" for ref in runtime.store.load(runtime.run_id)["binding"]["input_snapshot_refs"])
    put_document(runtime.root, "late-canon", "AUXILIARYTOKEN LATE_SOURCE_OLD", category="canon")
    original_execute = runtime.service.execute_tool

    def execute_then_change_source(run_id, call, **kwargs):
        """依赖：实际recall/临时YAML夹具。输入：晚查询。输出：原结果。实现：查询完成后改同一源版本，不直接更改Store记忆。"""
        result = original_execute(run_id, call, **kwargs)
        if kwargs.get("provider_call_id", call.call_id) == "late-query":
            put_document(runtime.root, "late-canon", "AUXILIARYTOKEN LATE_SOURCE_NEW", category="canon",
                         extra_metadata={"source_revision": 2})
        return result

    monkeypatch.setattr(runtime.service, "execute_tool", execute_then_change_source)

    def script(body, step):
        """依赖：真实native请求。输入：查询/重读步骤。输出：原生turn。实现：下一请求不得携带旧来源片段，新内容走实际read_document。"""
        if step == 1:
            return _reply(mode, calls=[ToolCall("late-query", "recall", {"query": "AUXILIARYTOKEN"})])
        if step == 2:
            assert "LATE_SOURCE_OLD" not in json.dumps(body)
            return _reply(mode, calls=[ToolCall("read-new-source", "read_document", {"document_id": "late-canon"})])
        assert step == 3
        assert "LATE_SOURCE_NEW" in _outputs(body, mode)["read-new-source"]["text"]
        return _reply(mode, text="SOURCE_CHECKED_BODY")

    runtime.script = script
    final = runtime.run()
    assert final["status"] == "completed"
    assert len(runtime.requests) == 3
    assert final["memory_revision"] == 0
    stored = runtime.store.load(runtime.run_id)
    assert "LATE_SOURCE_OLD" in json.dumps(stored["tool_results"][0]["result"])
    assert stored["turns"][0]["attempt_id"] != stored["turns"][1]["attempt_id"]


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_acknowledged_save_and_remember_keep_the_active_provider_attempt(runtime_factory, mode):
    """依赖：真实save/remember回执和来源效力。输入：合法追加记忆。输出：同attempt与完整活跃链。实现：用实际DraftRef写状态，防止仅因revision变化重建。"""
    runtime = runtime_factory(mode)
    observations = {}

    def script(body, step):
        """依赖：真正发送的工具回执。输入：连续原生请求。输出：预设正文/记忆turn。实现：所有CAS、Ref都从实际收到结果取值。"""
        if step == 1:
            return _reply(mode, calls=[ToolCall("save-known", "save_draft", {"text": "SAVED_BODY", "expected_revision": 0})],
                          opaque="KEEP_OPAQUE_SENTINEL")
        assert _messages(body, mode)[:2] == _messages(runtime.requests[0], mode)[:2]
        if mode == "responses":
            assert "KEEP_OPAQUE_SENTINEL" in json.dumps(body)
        outputs = _outputs(body, mode)
        if step == 2:
            observations["saved_ref"] = outputs["save-known"]
            assert observations["saved_ref"]["kind"] == "draft"
            return _reply(mode, calls=[ToolCall("remember-known", "remember", {"draft_ref": observations["saved_ref"],
                "expected_memory_revision": 0, "update": {"state_changes": [{"op": "set", "local_ref": "known-state",
                "entry": {"domain": "World", "kind": "condition", "value": "NEW_KNOWN_STATE", "lifetime": "carry"}}]}})])
        assert step == 3
        assert outputs["remember-known"]["memory_revision"] == 1
        assert outputs["save-known"] == observations["saved_ref"]
        return _reply(mode, text="SAVED_BODY\nFINAL_APPEND")

    runtime.script = script
    final = runtime.run()
    assert final["status"] == "completed"
    assert final["memory_revision"] == 1
    stored = runtime.store.load(runtime.run_id)
    assert len(stored["memory_batches"]) == 1
    assert len(stored["tool_commits"]) == 2
    assert len({row["attempt_id"] for row in stored["turns"]}) == 1
    for body in runtime.requests:
        _assert_paired(body, mode)


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_new_attempt_can_reuse_original_provider_id_for_a_distinct_save(runtime_factory, monkeypatch, mode):
    """依赖：实际Store提交与native配对。输入：来源失效后重复provider ID的新保存。输出：两个独立提交。实现：同run用新attempt隔离内部身份而原协议ID不变。"""
    runtime = runtime_factory(mode)
    provider_id = "provider/call:reused"
    original_execute = runtime.service.execute_tool

    def execute_then_replace_base(run_id, call, **kwargs):
        """依赖：原工具执行/临时源。输入：首轮基线读。输出：原回执。实现：旧材料已交付后改写正式fixture源以触发新attempt。"""
        result = original_execute(run_id, call, **kwargs)
        if kwargs.get("provider_call_id", call.call_id) == "read-old-base":
            put_document(runtime.root, "base-history", "REPLACED_FORMAL_BASE", chapter=1,
                         extra_metadata={"source_revision": 2})
        return result

    monkeypatch.setattr(runtime.service, "execute_tool", execute_then_replace_base)

    def script(body, step):
        """依赖：真实请求及当前CAS。输入：新旧attempt请求。输出：两次不同参数保存。实现：保持同一provider ID，后续回执按原值配对。"""
        if step == 1:
            return _reply(mode, calls=[ToolCall(provider_id, "save_draft", {"text": "FIRST_SAVE", "expected_revision": 0}),
                ToolCall("read-old-base", "read_document", {"document_id": "base-history"})])
        if step == 2:
            assert "CURRENT_FORMAL_BASE" not in json.dumps(body)
            assert "FIRST_SAVE" not in json.dumps(_outputs(body, mode))
            return _reply(mode, calls=[ToolCall(provider_id, "save_draft", {"text": "FIRST_SAVE\nSECOND_APPEND", "expected_revision": 1})])
        assert step == 3
        assert _outputs(body, mode)[provider_id]["draft_revision"] == 2
        return _reply(mode, text="FIRST_SAVE\nSECOND_APPEND")

    runtime.script = script
    final = runtime.run()
    assert final["status"] == "completed"
    stored = runtime.store.load(runtime.run_id)
    commits = [row for row in stored["tool_results"] if row["name"] == "save_draft"]
    assert len(commits) == 2
    assert [row["provider_call_id"] for row in commits] == [provider_id, provider_id]
    assert len({row["invocation_key"] for row in commits}) == 2
    assert len({row["attempt_id"] for row in commits}) == 2
    assert [row["result"]["draft_revision"] for row in commits] == [1, 2]
    assert len(stored["tool_commits"]) == 2
    assert stored["turns"][1]["attempt_id"] == stored["turns"][2]["attempt_id"]
    assert final["draft_text"] == "FIRST_SAVE\nSECOND_APPEND"
    for body in runtime.requests:
        _assert_paired(body, mode)


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_same_turn_multiple_tools_keep_original_protocol_pairing(runtime_factory, mode):
    """依赖：实际多工具dispatch及native编码。输入：同turn三工具。输出：完整原ID配对。实现：核真正请求中的调用顺序和所有结果，不改工具条数。"""
    runtime = runtime_factory(mode)
    ids = ["read-first", "recall-middle", "read-last"]

    def script(body, step):
        """依赖：实际后续请求。输入：首/末turn。输出：原生响应。实现：中间recall成功后仍保留两端读工具和原始参数。"""
        if step == 1:
            return _reply(mode, calls=[ToolCall(ids[0], "read_document", {"document_id": "base-history"}),
                ToolCall(ids[1], "recall", {"query": "CURRENT_FORMAL_BASE"}),
                ToolCall(ids[2], "read_document", {"document_id": "base-history", "start_paragraph": 1, "end_paragraph": 1})],
                opaque="MULTITOOL_OPAQUE_SENTINEL")
        assert step == 2
        _assert_paired(body, mode)
        outputs = _outputs(body, mode)
        assert set(outputs) == set(ids)
        assert outputs[ids[0]]["text"] == outputs[ids[2]]["text"]
        assert outputs[ids[1]].get("ok") is not False
        if mode == "responses":
            assert "MULTITOOL_OPAQUE_SENTINEL" in json.dumps(body)
        return _reply(mode, text="MULTITOOL_BODY")

    runtime.script = script
    final = runtime.run()
    assert final["status"] == "completed"
    stored = runtime.store.load(runtime.run_id)
    assert [row["provider_call_id"] for row in stored["tool_results"]] == ids
    assert [row["call_id"] for row in stored["turns"][0]["tool_calls"]] == ids
    assert len({row["attempt_id"] for row in stored["turns"]}) == 1


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_seventeenth_valid_tool_turn_is_not_a_default_context_limit(runtime_factory, mode):
    """依赖：真实运行循环和工具结果。输入：17次合法读取及终稿。输出：18个请求后完成。实现：按实发请求与原turn事实验证默认无固定16turn。"""
    runtime = runtime_factory(mode)

    def script(body, step):
        """依赖：原生调用配对。输入：实际请求序号。输出：下一读或终稿。实现：每轮只新增一次有界读取，不写任何记忆。"""
        _assert_paired(body, mode)
        if step <= 17:
            return _reply(mode, calls=[ToolCall(f"read-{step}", "read_document", {"document_id": "base-history"})])
        assert step == 18
        assert len(_outputs(body, mode)) == 17
        return _reply(mode, text="BODY_AFTER_SEVENTEEN_READS")

    runtime.script = script
    final = runtime.run()
    assert final["status"] == "completed"
    assert len(runtime.requests) == 18
    stored = runtime.store.load(runtime.run_id)
    assert len(stored["turns"]) == 18
    assert len(stored["tool_results"]) == 17
    assert len({row["attempt_id"] for row in stored["turns"]}) == 1


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_explicit_turn_limit_preserves_public_text_and_is_distinct_from_capacity(runtime_factory, mode):
    """依赖：显式client策略/原turn。输入：max_turns=1和公开工具前说明。输出：run_limit且不制造草稿。实现：完成首工具组后停止，新Store仍可读取原公开文本。"""
    runtime = runtime_factory(mode, max_turns=1)
    text = "PUBLIC_PLAN_AT_EXPLICIT_LIMIT🙂\r\n此为工具前说明。"

    def script(_body, step):
        """依赖：实际native调用。输入：首请求。输出：完整公开text及读工具。实现：显式限制不允许第二请求，也不把说明保存为正文。"""
        assert step == 1
        return _reply(mode, calls=[ToolCall("limit-read", "read_document", {"document_id": "base-history"})], text=text)

    runtime.script = script
    final = runtime.run()
    assert final["status"] == "interrupted"
    assert final["error"]["code"] == "run_limit"
    assert len(runtime.requests) == 1
    assert final["draft_revision"] == 0
    assert final["draft_ref"] is None
    reopened = DraftStore(runtime.store.root)
    stored = reopened.load(runtime.run_id)
    assert len(stored["tool_results"]) == 1
    assert reopened.public_turn_text(runtime.run_id, stored["turns"][0]["turn_id"]) == text
    assert stored["turns"][0]["request_manifest"]["policy"]["max_turns"] == 1


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_explicit_unfittable_window_preserves_input_and_never_submits(runtime_factory, mode):
    """依赖：原生真实请求估算/显式窗口。输入：明确不足的窗口和输出预留。输出：context_limit、零网络与效果。实现：完整原任务留在Store，不通过静默截断或重试实现适配。"""
    runtime = runtime_factory(mode, context_window_tokens=1, output_reserve_tokens=0)
    final = runtime.run()
    assert final["status"] in {"failed", "interrupted"}
    assert final["error"]["code"] == "context_limit"
    assert runtime.requests == []
    stored = runtime.store.load(runtime.run_id)
    assert stored["request_snapshot"]["outline"] == "原纲🙂：沿作者路线继续，保留结尾约束。"
    assert stored["request_snapshot"]["request"] == "原要求：按真实来源写作。"
    assert stored["draft_revision"] == 0
    assert stored["memory_revision"] == 0
    assert stored["tool_commits"] == {}
    assert stored["turns"] == []


@pytest.mark.parametrize("mode", ["chat", "responses"])
@pytest.mark.parametrize("error_code,expected", [("invalid_request_error", "capability"), ("context_length_exceeded", "context_limit")])
def test_unknown_window_http_error_does_not_retry_or_guess_capacity(runtime_factory, mode, error_code, expected):
    """依赖：真实native HTTP错误分类。输入：未知窗口普通400/明确容量码。输出：一次失败及准确类别。实现：保留prepared输入且不自动重发或循环新attempt。"""
    runtime = runtime_factory(mode)

    def script(_body, step):
        """依赖：真实错误响应。输入：请求次数。输出：HTTP400。实现：错误文字不含容量暗示，仅明确code可识别容量。"""
        assert step == 1
        return httpx.Response(400, json={"error": {"code": error_code, "message": "scripted endpoint rejection"}})

    runtime.script = script
    final = runtime.run()
    assert final["status"] in {"failed", "interrupted"}
    assert final["error"]["code"] == expected
    assert len(runtime.requests) == 1
    stored = runtime.store.load(runtime.run_id)
    assert stored["draft_revision"] == 0
    assert stored["memory_revision"] == 0
    assert stored["request_snapshot"]["outline"].endswith("保留结尾约束。")
    assert len(stored["turns"]) == 1
    assert stored["turns"][0]["attempt_id"]
    assert stored["turns"][0]["request_status"] == "prepared"


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_unsubmitted_public_turn_text_is_readable_after_renewal_and_not_story(runtime_factory, monkeypatch, mode):
    """依赖：原turn/received与read_document技术槽。输入：未存公开说明和来源失效。输出：新窗口可完整读且不制造正文。实现：按公开导览续页精确重组，最终正文只取终稿。"""
    runtime = runtime_factory(mode)
    public_text = "OOC_PROCESS_ONLY🙂\r\n这是工具前的公开说明，不是故事正文。\n" * 180
    original_execute = runtime.service.execute_tool
    pages = []

    def execute_then_change_source(run_id, call, **kwargs):
        """依赖：真实读工具/临时源。输入：首个来源读。输出：原结果。实现：在公开turn完整保存后触发新attempt，无自动草稿保存。"""
        result = original_execute(run_id, call, **kwargs)
        if kwargs.get("provider_call_id", call.call_id) == "read-before-renewal":
            put_document(runtime.root, "base-history", "NEW_BASE_FOR_PUBLIC_TEXT", chapter=1,
                         extra_metadata={"source_revision": 2})
        return result

    monkeypatch.setattr(runtime.service, "execute_tool", execute_then_change_source)

    def script(body, step):
        """依赖：新窗口实际技术导览/分页回执。输入：真实请求。输出：完整续读或终稿。实现：每页沿原next_arguments，始终核稿件未被技术text创建。"""
        if step == 1:
            return _reply(mode, calls=[ToolCall("read-before-renewal", "read_document", {"document_id": "base-history"})],
                          text=public_text, opaque="RETIRED_PUBLIC_TEXT_OPAQUE")
        assert runtime.store.load(runtime.run_id)["draft_revision"] == 0
        assert runtime.store.load(runtime.run_id)["draft_ref"] is None
        if step == 2:
            assert "RETIRED_PUBLIC_TEXT_OPAQUE" not in json.dumps(body)
            descriptor = _context(body, mode)["technical_turns"][0]
            assert descriptor["kind"] == "technical_turn"
            assert descriptor["total_characters"] == len(public_text)
            return _reply(mode, calls=[ToolCall(f"public-page-{step}", "read_document", descriptor["read_arguments"])])
        page = _outputs(body, mode)[f"public-page-{step - 1}"]
        assert page["kind"] == "technical_turn"
        assert page["source_ref"] is None
        assert page["character_range"][0] == sum(len(part) for part in pages)
        pages.append(page["text"])
        if page["next_arguments"]:
            return _reply(mode, calls=[ToolCall(f"public-page-{step}", "read_document", page["next_arguments"])])
        assert "".join(pages) == public_text
        return _reply(mode, text="FINAL_STORY_ONLY")

    runtime.script = script
    final = runtime.run()
    assert final["status"] == "completed"
    assert len(pages) > 1
    assert final["draft_text"] == "FINAL_STORY_ONLY"
    assert final["draft_revision"] == 1
    stored = runtime.store.load(runtime.run_id)
    assert stored["turns"][0]["text"] == public_text
    assert stored["turns"][0]["attempt_id"] != stored["turns"][1]["attempt_id"]
    assert runtime.store.public_turn_text(runtime.run_id, stored["turns"][0]["turn_id"]) == public_text
    assert stored["memory_batches"] == []


class _ExitBeforeResponse(BaseException):
    """Fixture simulates leaving the runtime before any provider response exists."""


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_request_identity_is_prepared_before_response_and_survives_restart(runtime_factory, mode):
    """依赖：实际发送前Store准备行/恢复。输入：响应前退出。输出：原attempt/manifest保留且不重发。实现：内存transport抛退出异常，新Store标interrupted并读取原绑定。"""
    runtime = runtime_factory(mode)
    prepared = {}

    def script(_body, step):
        """依赖：真正POST发起时的原Store。输入：首次请求。输出：模拟退出。实现：先核准备行已落盘，没有结果或工具效果，再停止响应。"""
        assert step == 1
        current = runtime.store.load(runtime.run_id)
        assert current["status"] == "running"
        assert len(current["turns"]) == 1
        prepared.update(current["turns"][0])
        assert prepared["attempt_id"]
        assert prepared["request_status"] == "prepared"
        assert prepared["request_manifest"]["material_binding"]
        assert current["tool_commits"] == {}
        raise _ExitBeforeResponse()

    runtime.script = script
    with pytest.raises(_ExitBeforeResponse):
        runtime.run()
    reopened = DraftStore(runtime.store.root)
    assert reopened.recover() == [runtime.run_id]
    persisted = reopened.snapshot(runtime.run_id)
    assert persisted["status"] == "interrupted"
    assert persisted["turns"][0]["turn_id"] == prepared["turn_id"]
    assert persisted["turns"][0]["attempt_id"] == prepared["attempt_id"]
    assert persisted["turns"][0]["request_manifest"] == prepared["request_manifest"]
    assert persisted["turns"][0]["request_status"] == "prepared"
    assert persisted["tool_commits"] == {}
    assert len(runtime.requests) == 1


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_committed_remember_without_tool_receipt_recovers_the_original_identity(runtime_factory, monkeypatch, mode):
    """依赖：实际Memory提交/原turn参数/恢复dispatcher。输入：提交后回执落盘失败。输出：新Store同身份恢复唯一回执。实现：只故障tool_results保存，原批次/键已落盘且旧CAS仍恢复。"""
    runtime = runtime_factory(mode)
    source = runtime.store.save(runtime.run_id, 0, "CHECKPOINT_BEFORE_MEMORY", origin="model").as_dict()
    arguments = {"draft_ref": source, "expected_memory_revision": 0, "update": {"state_changes": [{
        "op": "set", "local_ref": "recovered-state", "entry": {"domain": "World", "kind": "condition",
        "value": "ONE_COMMITTED_CHANGE", "lifetime": "carry"}}]}}
    original_write = runtime.store.write
    failed = False

    def write_with_one_receipt_failure(run):
        """依赖：原Store原子保存。输入：待保存run。输出：正常写/单次OSError。实现：批次真实提交后才阻断独立tool_results回执行，不能回滚提交。"""
        nonlocal failed
        if not failed and run["memory_batches"] and any(row["name"] == "remember" for row in run.get("tool_results", [])):
            failed = True
            raise OSError("fixture tool receipt persistence failure")
        return original_write(run)

    monkeypatch.setattr(runtime.store, "write", write_with_one_receipt_failure)

    def script(_body, step):
        """依赖：真实native调用。输入：唯一模型请求。输出：remember响应。实现：原call参数固定，提交后不再给第二个新意图。"""
        assert step == 1
        return _reply(mode, calls=[ToolCall("original/remember:id", "remember", arguments)])

    runtime.script = script
    final = runtime.run()
    assert failed
    assert final["status"] == "failed"
    assert final["error"]["code"] == "save_failed"
    assert len(runtime.requests) == 1
    reopened = DraftStore(runtime.store.root)
    stored = reopened.load(runtime.run_id)
    turn = stored["turns"][0]
    original = turn["tool_calls"][0]
    assert original["call_id"] == "original/remember:id"
    assert original["arguments"] == arguments
    key = reopened.invocation_key(turn["attempt_id"], original["call_id"])
    assert set(stored["tool_commits"]) == {key}
    expected = stored["tool_commits"][key]["result"]
    assert expected["memory_revision"] == 1
    assert stored.get("tool_results", []) == []
    memory = MemoryService(runtime.root, reopened)
    resumed = RunService(runtime.root, reopened, memory, _ModelConfiguration(runtime.model))
    recovered = resumed.execute_tool(runtime.run_id, ToolCall(key, "remember", original["arguments"]), delivery="model",
                                     attempt_id=turn["attempt_id"], provider_call_id=original["call_id"], turn_id=turn["turn_id"])
    assert recovered == expected
    after = reopened.load(runtime.run_id)
    assert len(after["memory_batches"]) == 1
    assert after["memory_revision"] == 1
    assert set(after["tool_commits"]) == {key}
    assert after["tool_results"][0]["invocation_key"] == key
    assert after["tool_results"][0]["attempt_id"] == turn["attempt_id"]
    assert after["tool_results"][0]["provider_call_id"] == original["call_id"]
    changed = {**arguments, "expected_memory_revision": 1}
    with pytest.raises(StoreConflict, match="revision_conflict"):
        resumed.execute_tool(runtime.run_id, ToolCall(key, "remember", changed), delivery="model",
                             attempt_id=turn["attempt_id"], provider_call_id=original["call_id"], turn_id=turn["turn_id"])
    assert len(reopened.load(runtime.run_id)["memory_batches"]) == 1
    assert len(runtime.requests) == 1
