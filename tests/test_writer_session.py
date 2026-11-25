from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from native_http_fixture import NativeEndpoint
from novel_rag.generation.session import RunService
from novel_rag.generation.store import DraftStore, StoreConflict
from novel_rag.identity import GraphKey
from novel_rag.memory.service import MemoryService
from novel_rag.model_config.store import ModelConfigStore
from novel_rag.service import load_story_sources
from writer_fixtures import make_library, put_document


def _runtime(root: Path, workspace: Path, endpoint: NativeEndpoint, mode: str):
    """依赖：RunService、DraftStore、MemoryService 与本地模型配置。
    输入：临时资料库、工作区、fixture 端点和原生协议。
    输出：真实本地创作服务及持久化组件。
    实现：保存不含凭证的 HTTPX profile 并注入真实 Store/Memory。
    """
    assert endpoint.base_url is not None
    store = DraftStore(workspace)
    memory = MemoryService(root, store)
    config = ModelConfigStore(workspace / "model-config.json")
    config.set_profile("fixture", {
        "base_url": endpoint.base_url,
        "model": "writer-fixture",
        "mode": mode,
        "no_auth": True,
        "timeout": 3,
        "retries": 0,
    })
    return RunService(root, store, memory, config), store, memory, config


def _tool_response(mode: str, calls: list[dict]) -> dict:
    """依赖：OpenAI chat/responses 原生 SSE 形状。
    输入：测试手写的 call_id/name/arguments 列表。
    输出：fixture 可发送的 SSE 响应脚本。
    实现：独立编码 function-call item 并以完整终止事件封口。
    """
    if mode == "chat":
        fragments = [{
            "index": index,
            "id": call["call_id"],
            "type": "function",
            "function": {
                "name": call["name"],
                "arguments": json.dumps(call["arguments"], ensure_ascii=False),
            },
        } for index, call in enumerate(calls)]
        return {"frames": [
            {"id": "chatcmpl_session_fixture", "choices": [{"index": 0, "delta": {"tool_calls": fragments}}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            "[DONE]",
        ]}
    output = [{
        "type": "function_call",
        "id": "fc_" + call["call_id"],
        "call_id": call["call_id"],
        "name": call["name"],
        "arguments": json.dumps(call["arguments"], ensure_ascii=False),
    } for call in calls]
    events = [
        {"type": "response.output_item.added", "output_index": index, "item": item}
        for index, item in enumerate(output)
    ]
    events.extend({"type": "response.function_call_arguments.delta", "item_id": item["id"],
                   "delta": item["arguments"]} for item in output)
    events.append({"type": "response.completed", "response": {
        "id": "resp_session_fixture", "status": "completed", "output": output,
        "usage": {"input_tokens": 12, "output_tokens": 9},
    }})
    return {"frames": events}


def _text_response(mode: str, text: str, *, reasoning_token: str | None = None) -> dict:
    """依赖：OpenAI chat/responses 原生 SSE 形状。
    输入：协议名、公开终稿及可选 Responses 继续项。
    输出：fixture 用完整文本响应脚本。
    实现：以独立手写的终止结构返回公开文本，推理只放在原始 output。
    """
    if mode == "chat":
        return {"frames": [
            {"choices": [{"index": 0, "delta": {"role": "assistant", "content": text}}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            "[DONE]",
        ]}
    output = []
    if reasoning_token:
        output.append({"type": "reasoning", "id": "rs_parent", "encrypted_content": reasoning_token})
    output.append({"type": "message", "id": "msg_session_final", "role": "assistant",
                   "content": [{"type": "output_text", "text": text}]})
    return {"frames": [
        {"type": "response.output_text.delta", "delta": text},
        {"type": "response.completed", "response": {
            "id": "resp_session_final", "status": "completed", "output": output,
            "usage": {"input_tokens": 14, "output_tokens": 11},
        }},
    ]}


def _tool_outputs(body: dict, mode: str) -> dict[str, dict]:
    """依赖：两种原生 follow-up 消息形状与 JSON。
    输入：实际记录的下一请求 body。
    输出：按原 call_id 解码的工具结果映射。
    实现：只读取 chat tool 消息或 Responses function_call_output 项。
    """
    if mode == "chat":
        return {message["tool_call_id"]: json.loads(message["content"])
                for message in body["messages"] if message.get("role") == "tool"}
    return {item["call_id"]: json.loads(item["output"])
            for item in body["input"] if item.get("type") == "function_call_output"}


def _user_payload(body: dict, mode: str) -> dict:
    """依赖：build_context 的实际模型请求格式。
    输入：记录到的 chat/responses 请求体。
    输出：从 user message 解析的上下文 JSON。
    实现：定位 user role 并解析其原始 UTF-8 content。
    """
    messages = body["messages"] if mode == "chat" else body["input"]
    user = next(message for message in messages if message.get("role") == "user")
    return json.loads(user["content"])


@pytest.mark.parametrize("mode", ["chat", "responses"])
def test_writer_session_runs_real_tools_then_finishes_without_adopting_history(
    tmp_path: Path, mode: str,
) -> None:
    """验证原生会话按真实工具结果连续运行并保持正式前文不变。

    依赖：RunService、真实 YAML SourceCorpus、DraftStore 和本地 HTTPX endpoint。
    输入：原始大纲、选定正式章节及 recall/read/save/remember 调用。
    输出：完整终稿、真实记忆来源与未变更 History 字节。
    实现：回调从实际 save_draft 工具输出取 DraftRef，再动态生成 remember 帧。
    """
    async def scenario() -> None:
        """依赖：真实 RunService 异步单槽与 endpoint callback。
        输入：四工具首轮、含真实检查点的 remember 次轮及终稿响应。
        输出：可从 run.json 和 HTTP 请求复核的成功会话。
        实现：先执行真实工具副作用，再核对后续请求中的原 call_id 和结果。
        """
        root = make_library(tmp_path)
        history_text = "正式第一章：乙把旧钥匙交给甲。\n"
        history_path = put_document(root, "chapter-one", history_text, chapter=1, scene=1)
        scope = GraphKey("demo", "main")
        source_corpus = load_story_sources(root, scope)
        source_ref = source_corpus.source_refs["chapter-one"].as_dict()
        selected_original = source_corpus.read("chapter-one")[0].searchable_text()
        history_bytes = history_path.read_bytes()
        outline = "先写两人寻找旧屋，再让乙交出钥匙。"
        request = "以甲的视角续写，保留潮湿山路的气味。"
        checkpoint_text = "检查点正文：甲沿着潮湿山路走向旧屋。"
        final_text = checkpoint_text + "\n雨水沿石阶落下，甲接过钥匙，没有立刻开门。"
        first_calls = [
            {"call_id": "call-session-recall", "name": "recall", "arguments": {"query": "旧屋钥匙"}},
            {"call_id": "call-session-read", "name": "read_document", "arguments": {"document_id": "chapter-one"}},
            {"call_id": "call-session-save", "name": "save_draft", "arguments": {
                "text": checkpoint_text, "expected_revision": 0,
            }},
        ]
        observed: dict[str, dict] = {}

        def remember_from_real_save(request_record: dict) -> dict:
            """依赖：实际 follow-up body 和独立工具响应编码器。
            输入：RunService 发来的真实工具结果请求。
            输出：使用刚保存 DraftRef 的 remember SSE。
            实现：从 save_draft 原 call_id 的结果 JSON 取引用，不伪造身份/hash。
            """
            outputs = _tool_outputs(request_record["body"], mode)
            draft_ref = outputs["call-session-save"]
            observed["draft_ref"] = draft_ref
            remember_args = {
                "draft_ref": draft_ref,
                "expected_memory_revision": 0,
                "update": {"state_changes": [{
                    "op": "set",
                    "local_ref": "key-custody",
                    "entry": {"domain": "World", "kind": "custody",
                              "value": "旧钥匙目前由甲保管。", "lifetime": "carry"},
                }]},
            }
            return _tool_response(mode, [{
                "call_id": "call-session-remember", "name": "remember", "arguments": remember_args,
            }])

        with NativeEndpoint([
            {"mode": mode, "callback": lambda _request: _tool_response(mode, first_calls)},
            {"mode": mode, "callback": remember_from_real_save},
            {"mode": mode, "callback": lambda _request: _text_response(mode, final_text)},
        ]) as endpoint:
            service, store, memory, _config = _runtime(root, tmp_path / "workspace", endpoint, mode)
            run_id = service.start(scope, "write", outline, request, base_ref=source_ref, profile_name="fixture")
            result = await service.run(run_id)

            assert result["status"] == "completed"
            assert result["draft_text"] == final_text
            assert result["memory_revision"] == 1
            assert len(result["memory_batches"]) == 1
            assert result["memory_batches"][0]["draft_ref"] == observed["draft_ref"]
            assert result["memory_batches"][0]["source_refs"] == [observed["draft_ref"]]
            assert result["memory_batches"][0]["update"]["state_changes"][0]["entry"]["value"] == "旧钥匙目前由甲保管。"
            assert [call["call_id"] for turn in result["turns"] for call in turn["tool_calls"]] == [
                "call-session-recall", "call-session-read", "call-session-save", "call-session-remember",
            ]
            assert [row["name"] for row in result["tool_results"]] == [
                "recall", "read_document", "save_draft", "remember",
            ]
            assert result["tool_results"][1]["result"]["text"] == selected_original
            assert result["tool_results"][1]["result"]["kind"] == "original"
            assert endpoint.callback_errors == []
            assert history_path.read_bytes() == history_bytes

            first_request = endpoint.requests[0]
            assert first_request["path"] == ("/v1/chat/completions" if mode == "chat" else "/v1/responses")
            body = first_request["body"]
            tools = body["tools"]
            names = [item["function"]["name"] if mode == "chat" else item["name"] for item in tools]
            assert names == ["recall", "read_document", "read_writing_reference", "save_draft", "remember"]
            context = _user_payload(body, mode)
            assert context["outline_original"] == outline
            assert context["request"] == request
            assert context["body_context"] == selected_original
            assert context["baseline"]["source_ref"] == source_ref
            assert context["baseline"]["inline"] is True
            assert all("text" not in item for item in context["references"])

            followup_body = endpoint.requests[1]["body"]
            outputs = _tool_outputs(followup_body, mode)
            assert set(outputs) == {"call-session-recall", "call-session-read", "call-session-save"}
            assert outputs["call-session-save"] == observed["draft_ref"]
            followup_messages = followup_body["messages"] if mode == "chat" else followup_body["input"]
            if mode == "chat":
                assistant = next(item for item in followup_messages
                                 if item.get("role") == "assistant" and item.get("tool_calls"))
                assert [item["id"] for item in assistant["tool_calls"]] == [call["call_id"] for call in first_calls]
            else:
                assert [item["call_id"] for item in followup_messages if item.get("type") == "function_call"] == [
                    call["call_id"] for call in first_calls
                ]

            final_body = endpoint.requests[2]["body"]
            final_outputs = _tool_outputs(final_body, mode)
            assert "call-session-remember" in final_outputs
            assert final_outputs["call-session-remember"]["memory_revision"] == 1
        assert endpoint.thread is not None and not endpoint.thread.is_alive()
        assert all(not thread.is_alive() for thread in endpoint.request_threads)

    asyncio.run(scenario())


def test_writer_finishes_without_remember_and_leaves_formal_history_untouched(tmp_path: Path) -> None:
    """验证记忆工具可选，单次终稿完成且采用前正式章节字节不变。

    依赖：RunService、真实 SourceCorpus/DraftStore 与本地 HTTPX endpoint。
    输入：有正式基线的 write run 和一条无工具终稿响应。
    输出：completed 草稿、memory_revision 为零、History 原字节不变。
    实现：真实请求经本地 endpoint 后读取新的 Store 快照与原 YAML 字节。
    """
    async def scenario() -> None:
        """依赖：RunService 异步会话。
        输入：唯一的最终文本 turn。
        输出：一个已保存草稿且无 remember 批次。
        实现：从正式章节 source ref 启动并运行零记忆工具的会话。
        """
        root = make_library(tmp_path)
        original = "正式第一章内容不能自动并入续写。\n"
        history_path = put_document(root, "chapter-one", original, chapter=1, scene=1)
        before = history_path.read_bytes()
        scope = GraphKey("demo", "main")
        source_ref = load_story_sources(root, scope).source_refs["chapter-one"].as_dict()
        final_text = "第二章从一阵风声开始。"
        with NativeEndpoint([{"mode": "chat", "callback": lambda _request: _text_response("chat", final_text)}]) as endpoint:
            service, _store, _memory, _config = _runtime(root, tmp_path / "workspace", endpoint, "chat")
            run_id = service.start(scope, "write", "写第二章", "让风声先出现。",
                                   base_ref=source_ref, profile_name="fixture")
            result = await service.run(run_id)
            assert result["status"] == "completed"
            assert result["draft_text"] == final_text
            assert result["memory_revision"] == 0
            assert result["memory_batches"] == []
            assert result["draft_ref"] is not None
            assert history_path.read_bytes() == before
            assert len(endpoint.requests) == 1
            assert endpoint.callback_errors == []

    asyncio.run(scenario())


def test_discussion_turn_is_saved_to_session_without_formal_draft(tmp_path: Path) -> None:
    """验证 discuss 只保存会话回答，不创建正文检查点。

    依赖：RunService discuss 分支、DraftStore 和本地 endpoint。
    输入：空本书和一条模型讨论响应。
    输出：discussion_text 有值且 draft_ref/draft_text 为空。
    实现：真实模型请求完成后比较权威 run 快照中的稿件字段。
    """
    async def scenario() -> None:
        """依赖：RunService 异步运行与 config profile。
        输入：discuss 任务和无工具回答。
        输出：已完成讨论快照且不含正文草稿。
        实现：在无正式来源的规范临时库中跑完整本地 HTTP 会话。
        """
        root = make_library(tmp_path)
        scope = GraphKey("demo", "main")
        answer = "这两个人可以先在门口停一停，再决定是否开门。"
        with NativeEndpoint([{"mode": "responses", "callback": lambda _request: _text_response("responses", answer)}]) as endpoint:
            service, store, _memory, _config = _runtime(root, tmp_path / "workspace", endpoint, "responses")
            run_id = service.start(scope, "discuss", "暂不写正文", "讨论两人的犹豫。", profile_name="fixture")
            result = await service.run(run_id)
            assert result["status"] == "completed"
            assert result["discussion_text"] == answer
            assert result["draft_ref"] is None
            assert result["draft_text"] == ""
            assert result["drafts"] == {}
            assert store.load(run_id)["draft_revision"] == 0
            assert endpoint.callback_errors == []

    asyncio.run(scenario())


def test_feedback_branches_from_selected_parent_once_and_discards_old_continuation(tmp_path: Path) -> None:
    """验证同一父检查点可分支续写一次前缀并重建干净上下文。

    依赖：RunService.feedback、DraftStore 父检查点与 Responses continuation。
    输入：含正式前章的父 run、真实 parent DraftRef 和两条子分支。
    输出：分支正文各拼父稿一次，正式前章未拼入，旧推理项未重放。
    实现：从父 turn 保存 opaque continuation，再通过 feedback 检查子请求实际 input。
    """
    async def scenario() -> None:
        """依赖：同一 event loop 中的 RunService 与动态 endpoint。
        输入：父终稿和两个独立续写后缀。
        输出：不同 child run/checkpoint 与各自完整正文。
        实现：先完成父稿，再以相同经核验 checkpoint 启动两条新分支。
        """
        root = make_library(tmp_path)
        formal_text = "正式前章：山门在雨中关闭。\n"
        history_path = put_document(root, "chapter-one", formal_text, chapter=1, scene=1)
        history_bytes = history_path.read_bytes()
        scope = GraphKey("demo", "main")
        source_ref = load_story_sources(root, scope).source_refs["chapter-one"].as_dict()
        prefix = "PARENT_PREFIX◆父稿中已写好的内容。"
        reasoning_sentinel = "opaque-parent-only-continuation"
        observed_child_contexts: list[dict] = []

        def collect_child_a(request_record: dict) -> dict:
            """依赖：实际 Responses child request。
            输入：child A 首轮请求。
            输出：A 分支终稿响应。
            实现：保存真实组装 user payload 后返回独立后缀。
            """
            observed_child_contexts.append(_user_payload(request_record["body"], "responses"))
            return _text_response("responses", "续写A：灯亮了。")

        def collect_child_b(request_record: dict) -> dict:
            """依赖：实际 Responses child request。
            输入：child B 首轮请求。
            输出：B 分支终稿响应。
            实现：保存真实组装 user payload 后返回另一后缀。
            """
            observed_child_contexts.append(_user_payload(request_record["body"], "responses"))
            return _text_response("responses", "续写B：门外有人。")

        with NativeEndpoint([
            {"mode": "responses", "callback": lambda _request: _text_response(
                "responses", prefix, reasoning_token=reasoning_sentinel)},
            {"mode": "responses", "callback": collect_child_a},
            {"mode": "responses", "callback": collect_child_b},
        ]) as endpoint:
            service, store, _memory, _config = _runtime(root, tmp_path / "workspace", endpoint, "responses")
            parent_id = service.start(scope, "write", "第一章路線", "完成父稿。",
                                      base_ref=source_ref, profile_name="fixture")
            parent = await service.run(parent_id)
            parent_ref = parent["draft_ref"]
            assert parent["draft_text"] == prefix
            assert reasoning_sentinel in json.dumps(store.load(parent_id)["turns"][0]["continuation"], ensure_ascii=False)
            assert reasoning_sentinel not in json.dumps(parent, ensure_ascii=False)
            with pytest.raises(StoreConflict, match="所选父检查点不匹配"):
                service.feedback(parent["session_id"], parent_id, "write", "错误父版本",
                                 base_ref=parent_ref, selected_parent_checkpoint="checkpoint-wrong")

            child_a_id = service.feedback(parent["session_id"], parent_id, "write", "沿路继续A",
                                          base_ref=parent_ref, selected_parent_checkpoint=parent_ref["checkpoint_id"])
            child_a = await service.run(child_a_id)
            child_b_id = service.feedback(parent["session_id"], parent_id, "write", "沿路继续B",
                                          base_ref=parent_ref, selected_parent_checkpoint=parent_ref["checkpoint_id"])
            child_b = await service.run(child_b_id)

            assert child_a_id != child_b_id != parent_id
            assert child_a["parent_run_id"] == parent_id == child_b["parent_run_id"]
            assert child_a["binding"]["output_mode"] == child_b["binding"]["output_mode"] == "append_suffix"
            assert child_a["draft_text"] == prefix + "续写A：灯亮了。"
            assert child_b["draft_text"] == prefix + "续写B：门外有人。"
            assert child_a["draft_text"].count(prefix) == 1
            assert child_b["draft_text"].count(prefix) == 1
            assert formal_text not in child_a["draft_text"] + child_b["draft_text"]
            assert len(observed_child_contexts) == 2
            for context in observed_child_contexts:
                assert context["output_mode"] == "append_suffix"
                assert context["body_context"] == prefix
                assert context["outline_original"] == "第一章路線"
            assert reasoning_sentinel not in json.dumps(endpoint.requests[1]["body"], ensure_ascii=False)
            assert reasoning_sentinel not in json.dumps(endpoint.requests[2]["body"], ensure_ascii=False)
            assert child_a["draft_ref"]["checkpoint_id"] != child_b["draft_ref"]["checkpoint_id"]
            assert history_path.read_bytes() == history_bytes
            assert endpoint.callback_errors == []

    asyncio.run(scenario())


def test_early_revise_uses_before_state_and_reads_original_as_edit_reference(tmp_path: Path) -> None:
    """验证早章改写不带入未来状态且原章仍可作修改参考。

    依赖：RunService revise context、真实未来 SourceRef 与 read_document。
    输入：早章、后续章及引用后续章的投影批次。
    输出：实际 user context 状态不含未来条目，工具返回 edit_reference 原文。
    实现：创建带真实 future document ref 的投影 YAML，再观察模型请求与工具结果。
    """
    async def scenario() -> None:
        """依赖：真实 MemoryService 游标、ToolDispatcher 和本地 endpoint。
        输入：before 目标坐标的 revise run 与一次原章读取调用。
        输出：章前上下文及实际 edit_reference 读取证据。
        实现：通过完整 HTTP 工具循环核对初始 state 与原文回读。
        """
        root = make_library(tmp_path)
        scope = GraphKey("demo", "main")
        early_text = "第一章原文：甲把旧地图折好。\n"
        future_text = "第二章原文：暴风雪封住山口，乙才得知路线。\n"
        put_document(root, "chapter-early", early_text, chapter=1, scene=2)
        put_document(root, "chapter-future", future_text, chapter=1, scene=4)
        full = load_story_sources(root, scope)
        early_ref = full.source_refs["chapter-early"].as_dict()
        future_ref = full.source_refs["chapter-future"].as_dict()
        future_value = "FUTURE_STATE_MUST_NOT_APPEAR_BEFORE_CHAPTER_ONE"
        future_entry = {
            "entry_id": "state-future-wind",
            "domain": "World",
            "kind": "weather",
            "value": future_value,
            "lifetime": "carry",
            "source_refs": [future_ref],
        }
        future_batch = {
            "batch_id": "batch-after-chapter-one",
            "memory_revision": 1,
            "source_refs": [future_ref],
            "narrative_position": {"kind": "document", "document_id": "chapter-future"},
            "update": {"state_changes": [{"op": "set", "entry_id": "state-future-wind",
                                           "entry": future_entry, "source_refs": [future_ref]}]},
        }
        put_document(root, "early-summary", "旧章节的展示摘要。", category="summary", chapter=1, scene=1,
                     extra_metadata={"memory_schema_version": 3, "memory_kind": "memory_projection",
                                     "source_refs": [future_ref], "coverage": {"kind": "document"},
                                     "memory_batches": [future_batch]})
        revise_corpus = load_story_sources(root, scope)
        target = revise_corpus.source_refs["chapter-early"].as_dict()
        expected_edit_reference = revise_corpus.read("chapter-early")[0].searchable_text()
        observed: dict[str, dict] = {}
        read_call = {"call_id": "call-edit-reference", "name": "read_document",
                     "arguments": {"document_id": "chapter-early"}}

        def finish_after_read(request_record: dict) -> dict:
            """依赖：真实 read_document tool result 与 Responses/Chat body codec。
            输入：含 read_document 原 call_id 的后续请求。
            输出：修改后的正文 turn。
            实现：记录实际 edit_reference 内容后给出终稿文本。
            """
            observed["read"] = _tool_outputs(request_record["body"], "chat")["call-edit-reference"]
            return _text_response("chat", "修订后的第一章正文。")

        with NativeEndpoint([
            {"mode": "chat", "callback": lambda _request: _tool_response("chat", [read_call])},
            {"mode": "chat", "callback": finish_after_read},
        ]) as endpoint:
            service, _store, _memory, _config = _runtime(root, tmp_path / "workspace", endpoint, "chat")
            run_id = service.start(scope, "revise", "保留地图交接", "改写第一章开头。",
                                   base_ref=target, profile_name="fixture")
            result = await service.run(run_id)

            assert result["status"] == "completed"
            assert result["binding"]["narrative_cursor"]["endpoint"] == "before"
            assert result["binding"]["target_coordinate"] == target["coordinate"]
            initial = endpoint.requests[0]["body"]
            context = _user_payload(initial, "chat")
            assert context["task_kind"] == "revise"
            assert context["edit_reference"] == expected_edit_reference
            assert "body_context" not in context
            state = service.memory.recall(run_id)["state_view"]
            assert state["entries"] == []
            assert state["recorded_through"] is None
            assert context["memory"]["recorded_through"] is None
            assert future_value not in json.dumps(context, ensure_ascii=False)
            assert future_text not in json.dumps(context, ensure_ascii=False)
            assert observed["read"]["kind"] == "edit_reference"
            assert observed["read"]["text"] == expected_edit_reference
            assert observed["read"]["source_ref"] == target
            assert result["draft_text"] == "修订后的第一章正文。"
            assert endpoint.callback_errors == []

    asyncio.run(scenario())
