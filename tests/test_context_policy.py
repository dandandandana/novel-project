from __future__ import annotations

import asyncio
from copy import deepcopy
import json

import pytest

from native_http_fixture import NativeEndpoint
from novel_rag.graph.corpus import json_text
from novel_rag.model_api import ModelAPIError, ModelTurn, OpenAICompatibleModel, ToolCall, provider_usage_totals


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_native_manifest_and_explicit_cache_match_actual_request(mode: str) -> None:
    """依赖：本地HTTP fixture/原生client。输入：Unicode任务、工具和显式cache参数。输出：实际body与安全计量一致。实现：真实loopback请求，核完整封装与不披露材料。"""
    pytest.importorskip("httpx")
    messages = [{"role": "system", "content": "稳定规则"}, {"role": "user", "content": "秘密原纲🙂"}]
    definitions = [{"name": "recall", "description": "读取资料", "parameters": {"type": "object"}}]
    response = ({"choices": [{"message": {"content": "正文"}, "finish_reason": "stop"}]}
                if mode == "chat" else {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "正文"}]}]})
    with NativeEndpoint([{"mode": mode, "json": response}]) as endpoint:
        model = OpenAICompatibleModel(endpoint.base_url, "fixture", mode=mode, api_key="PRIVATE-KEY",
                                      prompt_cache_key="PRIVATE-CACHE-KEY", prompt_cache_retention="24h")
        manifest = model.request_manifest(messages, definitions, {"stream": False})
        turn = asyncio.run(model.complete_turn(messages, definitions, {"stream": False}))
        assert turn.text == "正文"
        body = endpoint.requests[0]["body"]
        assert body["input" if mode == "responses" else "messages"] == messages
        assert body["prompt_cache_key"] == "PRIVATE-CACHE-KEY"
        assert body["prompt_cache_retention"] == "24h"
        assert not {"context_window_tokens", "output_reserve_tokens", "max_turns", "provider_compaction"} & body.keys()
        logical = json_text(body)
        assert manifest["logical_json_bytes"] == len(logical.encode("utf-8"))
        assert manifest["logical_json_characters"] == len(logical)
        assert manifest["logical_json_bytes"] > manifest["logical_json_characters"]
        assert manifest["message_type_counts"] == {"system": 1, "user": 1}
        assert manifest["wire_bytes"] is None
        assert manifest["measurement"] == "logical_native_request_json"
        for private in ("秘密原纲", "PRIVATE-KEY", "PRIVATE-CACHE-KEY"):
            assert private not in json.dumps(manifest, ensure_ascii=False)


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_unknown_capacity_and_default_cache_do_not_guess_model(mode: str) -> None:
    """依赖：request_manifest/request_body。输入：看似大窗口型号与显式输出上限。输出：未知窗口/预留仍为None。实现：比较默认与仅设window，确认输出上限不冒充预留。"""
    model = OpenAICompatibleModel("http://fixture.invalid/v1", "gpt-1000000-token-window", mode=mode,
                                  max_output_tokens=256)
    messages = [{"role": "user", "content": "任务"}]
    for window in (None, 8192):
        model.context_window_tokens = window
        manifest = model.request_manifest(messages, [], {"max_output_tokens": 512})
        assert manifest["output_reserve_tokens"] is None
        assert manifest["remaining_input_tokens"] is None
        assert manifest["context_fits"] is None
        assert manifest["policy"]["max_output_tokens"] == 512
        assert model.max_turns is None
        body = model.request_body(messages, [])
        assert "prompt_cache_key" not in body and "prompt_cache_retention" not in body
        assert "context_management" not in body and "truncation" not in body
        assert manifest["capabilities"]["provider_compaction"] == "unsupported"


