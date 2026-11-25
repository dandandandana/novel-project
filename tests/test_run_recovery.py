from __future__ import annotations

import asyncio
from pathlib import Path
import threading

from native_http_fixture import NativeEndpoint
from novel_rag.generation.store import DraftStore
from novel_rag.identity import GraphKey
from writer_fixtures import make_library

from test_writer_session import _runtime, _text_response


def _partial_chat_frame(call_id: str = "call-incomplete") -> dict:
    """依赖：原生 Chat SSE delta 形状。
    输入：不完整工具调用的 call_id。
    输出：同时含公开文本与截断 remember 参数的首帧。
    实现：故意不给 finish_reason 和完整 JSON 参数，验证调用不会提交。
    """
    return {
        "id": "chatcmpl_partial_fixture",
        "choices": [{"index": 0, "delta": {
            "content": "已经接收的部分正文。",
            "tool_calls": [{
                "index": 0,
                "id": call_id,
                "type": "function",
                "function": {"name": "remember", "arguments": '{"draft_ref":'},
            }],
        }}],
    }


def test_late_model_completion_is_saved_beside_author_edit_without_moving_pointer(tmp_path: Path) -> None:
    """验证作者编辑先提交后，迟到模型正文另存且不覆盖作者指针。

    依赖：真实 RunService/DraftStore 与本地 HTTP 响应 barrier。
    输入：等待响应头的正文请求、作者 CAS 保存和迟到模型终稿。
    输出：author draft 仍被选中，generated draft 可按真实 DraftRef 读取。
    实现：实际请求被 callback 暂停，作者写入后再释放模型响应并重开 Store 校验。
    """
    async def scenario() -> None:
        """依赖：同一 event loop 中的 RunService 与线程安全本地 endpoint。
        输入：受控延迟的终稿及运行期间的作者保存。
        输出：含作者稿和迟到生成稿的持久快照。
        实现：等待真实 POST 记录，完成 author revision CAS 后放行 HTTP 响应。
        """
        root = make_library(tmp_path)
        workspace = tmp_path / "workspace"
        release_response = threading.Event()
        final_text = "模型迟到终稿：灯亮在旧屋窗后。"

        def delayed_final(_request: dict) -> dict:
            """依赖：有限响应 barrier 与独立手写 SSE 文本响应。
            输入：已记录的真实模型请求。
            输出：barrier 释放后的终稿响应脚本。
            实现：在 HTTP handler 线程等待作者保存，再返回完整 Chat turn。
            """
            release_response.wait(5)
            return _text_response("chat", final_text)

        with NativeEndpoint([{"mode": "chat", "callback": delayed_final}], barrier_timeout=5) as endpoint:
            service, store, _memory, _config = _runtime(root, workspace, endpoint, "chat")
            run_id = service.start(GraphKey("demo", "main"), "write", "先寻找旧屋", "写出灯亮的一刻。",
                                   profile_name="fixture")
            running = asyncio.create_task(service.run(run_id))
            assert await asyncio.to_thread(endpoint.wait_for_requests, 1, 2)
            author_text = "作者先改成：雨停以后，窗里亮起一盏灯。"
            author_ref = store.save(run_id, 0, author_text, origin="author")
            release_response.set()
            result = await running

            assert result["status"] == "completed"
            assert result["author_revision"] == 1
            assert result["draft_ref"] == author_ref.as_dict()
            assert result["draft_text"] == author_text
            assert result["generated_draft_text"] == final_text
            assert result["generated_draft_ref"]["checkpoint_id"] != author_ref.checkpoint_id
            generated_run, generated_text = store.resolve_draft(result["generated_draft_ref"])
            assert generated_run["run_id"] == run_id
            assert generated_text == final_text
            assert result["drafts"][author_ref.checkpoint_id]["origin"] == "author"
            assert result["drafts"][result["generated_draft_ref"]["checkpoint_id"]]["origin"] == "model"
            assert endpoint.callback_errors == []

            reopened = DraftStore(workspace)
            persisted = reopened.snapshot(run_id)
            assert persisted["draft_ref"] == author_ref.as_dict()
            assert persisted["draft_text"] == author_text
            assert reopened.resolve_draft(persisted["generated_draft_ref"])[1] == final_text
        assert endpoint.thread is not None and not endpoint.thread.is_alive()
        assert all(not thread.is_alive() for thread in endpoint.request_threads)

    asyncio.run(scenario())


