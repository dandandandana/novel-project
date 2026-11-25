from __future__ import annotations

import asyncio
from pathlib import Path
import threading

import pytest

pytest.importorskip("httpx", reason="native model-turn transport requires optional HTTPX")

from native_http_fixture import NativeEndpoint
from novel_rag.generation.store import DraftStore
from novel_rag.generation.types import NarrativeCursor, RunBinding
from novel_rag.identity import GraphKey
from novel_rag.model_api import ModelAPIError, OpenAICompatibleModel


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_request_body_preserves_actual_memory_examples_and_descriptions(tmp_path: Path, mode: str) -> None:
    """依赖：实际工具登记/原生request_body。输入：同一run五工具定义。输出：两协议完整同源Schema及描述。实现：仅封装真实定义，核样例未被协议包装裁掉，不调用外部模型。"""
    from novel_rag.composition import build_writer_service
    from novel_rag.memory.schema import remember_update_schema
    from novel_rag.std.serialization import json_text
    from writer_fixtures import make_library

    service = build_writer_service(make_library(tmp_path), tmp_path / "workspace", tmp_path / "no-config.json")
    run_id = service.prepare(GraphKey("demo", "main"), "write", "山门关闭后开放。", "记忆实际变化。")
    definitions = service.tool_dispatcher(run_id).definitions()
    model = OpenAICompatibleModel("http://127.0.0.1:1/v1", "fixture-writer", mode=mode)
    body = model.request_body([], definitions)
    delivered = ([{key: value for key, value in tool.items() if key != "type"} for tool in body["tools"]]
                 if mode == "responses" else [tool["function"] for tool in body["tools"]])
    assert delivered == definitions
    schema = next(tool for tool in delivered if tool["name"] == "remember")["parameters"]["properties"]["update"]
    assert schema == remember_update_schema()
    assert json_text(schema["examples"]) in schema["description"]


def _model(endpoint: NativeEndpoint, mode: str, *, api_key: str | None = None) -> OpenAICompatibleModel:
    """依赖：NativeEndpoint 与 OpenAICompatibleModel。
    输入：fixture 地址、协议名及可选测试凭证。
    输出：关闭重试的本地模型 client。
    实现：使用短超时和真实 HTTPX 传输，不替换协议代码。
    """
    assert endpoint.base_url is not None
    return OpenAICompatibleModel(
        endpoint.base_url,
        "fixture-writer",
        api_key=api_key,
        mode=mode,
        timeout=2.0,
        retries=0,
    )