def test_explicit_capacity_counts_tools_and_blocks_without_http_or_mutation() -> None:
    """依赖：真实容量策略/原生codec。输入：可容纳短任务但不可容纳大schema的窗口。输出：发送前context_limit。实现：比较完整body计量并断言原材料保持。"""
    messages = [{"role": "user", "content": "写作"}]
    definitions = [{"name": "recall", "description": "很长的工具说明" * 1000,
                    "parameters": {"type": "object"}}]
    original = deepcopy((messages, definitions))
    model = OpenAICompatibleModel("http://fixture.invalid/v1", "fixture", context_window_tokens=512,
                                  output_reserve_tokens=64)
    assert model.request_manifest(messages, [])["context_fits"] is True
    manifest = model.request_manifest(messages, definitions)
    assert manifest["remaining_input_tokens"] == 448
    assert manifest["context_fits"] is False
    with pytest.raises(ModelAPIError, match="^context_limit:"):
        asyncio.run(model.complete_turn(messages, definitions))
    assert (messages, definitions) == original


@pytest.mark.parametrize("options", [
    {"context_window_tokens": True}, {"context_window_tokens": 0}, {"context_window_tokens": "100"},
    {"output_reserve_tokens": -1}, {"max_turns": False}, {"max_turns": 0},
    {"context_window_tokens": 10, "output_reserve_tokens": 11},
    {"prompt_cache_key": ""}, {"prompt_cache_key": []}, {"prompt_cache_retention": "forever"},
    {"provider_compaction": True},
])
def test_direct_client_rejects_invalid_policy(options: dict) -> None:
    """依赖：共享policy validator。输入：坏类型/边界/未支持能力。输出：安全capability错误。实现：直接构造client，避免配置层掩盖运行时校验。"""
    with pytest.raises(ModelAPIError, match="^capability:"):
        OpenAICompatibleModel("http://fixture.invalid/v1", "fixture", **options)