def test_cancelled_or_truncated_stream_keeps_partial_on_reopened_store_and_skips_incomplete_call(
    tmp_path: Path,
) -> None:
    """验证取消及断流都保留 partial，重开 Store 可读且不执行未完整工具调用。

    依赖：RunService transport cancel、NativeEndpoint SSE barrier 和 DraftStore received 文件。
    输入：取消场景与缺少 finish marker 的真实 Chat SSE 流。
    输出：partial、连续事件与prepared发送绑定已持久化，无完整turn/工具副作用，新实例可继续。
    实现：首帧携带截断 remember 参数，分别取消/断流后重开并核对已发布前缀，再发起新回合。
    """
    async def scenario() -> None:
        """依赖：两个真实 RunService 实例、同一工作区与可控 localhost 端点。
        输入：stream 中取消和未终止断流两个真实传输结局。
        输出：原run接收前缀、连续公开事件、prepared绑定、未执行工具证据与新run完成快照。
        实现：在首帧事件后取消或让 EOF 缺少终止事件，再用新 Store/profile 完成新请求。
        """
        root = make_library(tmp_path)
        workspace = tmp_path / "workspace"
        scope = GraphKey("demo", "main")
        first_frame_sent = threading.Event()
        release_stream = threading.Event()
        partial_frame = _partial_chat_frame()
        with NativeEndpoint([{
            "mode": "chat",
            "frames": [partial_frame],
            "first_frame_sent": first_frame_sent,
            "after_first": release_stream,
        }], barrier_timeout=5) as endpoint:
            service, first_store, _memory, _config = _runtime(root, workspace, endpoint, "chat")
            cancelled_id = service.start(scope, "write", "原始路线", "先写一个开头。", profile_name="fixture")
            running = asyncio.create_task(service.run(cancelled_id))
            assert await asyncio.to_thread(endpoint.wait_for_requests, 1, 2)
            assert await asyncio.to_thread(first_frame_sent.wait, 2)
            requested = service.cancel(cancelled_id)
            assert requested["cancel_requested"] is True
            release_stream.set()
            cancelled = await running
            assert cancelled["status"] == "cancelled"
            assert cancelled["received_text"] == "已经接收的部分正文。"
            assert cancelled["draft_revision"] == 0
            assert cancelled.get("tool_results", []) == []
            assert len(cancelled["turns"]) == 1
            assert cancelled["turns"][0]["request_status"] == "prepared"
            assert cancelled["turns"][0]["tool_calls"] is None
            assert cancelled["turns"][0]["attempt_id"]
            assert cancelled["turns"][0]["request_manifest"]["material_binding"]["author_revision"] == 0
            assert not any(event["type"] == "tool_started" for event in cancelled["events"])
            assert endpoint.callback_errors == []

        assert endpoint.thread is not None and not endpoint.thread.is_alive()
        assert all(not thread.is_alive() for thread in endpoint.request_threads)
        reopened_store = DraftStore(workspace)
        recovered_cancel = reopened_store.snapshot(cancelled_id)
        assert recovered_cancel["received_text"] == "已经接收的部分正文。"
        assert recovered_cancel["status"] == "cancelled"
        events = recovered_cancel["events"]
        assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
        assert [event["payload"] for event in events if event["type"] == "text_delta"] == [
            {"turn_id": recovered_cancel["received_turn_id"], "text": recovered_cancel["received_text"]},
        ]

        # A fresh model profile and Service use the same disk workspace after cancellation.
        with NativeEndpoint([{"mode": "chat", "callback": lambda _request: _text_response(
            "chat", "恢复后新请求成功完成。") }]) as next_endpoint:
            next_service, next_store, _memory, _config = _runtime(root, workspace, next_endpoint, "chat")
            next_id = next_service.start(scope, "write", "原始路线", "从新请求重新生成。", profile_name="fixture")
            next_result = await next_service.run(next_id)
            assert next_result["status"] == "completed"
            assert next_result["draft_text"] == "恢复后新请求成功完成。"
            assert next_store.snapshot(cancelled_id)["received_text"] == "已经接收的部分正文。"
            assert next_endpoint.callback_errors == []

        # A truncated transport with no terminal event must also be recoverable from disk.
        with NativeEndpoint([{
            "mode": "chat",
            "frames": [_partial_chat_frame("call-truncated")],
        }], barrier_timeout=5) as broken_endpoint:
            broken_service, broken_store, _memory, _config = _runtime(root, workspace, broken_endpoint, "chat")
            broken_id = broken_service.start(scope, "write", "原始路线", "测试断流保存。", profile_name="fixture")
            broken = await broken_service.run(broken_id)
            assert broken["status"] == "failed"
            assert broken["error"]["code"] == "model_protocol"
            assert broken["received_text"] == "已经接收的部分正文。"
            assert broken["draft_revision"] == 0
            assert broken.get("tool_results", []) == []
            assert len(broken["turns"]) == 1
            assert broken["turns"][0]["request_status"] == "prepared"
            assert broken["turns"][0]["tool_calls"] is None
            assert not any(event["type"] == "tool_started" for event in broken["events"])
            assert broken_endpoint.callback_errors == []
            disk_after_break = DraftStore(workspace).snapshot(broken_id)
            assert disk_after_break["received_text"] == "已经接收的部分正文。"
            events = disk_after_break["events"]
            assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
            assert [event["payload"] for event in events if event["type"] == "text_delta"] == [
                {"turn_id": disk_after_break["received_turn_id"], "text": disk_after_break["received_text"]},
            ]
            assert broken_store.received(broken_id)["complete"] is False
        assert broken_endpoint.thread is not None and not broken_endpoint.thread.is_alive()
        assert all(not thread.is_alive() for thread in broken_endpoint.request_threads)

        # The reopened instance remains able to dispatch another normal run.
        with NativeEndpoint([{"mode": "chat", "callback": lambda _request: _text_response(
            "chat", "断流后新请求也能运行。") }]) as retry_endpoint:
            retry_service, retry_store, _memory, _config = _runtime(root, workspace, retry_endpoint, "chat")
            retry_id = retry_service.start(scope, "write", "原始路线", "断流后重新请求。", profile_name="fixture")
            retry_result = await retry_service.run(retry_id)
            assert retry_result["status"] == "completed"
            assert retry_result["draft_text"] == "断流后新请求也能运行。"
            assert retry_store.snapshot(broken_id)["received_text"] == "已经接收的部分正文。"
            assert retry_endpoint.callback_errors == []

    asyncio.run(scenario())


