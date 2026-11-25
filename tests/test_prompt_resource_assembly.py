from __future__ import annotations

import asyncio
import hashlib
from importlib.resources import files
import json
from pathlib import Path

from native_http_fixture import NativeEndpoint
from novel_rag.generation.context import WRITER_PROMPT
from novel_rag.generation.tools import writing_resources
from novel_rag.identity import GraphKey
from novel_rag.service import load_story_sources
from writer_fixtures import make_library, write_yaml

from test_writer_session import _runtime, _text_response, _tool_outputs, _tool_response


def test_real_writer_prompt_keeps_r13_as_eight_hash_verified_on_demand_fragments(tmp_path: Path) -> None:
    """验证真实系统提示常驻信息边界，R13及玄鉴结构参考各自按需且源hash可核验。

    依赖：真实 RunService/build_context、writing_resources、独立参考来源、本地原生 Chat endpoint。
    输入：含隔离 style_audit 文档的临时作品线和一次 read_writing_reference 调用。
    输出：实际system/user请求无旧审计，原八片段与新增结构参考分别核验且只在工具结果含样例。
    实现：发起完整本地模型会话，检查线上序列化请求及真实 reference tool result。
    """
    async def scenario() -> None:
        """依赖：RunService 和实际 R13/StyleAudit 文件读取路径。
        输入：一个真实参考工具调用及最终正文响应。
        输出：system prompt、工具返回内容和来源摘要的可复核断言。
        实现：从 endpoint 录制的首请求读取最终组装指令，再核对后续 tool output。
        """
        root = make_library(tmp_path)
        scope = GraphKey("demo", "main")
        style_marker = "STYLE_AUDIT_MUST_NOT_ENTER_INITIAL_INSTRUCTIONS"
        style_path = root / "stories" / "demo" / "timelines" / "main" / "system-overrides" / "style-audit" / "style.yaml"
        write_yaml(style_path, {
            "metadata": {
                "document_id": "style-audit-only",
                "story_id": "demo",
                "timeline_id": "main",
                "document_type": "style_audit",
                "module_type": "style",
                "title": "style audit isolation fixture",
                "status": "active",
                "version": "1",
            },
            "text": style_marker,
        })

        resources_path = files("novel_rag.generation").joinpath("resources.json")
        resource_map = writing_resources()
        source_path = Path(__file__).parents[1] / "docs" / "references" / "kardia-r13-full-symbolic-lean.source.txt"
        actual_source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        r13_resources = {key: item for key, item in resource_map.items()
                         if item["source"]["asset"] == "docs/references/kardia-r13-full-symbolic-lean.source.txt"}
        assert len(r13_resources) == 8
        assert set(resource_map) - set(r13_resources) == {"information_transmission"}
        assert all(item["kind"] == "writing_reference" and item["source"]["provided_fragment"]
                   for item in r13_resources.values())
        assert all(item["source"]["asset"] == "docs/references/kardia-r13-full-symbolic-lean.source.txt"
                   for item in r13_resources.values())
        assert {item["source"]["source_sha256"] for item in r13_resources.values()} == {actual_source_hash}
        information = resource_map["information_transmission"]
        information_source = Path(__file__).parents[1] / information["source"]["asset"]
        assert information["source"]["source_sha256"] == hashlib.sha256(information_source.read_bytes()).hexdigest()
        assert information["source"]["provided_fragment"] is False
        assert len(information["source"]["reference_urls"]) == 5
        for adaptation in information["source"]["adaptation_sources"]:
            adaptation_source = Path(__file__).parents[1] / adaptation["asset"]
            assert adaptation["provided_fragment"] is True
            assert adaptation["source_sha256"] == hashlib.sha256(adaptation_source.read_bytes()).hexdigest()
        assert json.loads(resources_path.read_text(encoding="utf-8")) == resource_map
        assert load_story_sources(root, scope).documents == ()

        chosen = resource_map["natural_dialogue"]
        calls = [{"call_id": "call-r13-natural-dialogue", "name": "read_writing_reference",
                  "arguments": {"resource_id": "natural_dialogue"}}]
        observed: dict[str, dict] = {}

        def finish_after_reference(request_record: dict) -> dict:
            """依赖：真实 Chat follow-up 工具结果与手写文本响应。
            输入：RunService 发出的 function result 请求体。
            输出：最终正文响应脚本。
            实现：保存原call_id对应的实际片段后给出终止文本turn。
            """
            observed["reference"] = _tool_outputs(request_record["body"], "chat")[calls[0]["call_id"]]
            return _text_response("chat", "雨停后，旧屋窗里亮起一盏灯。")

        with NativeEndpoint([
            {"mode": "chat", "callback": lambda _request: _tool_response("chat", calls)},
            {"mode": "chat", "callback": finish_after_reference},
        ]) as endpoint:
            service, _store, _memory, _config = _runtime(root, tmp_path / "workspace", endpoint, "chat")
            run_id = service.start(scope, "write", "沿着旧地图找到屋子。", "写雨停后屋里亮起灯。",
                                   profile_name="fixture")
            result = await service.run(run_id)

            assert result["status"] == "completed"
            assert observed["reference"] == chosen
            first_body = endpoint.requests[0]["body"]
            system_text = next(message["content"] for message in first_body["messages"]
                               if message.get("role") == "system")
            user_text = next(message["content"] for message in first_body["messages"]
                             if message.get("role") == "user")
            user_context = json.loads(user_text)
            assert system_text == WRITER_PROMPT
            assert style_marker not in system_text + user_text
            assert all(item["text"] not in system_text + user_text for item in resource_map.values())
            assert "CPM" not in system_text and "CHECK 1" not in system_text
            assert "CHECK 2" not in system_text and "CHECK 3" not in system_text and "CHECK 4" not in system_text
            assert "PASS/FAIL" not in system_text and "Repair Loop" not in system_text
            assert set(user_context["available_writing_resources"]) == set(resource_map)
            assert style_marker not in json.dumps(result["turns"], ensure_ascii=False)
            assert endpoint.callback_errors == []

    asyncio.run(scenario())