@pytest.mark.parametrize("status,error,expected", [
    (400, {"code": "context_length_exceeded"}, "context_limit"),
    (400, {"type": "max_context_length_exceeded"}, "context_limit"),
    (422, {"code": "context_window_exceeded"}, "context_limit"),
    (400, {"type": "invalid_request_error", "message": "maximum context length exceeded PRIVATE"}, "capability"),
    (400, {"code": ["context_length_exceeded"], "message": "PRIVATE"}, "capability"),
    (500, {"code": "other", "message": "PRIVATE context window"}, "model_network"),
])
def test_native_http_capacity_errors_use_codes_and_do_not_retry(monkeypatch, status: int, error: dict, expected: str) -> None:
    """依赖：HTTPX MockTransport/实际complete_turn。输入：明确或普通HTTP错误。输出：精确类别且一次请求。实现：只替换网络seam，保留状态/JSON/错误处理。"""
    httpx = pytest.importorskip("httpx")
    requests = []
    original_client = httpx.AsyncClient

    def respond(request):
        """依赖：HTTPX response。输入：真实编码request。输出：测试错误响应。实现：记录次数并返回独立JSON。"""
        requests.append(request)
        return httpx.Response(status, json={"error": error})

    def client(**kwargs):
        """依赖：原AsyncClient/MockTransport。输入：生产client选项。输出：隔离transport client。实现：只替换端点，不复制生产循环。"""
        return original_client(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    model = OpenAICompatibleModel("http://fixture.invalid/v1", "fixture", retries=5)
    with pytest.raises(ModelAPIError, match=f"^{expected}:") as caught:
        asyncio.run(model.complete_turn([], [], {"stream": False}))
    assert len(requests) == 1
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("event", [
    {"type": "error", "code": "context_length_exceeded"},
    {"type": "response.failed", "response": {"error": {"type": "context_window_exceeded"}}},
])
def test_responses_stream_reports_explicit_capacity_error(event: dict) -> None:
    """依赖：loopback SSE/原生错误分类。输入：两种明确provider失败帧。输出：context_limit且单请求。实现：通过真实stream parser，不按自由文本推容量。"""
    pytest.importorskip("httpx")
    with NativeEndpoint([{"mode": "responses", "frames": [event]}]) as endpoint:
        model = OpenAICompatibleModel(endpoint.base_url, "fixture", mode="responses")
        with pytest.raises(ModelAPIError, match="^context_limit:"):
            asyncio.run(model.complete_turn([], []))
        assert len(endpoint.requests) == 1


def test_unvalidated_compaction_cannot_become_public_text() -> None:
    """依赖：loopback Responses/完整turn decoder。输入：意外opaque compaction响应。输出：明确unsupported且无公开delta。实现：拒绝未验收类型，避免交付空稿或解释opaque。"""
    pytest.importorskip("httpx")
    deltas = []

    async def observe(text):
        """依赖：公开delta回调。输入：实际文本。输出：记录列表。实现：只观察，证明opaque没有变正文。"""
        deltas.append(text)

    with NativeEndpoint([{"mode": "responses", "json": {"status": "completed", "output": [
        {"type": "compaction", "encrypted_content": "PRIVATE-OPAQUE"},
    ]}}]) as endpoint:
        model = OpenAICompatibleModel(endpoint.base_url, "fixture", mode="responses")
        with pytest.raises(ModelAPIError, match="^capability:") as caught:
            asyncio.run(model.complete_turn([], [], {"stream": False}, on_text_delta=observe))
        assert deltas == []
        assert "PRIVATE-OPAQUE" not in str(caught.value)


def test_responses_active_groups_survive_followup_and_manifest() -> None:
    """依赖：followup_messages/安全manifest。输入：连续两组reasoning/调用/结果。输出：最后user后的全部原项保留。实现：跨多turn比较原链，计量不裁剪或泄露隐藏内容。"""
    model = OpenAICompatibleModel("http://fixture.invalid/v1", "fixture", mode="responses")
    messages = [{"role": "user", "content": "原任务"}]
    for number in range(2):
        call_id = f"provider-{number}"
        items = [{"type": "reasoning", "encrypted_content": f"PRIVATE-OPAQUE-{number}"},
                 {"type": "function_call", "call_id": call_id, "name": "recall", "arguments": '{"query":"原参数"}'}]
        turn = ModelTurn([], "", [ToolCall(call_id, "recall", {"query": "原参数"})], "tool_calls", items, {})
        messages = model.followup_messages(messages, turn, [{"call_id": call_id, "result": {"value": number}}])
    original = deepcopy(messages)
    manifest = model.request_manifest(messages, [])
    assert model.request_body(messages, [])["input"] == original
    assert messages == original
    assert manifest["message_type_counts"] == {"user": 1, "reasoning": 2, "function_call": 2, "function_call_output": 2}
    assert "PRIVATE" not in json.dumps(manifest)


def test_usage_totals_preserve_reported_cache_and_missing_values() -> None:
    """依赖：共同usage汇总。输入：两协议报告及缺失/null/坏类型。输出：累计provider/cache/净新增分开。实现：只算真实整数，缺字段不补零且不修改原usage。"""
    rows = [{"prompt_tokens": 20, "completion_tokens": 3, "total_tokens": 23,
             "prompt_tokens_details": {"cached_tokens": 8}},
            {"input_tokens": 100, "output_tokens": 7, "total_tokens": 107,
             "input_tokens_details": {"cached_tokens": 80}}]
    original = deepcopy(rows)
    result = provider_usage_totals(rows)
    assert result["input_tokens"] == 120 and result["output_tokens"] == 10 and result["total_tokens"] == 130
    assert result["cached_input_tokens"] == 88 and result["net_new_input_tokens"] == 32
    assert result["cache_write_tokens"] is None
    assert result["source"] == "provider_reported_usage" and result["scope"] == "cumulative"
    assert rows == original
    missing = provider_usage_totals([{"input_tokens": 40}, None])
    assert missing["input_tokens"] is None and missing["reported_requests"]["input_tokens"] == 1
    assert missing["cached_input_tokens"] is None and missing["net_new_input_tokens"] is None
    assert provider_usage_totals([{"input_tokens": 4, "input_tokens_details": {"cached_tokens": None}}])["cached_input_tokens"] is None
    assert provider_usage_totals([{"input_tokens": 4, "input_tokens_details": {"cached_tokens": True}}])["cached_input_tokens"] is None
    assert provider_usage_totals([{"input_tokens": 4, "input_tokens_details": {"cached_tokens": 5}}])["net_new_input_tokens"] is None
    assert provider_usage_totals([])["input_tokens"] is None