def test_cancel_while_waiting_for_response_headers_closes_transport_and_allows_new_run(tmp_path: Path) -> None:
    """验证等待 HTTP 响应头时取消会清理请求，且同工作区可启动新会话。

    依赖：RunService.cancel、有限 header barrier、重开的 DraftStore 与 localhost endpoint。
    输入：被响应头 barrier 挂起的 Chat 请求和下一次正常文本请求。
    输出：首run取消后保留prepared绑定但无正文提交，新Service可完成全新run。
    实现：等 fixture 确认 handler 正等响应头后发 cancel，再释放服务端并换 endpoint 重启。
    """
    async def scenario() -> None:
        """依赖：异步 RunService 与 fixture 请求/等待事件。
        输入：一个 header-pending run 和一条恢复后的普通响应。
        输出：取消快照含请求前绑定及新run成功快照。
        实现：在明确的 header wait 点取消，确认HTTP handler和后续单槽请求均结束。
        """
        root = make_library(tmp_path)
        workspace = tmp_path / "workspace"
        scope = GraphKey("demo", "main")
        release_headers, waiting_headers = threading.Event(), threading.Event()
        delayed_json = {"choices": [{"message": {"role": "assistant", "content": "迟到内容不得提交。"},
                                      "finish_reason": "stop"}]}
        with NativeEndpoint([{
            "mode": "chat",
            "json": delayed_json,
            "wait_headers": release_headers,
            "headers_waiting": waiting_headers,
        }], barrier_timeout=5) as endpoint:
            service, store, _memory, _config = _runtime(root, workspace, endpoint, "chat")
            run_id = service.start(scope, "write", "路线", "等待响应头时取消。", profile_name="fixture")
            running = asyncio.create_task(service.run(run_id))
            assert await asyncio.to_thread(endpoint.wait_for_requests, 1, 2)
            assert await asyncio.to_thread(waiting_headers.wait, 2)
            assert service.cancel(run_id)["cancel_requested"] is True
            release_headers.set()
            result = await running
            assert result["status"] == "cancelled"
            assert result["draft_revision"] == 0
            assert result["received_text"] == ""
            assert len(result["turns"]) == 1
            assert result["turns"][0]["request_status"] == "prepared"
            assert result["turns"][0]["tool_calls"] is None
            assert result["turns"][0]["request_manifest"]["material_binding"]["draft_ref"] is None
            assert endpoint.callback_errors == []
            assert store.snapshot(run_id)["status"] == "cancelled"

        assert endpoint.thread is not None and not endpoint.thread.is_alive()
        assert all(not thread.is_alive() for thread in endpoint.request_threads)
        with NativeEndpoint([{"mode": "chat", "callback": lambda _request: _text_response(
            "chat", "取消清理后仍可正常写作。") }]) as next_endpoint:
            next_service, next_store, _memory, _config = _runtime(root, workspace, next_endpoint, "chat")
            next_id = next_service.start(scope, "write", "路线", "新请求继续。", profile_name="fixture")
            next_result = await next_service.run(next_id)
            assert next_result["status"] == "completed"
            assert next_result["draft_text"] == "取消清理后仍可正常写作。"
            assert next_store.snapshot(run_id)["status"] == "cancelled"
            assert next_endpoint.callback_errors == []

    asyncio.run(scenario())