def _binding() -> RunBinding:
    """依赖：GraphKey、NarrativeCursor 与 RunBinding。
    输入：无。
    输出：不读取外部资料的固定故事绑定。
    实现：构造隔离 DraftStore 测试使用的最小 scene scope。
    """
    return RunBinding(
        scope=GraphKey("native-turn-story", "main"),
        task_kind="scene",
        narrative_cursor=NarrativeCursor("before"),
        base_ref=None,
        draft_branch="main",
        selected_parent_checkpoint=None,
    )


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_native_turn_accepts_non_streaming_json(mode: str) -> None:
    """验证两个原生协议的真实 HTTP 非流式响应与工具解码。

    依赖：本地 NativeEndpoint、HTTPX 与 ModelTurn。
    输入：独立手写的 provider JSON、会话和工具定义。
    输出：公开文本、真实调用 ID、参数和 usage 均可读取的完整 turn。
    实现：经 localhost 请求并检查按协议封装的实际请求体和 delta 回调。
    """
    text = "先查资料：雪山人物。"
    call_id = f"call_{mode}_nonstream_31"
    arguments = {"query": "雪山人物"}
    if mode == "chat":
        response = {
            "id": "chatcmpl_nonstream_fixture",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": text,
                    "tool_calls": [{
                        "id": call_id,
                        "type": "function",
                    "function": {"name": "recall", "arguments": '{"query":"雪山人物"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 19, "completion_tokens": 8},
        }
    else:
        response = {
            "id": "resp_nonstream_fixture",
            "status": "completed",
            "output": [
                {"type": "reasoning", "id": "rs_nonstream", "encrypted_content": "opaque-reasoning"},
                {"type": "message", "id": "msg_nonstream", "role": "assistant", "content": [
                    {"type": "output_text", "text": text},
                ]},
                {
                    "type": "function_call",
                    "id": "fc_nonstream",
                    "call_id": call_id,
                    "name": "recall",
                    "arguments": '{"query":"雪山人物"}',
                },
            ],
            "usage": {"input_tokens": 19, "output_tokens": 8},
        }

    messages = [{"role": "user", "content": "围绕雪山写作。"}]
    definitions = [{
        "name": "recall",
        "description": "读取参考资料",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
    }]
    with NativeEndpoint([{"mode": mode, "json": response}]) as endpoint:
        model = _model(endpoint, mode, api_key="fixture-secret")
        deltas: list[str] = []

        async def on_delta(delta: str) -> None:
            """依赖：complete_turn 的异步公开文本回调。
            输入：一次完整非流式公开文本交付。
            输出：无。
            实现：保存实际收到的 delta 供断言。
            """
            deltas.append(delta)

        turn = asyncio.run(model.complete_turn(
            messages,
            definitions,
            {"stream": False, "max_output_tokens": 128},
            on_text_delta=on_delta,
        ))

        assert len(endpoint.requests) == 1
        request = endpoint.requests[0]
        assert request["path"] == ("/v1/chat/completions" if mode == "chat" else "/v1/responses")
        body = request["body"]
        assert body["model"] == "fixture-writer"
        assert body["stream"] is False
        assert body["max_tokens" if mode == "chat" else "max_output_tokens"] == 128
        assert body["messages" if mode == "chat" else "input"] == messages
        if mode == "chat":
            assert body["tools"] == [{"type": "function", "function": definitions[0]}]
        else:
            assert body["tools"] == [{"type": "function", **definitions[0]}]
            assert body["store"] is False
            assert body["include"] == ["reasoning.encrypted_content"]

        assert "headers" not in request
        assert turn.text == text
        assert turn.tool_calls[0].call_id == call_id
        assert turn.tool_calls[0].name == "recall"
        assert turn.tool_calls[0].arguments == arguments
        assert turn.usage == response["usage"]
        assert deltas == [turn.text]
        assert all("reasoning" not in block.get("type", "") for block in turn.content_blocks)
        if mode == "responses":
            assert turn.continuation == response["output"]


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_native_sse_tool_followup_preserves_real_call_and_final_text(mode: str) -> None:
    """验证两种 SSE 协议从工具调用到 follow-up 终稿的真实往返。

    依赖：NativeEndpoint、complete_turn 与 followup_messages。
    输入：独立手写的多帧工具响应、真实结果及终稿响应。
    输出：首轮文本增量、原调用身份和下一请求内容与最终文本一致。
    实现：逐字节拆分 UTF-8 SSE，经两次真实 HTTP 请求核对原生会话续接。
    """
    messages = [{"role": "user", "content": "写一段雪山人物相遇。"}]
    definitions = [{
        "name": "recall",
        "description": "读取参考资料",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
    }]
    result = {"references": [{"document_id": "snow-guide", "text": "风雪中的山路。"}]}
    result_json = '{"references": [{"document_id": "snow-guide", "text": "风雪中的山路。"}]}'
    if mode == "chat":
        call_id = "call_chat_live_87"
        first_frames: list[dict | str] = [
            {"id": "chatcmpl_stream_fixture", "choices": [{"index": 0, "delta": {
                "role": "assistant", "content": "先查：",
            }}]},
            {"choices": [{"index": 0, "delta": {
                "content": "雪山信息。",
                "tool_calls": [{"index": 0, "id": call_id, "type": "function", "function": {
                    "name": "rec", "arguments": '{"query":"雪',
                }}],
            }}]},
            {"choices": [{"index": 0, "delta": {
                "tool_calls": [{"index": 0, "function": {
                    "name": "all", "arguments": '山人物"}',
                }}],
            }}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
             "usage": {"prompt_tokens": 24, "completion_tokens": 10}},
            "[DONE]",
        ]
        final_text = "终稿：雪山上的风停了。"
        final_frames: list[dict | str] = [
            {"choices": [{"index": 0, "delta": {"role": "assistant", "content": final_text}}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            "[DONE]",
        ]
        expected_output = {"role": "tool", "tool_call_id": call_id,
                           "content": result_json}
    else:
        call_id = "call_responses_live_92"
        call_item = {
            "type": "function_call",
            "id": "fc_live_92",
            "call_id": call_id,
            "name": "recall",
            "arguments": '{"query":"雪山人物"}',
        }
        reasoning_item = {
            "type": "reasoning",
            "id": "rs_live_92",
            "summary": [{"type": "summary_text", "text": "仅供模型继续的隐藏推理"}],
            "encrypted_content": "opaque-continuation-token",
        }
        first_output = [
            reasoning_item,
            {"type": "message", "id": "msg_live_92", "role": "assistant", "content": [
                {"type": "output_text", "text": "先查：雪山信息。"},
            ]},
            call_item,
        ]
        first_response = {
            "id": "resp_stream_fixture",
            "status": "completed",
            "output": first_output,
            "usage": {"input_tokens": 24, "output_tokens": 10},
        }
        first_frames = [
            {"type": "response.created", "response": {"id": "resp_stream_fixture", "status": "in_progress"}},
            {"type": "response.output_item.added", "output_index": 2, "item": call_item},
            {"type": "response.function_call_arguments.delta", "item_id": call_item["id"],
             "delta": call_item["arguments"]},
            {"type": "response.output_text.delta", "delta": "先查：雪山信息。"},
            {"type": "response.completed", "response": first_response},
        ]
        final_text = "终稿：雪山上的风停了。"
        final_output = [{
            "type": "message",
            "id": "msg_final_92",
            "role": "assistant",
            "content": [{"type": "output_text", "text": final_text}],
        }]
        final_frames = [
            {"type": "response.output_text.delta", "delta": final_text},
            {"type": "response.completed", "response": {
                "id": "resp_final_fixture", "status": "completed", "output": final_output,
                "usage": {"input_tokens": 37, "output_tokens": 9},
            }},
        ]
        expected_output = {"type": "function_call_output", "call_id": call_id,
                           "output": result_json}

    with NativeEndpoint([
        {"mode": mode, "frames": first_frames},
        {"mode": mode, "frames": final_frames},
    ]) as endpoint:
        model = _model(endpoint, mode)
        first_deltas: list[str] = []

        async def on_first_delta(delta: str) -> None:
            """依赖：complete_turn 的异步文本回调。
            输入：当前首轮公开文本增量。
            输出：无。
            实现：保留实际增量用于与最终 turn.text 对比。
            """
            first_deltas.append(delta)

        turn = asyncio.run(model.complete_turn(messages, definitions, on_text_delta=on_first_delta))
        assert turn.text == "先查：雪山信息。"
        assert "".join(first_deltas) == turn.text
        assert turn.tool_calls[0].call_id == call_id
        assert turn.tool_calls[0].name == "recall"
        assert turn.tool_calls[0].arguments == {"query": "雪山人物"}
        assert turn.finish_reason == "tool_calls"
        if mode == "chat":
            assert turn.continuation[0]["tool_calls"][0]["id"] == call_id
            assert turn.continuation[0]["tool_calls"][0]["function"]["name"] == "recall"
            assert turn.continuation[0]["tool_calls"][0]["function"]["arguments"] == '{"query":"雪山人物"}'
        else:
            assert turn.continuation == first_output
            assert turn.continuation[0] == reasoning_item
            assert all(block.get("type") != "reasoning" for block in turn.content_blocks)
            assert [block for block in turn.content_blocks if block.get("type") == "text"] == [
                {"type": "text", "text": "先查：雪山信息。"},
            ]
            assert any(block.get("type") == "tool_call" and block.get("call_id") == call_id
                       for block in turn.content_blocks)

        next_messages = model.followup_messages(messages, turn, [{"call_id": call_id, "result": result}])
        assert next_messages[:-1] == messages + turn.continuation
        assert next_messages[-1] == expected_output
        final_turn = asyncio.run(model.complete_turn(next_messages, definitions))
        assert final_turn.text == final_text
        assert endpoint.wait_for_requests(2)
        assert [request["path"] for request in endpoint.requests] == [
            "/v1/chat/completions" if mode == "chat" else "/v1/responses",
            "/v1/chat/completions" if mode == "chat" else "/v1/responses",
        ]
        assert endpoint.requests[0]["body"]["messages" if mode == "chat" else "input"] == messages
        assert endpoint.requests[1]["body"]["messages" if mode == "chat" else "input"] == next_messages
        if mode == "chat":
            assert any(block.get("type") == "tool_call" and block.get("call_id") == call_id
                       for block in turn.content_blocks)


def test_unterminated_stream_keeps_real_draft_store_partial(tmp_path: Path) -> None:
    """验证缺少协议结束标记時只保留真实落盘 partial。

    依赖：NativeEndpoint、DraftStore.receive 与 complete_turn。
    输入：一帧 UTF-8 文本后正常断开的 chat SSE。
    输出：模型报 model_protocol，received 快照保留前缀且 run 未提交 turn。
    实现：回调累计文本写入真实磁盘，再从新 Store 实例恢复检查。
    """
    partial = "已经收到：雪山"
    with NativeEndpoint([{"mode": "chat", "frames": [
        {"choices": [{"index": 0, "delta": {"content": partial}}]},
    ]}]) as endpoint:
        store = DraftStore(tmp_path)
        run = store.create(_binding(), "原始路线", "描写雪山。")
        model = _model(endpoint, "chat")
        accumulated = ""

        async def persist_delta(delta: str) -> None:
            """依赖：DraftStore.receive。
            输入：complete_turn 实际收到的文本增量。
            输出：无。
            实现：累计公开前缀并按 partial 状态写入磁盘。
            """
            nonlocal accumulated
            accumulated += delta
            store.receive(run["run_id"], "turn-partial", accumulated, complete=False)

        with pytest.raises(ModelAPIError, match="流未完整结束"):
            asyncio.run(model.complete_turn([], [], on_text_delta=persist_delta))

        restored = DraftStore(tmp_path)
        received = restored.received(run["run_id"], "turn-partial")
        current = restored.load(run["run_id"])
        assert received == {
            "turn_id": "turn-partial",
            "text": partial,
            "complete": False,
            "persisted_bytes": len(partial.encode("utf-8")),
        }
        assert current["draft_revision"] == 0
        assert current["turns"] == []
        assert current["received_turn_id"] == "turn-partial"


def test_incomplete_chat_tool_arguments_never_return_a_tool_call() -> None:
    """验证工具参数未闭合時拒绝完整 turn 与 ToolCall。

    依赖：NativeEndpoint、chat SSE decoder 与 ModelAPIError。
    输入：带真实 call ID 和 finish_reason 但 JSON 参数截断的帧。
    输出：model_protocol 错误，不向调用方交付工具调用。
    实现：完整结束帧触发最终 JSON 解析并确认截断参数被拒绝。
    """
    frames: list[dict | str] = [
        {"choices": [{"index": 0, "delta": {"tool_calls": [{
            "index": 0,
            "id": "call_incomplete_args_11",
            "type": "function",
            "function": {"name": "recall", "arguments": '{"query":'},
        }]}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        "[DONE]",
    ]
    with NativeEndpoint([{"mode": "chat", "frames": frames}]) as endpoint:
        model = _model(endpoint, "chat")
        with pytest.raises(ModelAPIError, match="model_protocol"):
            asyncio.run(model.complete_turn([], []))
        assert len(endpoint.requests) == 1


def test_callback_disk_write_failure_is_reported_as_save_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证真实接收回调的原子落盘失败會中止当前响应。

    依赖：DraftStore.receive、原子 JSON 保存点与 complete_turn。
    输入：实际 SSE 文本及在 received.json 写入边界注入的磁盘错误。
    输出：save_failed 错误，运行中没有伪造 complete turn。
    实现：只拦截 received 快照的磁盘写操作，其余 Store 路径真实执行。
    """
    import novel_rag.generation.store as store_module

    with NativeEndpoint([{"mode": "chat", "frames": [
        {"choices": [{"index": 0, "delta": {"content": "需要保存的正文"}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        "[DONE]",
    ]}]) as endpoint:
        store = DraftStore(tmp_path)
        run = store.create(_binding(), "路线", "请求")
        model = _model(endpoint, "chat")
        original_write = store_module.atomic_write_json

        def fail_received_write(path: Path, value: dict) -> None:
            """依赖：Store 原子 JSON 写入函数。
            输入：目标路径与准备持久化的快照。
            输出：received.json 触发模拟磁盘错误，其他写入正常。
            实现：在底层写入 seam 注入 OSError 以走真实回调错误处理。
            """
            if Path(path).name == "received.json":
                raise OSError("simulated disk full")
            original_write(path, value)

        monkeypatch.setattr(store_module, "atomic_write_json", fail_received_write)

        async def persist_delta(delta: str) -> None:
            """依赖：DraftStore.receive。
            输入：complete_turn 实际文本增量。
            输出：无或底层磁盘错误。
            实现：将本次累计文本交给真实 Store 接收路径。
            """
            store.receive(run["run_id"], "turn-save-failure", delta, complete=False)

        with pytest.raises(ModelAPIError, match="save_failed"):
            asyncio.run(model.complete_turn([], [], on_text_delta=persist_delta))
        assert DraftStore(tmp_path).load(run["run_id"])["turns"] == []


def test_cancel_waiting_for_headers_cleans_up_and_allows_next_request() -> None:
    """验证等待响应头時取消會关闭请求并允许同 client 后续请求。

    依赖：NativeEndpoint 的有限 header barrier 与 asyncio.Event。
    输入：一个阻塞首响应头的请求和一个成功 JSON 后续响应。
    输出：首请求取消，释放服务线程后第二请求成功。
    实现：等本地 handler 记录真实请求后取消，再释放 gate 并复用 endpoint。
    """
    async def scenario() -> None:
        """依赖：HTTPX cancel_signal 和 fixture request condition。
        输入：header barrier、取消事件与两次请求脚本。
        输出：取消清理及可继续使用的模型 client。
        实现：限时等待到达、取消首任务、释放 gate 后发送新请求。
        """
        header_gate = threading.Event()
        response = {"choices": [{"message": {"role": "assistant", "content": "第二次成功"},
                                 "finish_reason": "stop"}]}
        with NativeEndpoint([
            {"mode": "chat", "wait_headers": header_gate, "json": {}},
            {"mode": "chat", "json": response},
        ]) as endpoint:
            model = _model(endpoint, "chat")
            cancel = asyncio.Event()
            first = asyncio.create_task(model.complete_turn([], [], cancel_signal=cancel))
            try:
                assert await asyncio.to_thread(endpoint.wait_for_requests, 1, 2.0)
                assert endpoint.thread is not None and endpoint.thread.is_alive()
                cancel.set()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(first, timeout=2.0)
            finally:
                header_gate.set()
                if not first.done():
                    first.cancel()
                    await asyncio.gather(first, return_exceptions=True)

            next_turn = await model.complete_turn([], [], {"stream": False})
            assert next_turn.text == "第二次成功"
            assert endpoint.wait_for_requests(2)
        assert endpoint.thread is not None and not endpoint.thread.is_alive()
        assert all(not thread.is_alive() for thread in endpoint.request_threads)

    asyncio.run(scenario())


def test_cancel_mid_stream_cleans_up_and_allows_next_request() -> None:
    """验证收到流中公开文本後取消會保留前缀并允许新请求。

    依赖：NativeEndpoint 的 after_first barrier 与 complete_turn 回调。
    输入：首帧阻塞的 chat SSE、取消事件和后续 JSON 脚本。
    输出：首 turn 取消，后续请求成功且服务线程可关闭。
    实现：等待真实 delta 通知后取消，并在清理路径释放服务端 gate。
    """
    async def scenario() -> None:
        """依赖：HTTPX cancellation、asyncio.Event 与 fixture barrier。
        输入：首帧文本、客户端取消事件和后续响应。
        输出：可证实的流中取消及同端点重用。
        实现：回调通知测试线程，再取消并在 finally 释放 stream gate。
        """
        first_frame_gate = threading.Event()
        response = {"choices": [{"message": {"role": "assistant", "content": "取消后继续"},
                                 "finish_reason": "stop"}]}
        with NativeEndpoint([
            {"mode": "chat", "frames": [
                {"choices": [{"index": 0, "delta": {"content": "已接收前缀"}}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                "[DONE]",
            ], "after_first": first_frame_gate},
            {"mode": "chat", "json": response},
        ]) as endpoint:
            model = _model(endpoint, "chat")
            cancel = asyncio.Event()
            delta_received = asyncio.Event()

            async def observe_delta(_delta: str) -> None:
                """依赖：complete_turn 的文本 callback。
                输入：真实到达的 SSE delta。
                输出：设置测试同步事件。
                实现：通知 scenario 在首帧持久交付後发起取消。
                """
                delta_received.set()

            first = asyncio.create_task(model.complete_turn([], [], cancel_signal=cancel,
                                                             on_text_delta=observe_delta))
            try:
                await asyncio.wait_for(delta_received.wait(), timeout=2.0)
                cancel.set()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(first, timeout=2.0)
            finally:
                first_frame_gate.set()
                if not first.done():
                    first.cancel()
                    await asyncio.gather(first, return_exceptions=True)

            next_turn = await model.complete_turn([], [], {"stream": False})
            assert next_turn.text == "取消后继续"
            assert endpoint.wait_for_requests(2)
        assert endpoint.thread is not None and not endpoint.thread.is_alive()
        assert all(not thread.is_alive() for thread in endpoint.request_threads)

    asyncio.run(scenario())
