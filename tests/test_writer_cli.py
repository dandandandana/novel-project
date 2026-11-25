from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
from threading import Thread

from novel_rag.cli import build_parser
from novel_rag.identity import GraphKey, StoryCoordinate
from novel_rag.model_config import ModelConfigStore
from novel_rag.service import load_story_sources
from writer_fixtures import make_library, put_document


class _LocalChatHandler(BaseHTTPRequestHandler):
    """依赖：标准库HTTP服务。输入：chat completion POST请求。输出：受控的非流式JSON正文。实现：记录请求并返回一个不含工具调用的最终turn。"""

    requests: list[tuple[str, dict]] = []

    def do_POST(self) -> None:
        """依赖：BaseHTTPRequestHandler与测试响应。输入：HTTP POST。输出：记录请求并发送标准chat JSON。实现：读取JSON体后以application/json返回唯一终稿。"""

        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests.append((self.path, payload))
        response = {
            "id": "chatcmpl-writer-cli-fixture",
            "object": "chat.completion",
            "created": 1,
            "model": "fixture-writer",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "一段由本地模型生成的独立草稿。",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 8, "completion_tokens": 9, "total_tokens": 17},
        }
        body = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """依赖：BaseHTTPRequestHandler。输入：服务器访问日志参数。输出：无。实现：保持受控HTTP fixture输出安静。"""

        del format, args


def test_write_and_workspace_commands_are_registered_with_defaults() -> None:
    """依赖：CLI解析器。输入：write/workspace命令行样例。输出：解析出的默认值和可选坐标。实现：验证新入口参数不触发服务。"""

    parser = build_parser()
    write_args = parser.parse_args(
        ["write", "--story", "demo", "--outline-file", "outline.md"]
    )
    assert write_args.command == "write"
    assert write_args.timeline == "main"
    assert write_args.outline_file == Path("outline.md")
    assert write_args.request == ""
    assert write_args.task_kind == "write"
    assert write_args.profile is None
    assert write_args.workspace is None
    assert write_args.base_document is None
    assert (write_args.volume, write_args.chapter, write_args.scene) == (None, None, None)

    full_write_args = parser.parse_args(
        [
            "write", "--story", "demo", "--timeline", "branch",
            "--outline-file", "outline.md", "--request", "保留结尾",
            "--task-kind", "revise", "--profile", "local",
            "--workspace", "work", "--base-document", "history-1",
            "--volume", "2", "--chapter", "3", "--scene", "4",
        ]
    )
    assert full_write_args.timeline == "branch"
    assert full_write_args.task_kind == "revise"
    assert full_write_args.workspace == Path("work")
    assert (full_write_args.volume, full_write_args.chapter, full_write_args.scene) == (2, 3, 4)

    workspace_args = parser.parse_args(["workspace"])
    assert workspace_args.command == "workspace"
    assert workspace_args.port == 8765
    assert workspace_args.workspace is None


def test_cli_import_keeps_optional_web_runtime_lazy() -> None:
    """依赖：独立Python子进程。输入：novel_rag.cli导入表达式。输出：基础CLI导入成功且未加载web extra。实现：检查uvicorn与FastAPI仍延迟加载。"""

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import novel_rag.cli; "
            "assert 'uvicorn' not in sys.modules; "
            "assert 'fastapi' not in sys.modules",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_write_cli_runs_against_local_chat_and_preserves_history(tmp_path: Path) -> None:
    """依赖：真实CLI子进程、writer_fixtures、ModelConfigStore与本地HTTP模型。输入：临时本书、模型profile和原始大纲。输出：可恢复的终稿Ref/文件且正式History字节不变。实现：非流式chat JSON驱动一次真实RunService运行并检查无stage调用。"""

    library_root = make_library(tmp_path)
    put_document(
        library_root,
        "canon-setting-1",
        "主角在雨夜收到一封没有署名的信。",
        category="canon",
    )
    history_path = put_document(
        library_root,
        "history-source-1",
        "此前正式章节的原始正文。",
        category="history",
        volume=1,
        chapter=1,
        scene=1,
    )
    history_before = history_path.read_bytes()
    outline_path = tmp_path / "outline.md"
    outline_text = "第二章：主角拆开信封，发现寄件人留下的时间线索。"
    outline_path.write_text(outline_text, encoding="utf-8")
    workspace_root = tmp_path / "writer-workspace"
    model_config_path = tmp_path / "model-api.json"

    _LocalChatHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalChatHandler)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        config = ModelConfigStore(model_config_path)
        config.set_profile(
            "fixture",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            model="fixture-writer",
            mode="chat",
            api_key="writer-cli-secret",
            no_auth=False,
            timeout=10,
            retries=0,
        )
        config.set_active("fixture")

        command = [
            sys.executable,
            "-m",
            "novel_rag.cli",
            "--library",
            str(library_root),
            "--model-config",
            str(model_config_path),
            "write",
            "--story",
            "demo",
            "--outline-file",
            str(outline_path),
            "--base-document",
            "history-source-1",
            "--volume",
            "1",
            "--chapter",
            "2",
            "--scene",
            "1",
            "--workspace",
            str(workspace_root),
        ]
        result = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
        )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "writer-cli-secret" not in result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["status"] == "completed"
    assert output["draft_text"] == "一段由本地模型生成的独立草稿。"
    assert output["draft_ref"]["kind"] == "draft"
    assert output["draft_ref"]["content_hash"]

    assert len(_LocalChatHandler.requests) == 1
    request_path, request_body = _LocalChatHandler.requests[0]
    assert request_path == "/v1/chat/completions"
    assert request_body["stream"] is True
    assert "stage" not in request_body
    assert all("stage" not in message for message in request_body.get("messages", []))

    run_path = (
        workspace_root
        / "demo"
        / "main"
        / "runs"
        / output["run_id"]
        / "run.json"
    )
    run_snapshot = json.loads(run_path.read_text(encoding="utf-8"))
    expected_base_ref = load_story_sources(
        library_root, GraphKey("demo", "main")
    ).source_refs["history-source-1"].as_dict()
    assert run_snapshot["binding"]["base_ref"] == expected_base_ref
    assert run_snapshot["binding"]["target_coordinate"] == StoryCoordinate(1, 2, 1).__dict__
    assert run_snapshot["request_snapshot"]["outline"] == outline_text

    draft_files = list((run_path.parent / "drafts").glob("*.txt"))
    assert draft_files
    assert any(path.read_text(encoding="utf-8") == output["draft_text"] for path in draft_files)
    assert history_path.read_bytes() == history_before
