from __future__ import annotations

from copy import deepcopy
import json
from http.client import BadStatusLine, IncompleteRead
from pathlib import Path
import queue
import subprocess
import sys
import threading

import httpx
import pytest

from native_http_fixture import workspace_server
from novel_rag.harness import BackendClient, BackendError
from novel_rag.identity import GraphKey
from novel_rag.mutations.types import MutationLockError
from novel_rag.web.app import create_app
from writer_fixtures import make_library, put_document
from test_candidate_navigation import navigation_runtime


def test_candidate_navigation_crosses_http_and_stdio_restart(navigation_runtime, tmp_path: Path) -> None:
    """依赖：真实Uvicorn/原MCP子进程/共享候选夹具。输入：HTTP首批和返回cursor。输出：stdio继续、重启重放、原JSON同源与改源拒绝。实现：仅转发原入口，两个adapter共用同后端Store，不改归档源。"""
    root, _, run_id, ids = navigation_runtime
    app = create_app(root, tmp_path / "workspace", tmp_path / "no-model.json")
    with workspace_server(app) as backend:
        with httpx.Client(base_url=backend, timeout=15) as client:
            headers = {"x-workspace-token": client.get("/api/v1/harness/bootstrap").json()["token"]}
            response = client.post(f"/api/v1/runs/{run_id}/harness-tool", headers=headers,
                json={"name": "recall", "arguments": {"query": "无名物件"}, "delivery": "full"})
            assert response.status_code == 200
            first = response.json()
            assert len(first["hooks"]) == 64
            arguments = first["candidate_search"]["next_arguments"]
            found = set()
            for restart in range(2):
                replayed = set()
                with _McpProcess(backend, run_id) as mcp:
                    mcp.request(1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                        "clientInfo": {"name": "candidate-navigation-regression", "version": "1"}})
                    mcp.notify("notifications/initialized")
                    assert len(mcp.request(2, "tools/list")["result"]["tools"]) == 5
                    current_arguments, request_id = arguments, 3
                    while current_arguments is not None:
                        result = mcp.request(request_id, "tools/call", {"name": "recall", "arguments": current_arguments})["result"]
                        packet = result["structuredContent"]
                        assert json.loads(result["content"][0]["text"]) == packet
                        assert packet.get("ok") is not False, packet
                        assert packet["candidate_search"]["visited_count"] == 70
                        assert packet["candidate_search"]["next_arguments"] is None
                        for unit in packet["units"]:
                            replayed.update(item["record"]["id"] for item in unit.get("records", []) if item["kind"] == "hooks")
                        current_arguments = packet["next_arguments"]
                        request_id += 1
                        assert request_id < 20
                assert len(replayed) == 6
                if restart:
                    assert replayed == found
                found = replayed
            assert found.isdisjoint(row["id"] for row in first["hooks"])
            assert found | {row["id"] for row in first["hooks"]} == set(ids.values())
            source = app.state.service.memory.corpus(app.state.service.store.load(run_id)).read("background")[0].path
            source.write_bytes(source.read_bytes() + b"\n# isolated backend edit\n")
            rejected = client.post(f"/api/v1/runs/{run_id}/harness-tool", headers=headers,
                json={"name": "recall", "arguments": arguments}).json()
            assert rejected["ok"] is False and rejected["error"]["code"] == "snapshot_stale"


class _McpProcess:
    """固定run的真实CLI stdio MCP子进程。"""

    def __init__(self, backend: str, run_id: str):
        """依赖：CLI harness mcp入口、queue与stdout reader线程。输入：随机loopback后端和固定run ID。输出：已启动的交互式子进程。实现：二进制stdin/stdout保留UTF-8边界并单独收集stderr。"""

        project_root = Path(__file__).resolve().parents[1]
        self.process = subprocess.Popen(
            [sys.executable, "-m", "novel_rag.cli", "harness", "mcp", "--backend", backend, "--run-id", run_id],
            cwd=project_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.lines: queue.Queue[bytes | None] = queue.Queue()
        self.reader = threading.Thread(target=self._read_stdout, name="mcp-test-stdout", daemon=True)
        self.reader.start()
        self.closed = False

    def _read_stdout(self) -> None:
        """依赖：Popen stdout管道与线程安全Queue。输入：无。输出：完整UTF-8行或EOF标记。实现：只读取字节行，不解码或吞并协议边界。"""

        assert self.process.stdout is not None
        for line in iter(self.process.stdout.readline, b""):
            self.lines.put(line)
        self.lines.put(None)

    def send(self, value: dict) -> None:
        """依赖：子进程stdin与JSON encoder。输入：JSON-RPC对象。输出：一条UTF-8换行消息。实现：保留非ASCII文本并立即flush供真实stdio读取。"""

        if self.closed or self.process.stdin is None:
            raise AssertionError("MCP stdin is closed")
        self.process.stdin.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
        self.process.stdin.flush()

    def send_raw(self, value: bytes) -> None:
        """依赖：子进程stdin管道。输入：原始协议字节。输出：一条flush后的输入行。实现：用于验证坏JSON边界，不经JSON序列化器改写。"""

        if self.closed or self.process.stdin is None:
            raise AssertionError("MCP stdin is closed")
        self.process.stdin.write(value + b"\n")
        self.process.stdin.flush()

    def receive(self, timeout: float = 8.0) -> dict:
        """依赖：stdout reader与JSON-RPC行协议。输入：有限等待秒数。输出：解码后的对象消息。实现：每行必须是UTF-8完整JSON对象，非协议stdout立即失败。"""

        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty as exc:
            raise AssertionError("MCP subprocess did not produce a response") from exc
        if line is None:
            raise AssertionError("MCP subprocess closed stdout before replying")
        if not line.endswith(b"\n"):
            raise AssertionError(f"MCP stdout message is not newline-delimited: {line!r}")
        try:
            result = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise AssertionError(f"MCP stdout contained a non-JSON line: {line!r}") from exc
        assert isinstance(result, dict)
        return result

    def request(self, request_id: int, method: str, params: dict | None = None) -> dict:
        """依赖：send/receive。输入：请求ID、方法与参数。输出：匹配请求ID的JSON-RPC响应。实现：逐请求写一行并验证响应关联。"""

        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        response = self.receive()
        assert response.get("jsonrpc") == "2.0"
        assert response.get("id") == request_id
        return response

    def notify(self, method: str, params: dict | None = None) -> None:
        """依赖：send。输入：通知方法与参数。输出：无响应请求已写入。实现：省略JSON-RPC id，供生命周期通知使用。"""

        self.send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self, *, check: bool = True) -> None:
        """依赖：Popen stdin/stdout/stderr和有限进程回收。输入：是否检查正常退出。输出：已关闭adapter。实现：以stdin EOF结束MCP进程，核对退出码并拒绝意外stdout行。"""

        if self.closed:
            return
        self.closed = True
        if self.process.stdin is not None:
            self.process.stdin.close()
        try:
            exit_code = self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
            raise AssertionError("MCP adapter did not exit after stdin EOF")
        self.reader.join(timeout=3)
        if self.reader.is_alive():
            raise AssertionError("MCP stdout reader did not stop")
        stderr = self.process.stderr.read() if self.process.stderr is not None else b""
        trailing: list[bytes] = []
        while True:
            try:
                line = self.lines.get_nowait()
            except queue.Empty:
                break
            if line is not None:
                trailing.append(line)
        if check and exit_code != 0:
            raise AssertionError(f"MCP adapter exited {exit_code}: {stderr.decode('utf-8', errors='replace')}")
        if check and trailing:
            raise AssertionError(f"MCP adapter wrote unexpected stdout lines: {trailing!r}")

    def __enter__(self) -> _McpProcess:
        """依赖：已启动Popen。输入：with进入。输出：此交互式客户端。实现：不改变进程状态。"""

        return self

    def __exit__(self, exc_type, _exc, _traceback) -> None:
        """依赖：close。输入：with退出状态。输出：子进程回收完成。实现：始终发送EOF，测试主体成功时再检查退出与尾部输出。"""

        self.close(check=exc_type is None)


def _run_harness_cli(backend: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    """依赖：novel_rag.cli harness命令。输入：后端地址和实际CLI参数。输出：UTF-8进程结果。实现：在仓库根启动有界子进程并捕获stdout/stderr。"""

    project_root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [sys.executable, "-m", "novel_rag.cli", "harness", *arguments, "--backend", backend],
        cwd=project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def test_stdio_mcp_protocol_roundtrip_survives_eof_and_adapter_restart(tmp_path: Path) -> None:
    """验证真实TCP后端与CLI stdio MCP完整往返、协议错误和重启幂等。依赖：workspace_server、httpx、McpStdioAdapter CLI。输入：一次harness run、原生MCP lifecycle/tool/resource请求及两次adapter进程。输出：五工具/上下文可读，坏请求分层报错，稳定ID重放不增版本且EOF保留prepared。实现：逐行驱动真实子进程，跨重启用相同save/remember operation_id和实际DraftRef对比权威HTTP快照。"""

    root = make_library(tmp_path)
    put_document(root, "chapter-one", "山门的灯火照亮雨夜。")
    workspace = tmp_path / "workspace"
    app = create_app(root, workspace, tmp_path / "missing-model-config.json")

    with workspace_server(app) as backend:
        with httpx.Client(base_url=backend, timeout=4) as client:
            bootstrap = client.get("/api/v1/harness/bootstrap").json()
            headers = {"x-workspace-token": bootstrap["token"]}
            created = client.post(
                "/api/v1/runs",
                headers=headers,
                json={"driver": "harness", "story_id": "demo", "timeline_id": "main",
                      "outline": "作者原始路线：守灯人离开山门。", "request": "写出离开的瞬间。"},
            )
            assert created.status_code == 200, created.text
            run_id = created.json()["run_id"]

            with _McpProcess(backend, run_id) as mcp:
                initialized = mcp.request(1, "initialize", {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "codex-harness-regression", "version": "1"},
                })
                assert initialized["result"]["protocolVersion"] == "2025-11-25"
                assert set(initialized["result"]["capabilities"]) == {"tools", "resources"}
                mcp.notify("notifications/initialized")
                assert mcp.request(2, "ping")["result"] == {}

                listed_tools = mcp.request(3, "tools/list")["result"]["tools"]
                assert {tool["name"] for tool in listed_tools} == {
                    "recall", "read_document", "read_writing_reference", "save_draft", "remember",
                }
                save_schema = next(tool["inputSchema"] for tool in listed_tools if tool["name"] == "save_draft")
                assert "operation_id" in save_schema["required"]
                resources = mcp.request(4, "resources/list")["result"]["resources"]
                context_uri = f"novel://runs/{run_id}/context"
                assert [resource["uri"] for resource in resources] == [context_uri]
                context = mcp.request(5, "resources/read", {"uri": context_uri})["result"]["contents"][0]
                initial_context = json.loads(context["text"])
                assert initial_context["status"] == "prepared"
                assert "作者原始路线：守灯人离开山门。" in json.dumps(initial_context["messages"], ensure_ascii=False)
                native_tools = client.get(f"/api/v1/runs/{run_id}/harness-tools", headers=headers).json()["tools"]
                for tool in listed_tools:
                    native = next(row for row in native_tools if row["name"] == tool["name"])
                    schema = deepcopy(tool["inputSchema"])
                    if tool["name"] in {"save_draft", "remember"}:
                        schema["properties"].pop("operation_id")
                        schema["required"].remove("operation_id")
                    assert schema == native["parameters"]
                    assert tool["description"] == native["description"]

                read_result = mcp.request(6, "tools/call", {
                    "name": "read_document", "arguments": {"document_id": "chapter-one"},
                })["result"]
                assert read_result["isError"] is False
                assert "山门的灯火照亮雨夜。" in read_result["structuredContent"]["text"]

                unknown_tool = mcp.request(7, "tools/call", {"name": "model_owned_filesystem", "arguments": {}})
                assert unknown_tool["error"]["code"] == -32602
                business_error = mcp.request(8, "tools/call", {
                    "name": "read_document", "arguments": {"document_id": "outside-current-story"},
                })["result"]
                assert business_error["isError"] is True
                assert business_error["structuredContent"]["ok"] is False

                save_arguments = {
                    "text": "守灯人放下钥匙，走入雨中。",
                    "expected_revision": 0,
                    "operation_id": "stdio-save-stable-01",
                }
                saved = mcp.request(9, "tools/call", {
                    "name": "save_draft", "arguments": save_arguments,
                })["result"]["structuredContent"]
                assert saved["kind"] == "draft"
                remember_arguments = {
                    "draft_ref": saved,
                    "expected_memory_revision": 0,
                    "update": {
                        "event_lines": [{
                            "op": "create", "local_ref": "departure",
                            "record": {"record_kind": "event_line", "payload": {"title": "守灯人离开"}},
                        }],
                        "state_changes": [{
                            "op": "set", "local_ref": "key-custody",
                            "entry": {"domain": "World", "kind": "custody",
                                      "value": "钥匙留在门房。", "lifetime": "carry"},
                        }],
                    },
                    "operation_id": "stdio-memory-stable-01",
                }
                remembered = mcp.request(10, "tools/call", {
                    "name": "remember", "arguments": remember_arguments,
                })["result"]["structuredContent"]
                assert remembered["memory_revision"] == 1

                mcp.send_raw(b"{not-json}")
                parse_error = mcp.receive()
                assert parse_error["id"] is None
                assert parse_error["error"]["code"] == -32700
                assert mcp.request(11, "ping")["result"] == {}

            after_eof = client.get(f"/api/v1/runs/{run_id}", headers=headers).json()
            assert after_eof["status"] == "prepared"
            assert after_eof["draft_revision"] == 1
            assert after_eof["memory_revision"] == 1

            with _McpProcess(backend, run_id) as restarted:
                restarted.request(101, "initialize", {
                    "protocolVersion": "2025-11-25", "capabilities": {},
                    "clientInfo": {"name": "codex-harness-regression-restart", "version": "1"},
                })
                restarted.notify("notifications/initialized")
                restarted_context = restarted.request(102, "resources/read", {
                    "uri": f"novel://runs/{run_id}/context",
                })["result"]["contents"][0]
                current_context = json.loads(restarted_context["text"])
                assert current_context["draft_revision"] == 1
                assert current_context["memory_revision"] == 1
                assert current_context["draft_ref"] == saved

                recovered_save = restarted.request(103, "tools/call", {
                    "name": "save_draft", "arguments": save_arguments,
                })["result"]["structuredContent"]
                recovered_memory = restarted.request(104, "tools/call", {
                    "name": "remember", "arguments": remember_arguments,
                })["result"]["structuredContent"]
                assert recovered_save == saved
                assert recovered_memory == remembered

            final_snapshot = client.get(f"/api/v1/runs/{run_id}", headers=headers).json()
            assert final_snapshot["status"] == "prepared"
            assert final_snapshot["draft_revision"] == 1
            assert final_snapshot["memory_revision"] == 1
            assert len(final_snapshot["drafts"]) == 1
            assert len(final_snapshot["memory_batches"]) == 1
            assert set(final_snapshot["tool_commits"]) == {
                "harness:save_draft:stdio-save-stable-01",
                "harness:remember:stdio-memory-stable-01",
            }


def test_stdio_executes_delivered_memory_examples_with_host_ids_and_receipts(tmp_path: Path) -> None:
    """依赖：真实HTTP后端/CLI stdio/同源工具例。输入：tools/list实际交付的三例。输出：新建、更新、解除及原ID来源回读。实现：每次保存正文，用回执CAS/Ref替换占位，不另抄记忆成功参数。"""
    app = create_app(make_library(tmp_path), tmp_path / "workspace", tmp_path / "missing-model-config.json")
    with workspace_server(app) as backend, httpx.Client(base_url=backend, timeout=4) as client:
        bootstrap = client.get("/api/v1/harness/bootstrap").json()
        headers = {"x-workspace-token": bootstrap["token"]}
        created = client.post("/api/v1/runs", headers=headers, json={
            "driver": "harness", "story_id": "demo", "timeline_id": "main",
            "outline": "山门关闭、开放，最后拆除。", "request": "记录实际状态变化。",
        })
        assert created.status_code == 200, created.text
        run_id = created.json()["run_id"]
        with _McpProcess(backend, run_id) as mcp:
            mcp.request(1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                "clientInfo": {"name": "memory-examples-regression", "version": "1"}})
            mcp.notify("notifications/initialized")
            tools = mcp.request(2, "tools/list")["result"]["tools"]
            schema = next(tool for tool in tools if tool["name"] == "remember")["inputSchema"]["properties"]["update"]
            context = json.loads(mcp.request(3, "resources/read", {
                "uri": f"novel://runs/{run_id}/context",
            })["result"]["contents"][0]["text"])
            native_tools = client.get(f"/api/v1/runs/{run_id}/harness-tools", headers=headers).json()["tools"]
            native = next(row for row in native_tools if row["name"] == "remember")
            assert schema == native["parameters"]["properties"]["update"]
            revision, memory_revision = context["draft_revision"], context["memory_revision"]
            text, entry_id = "", None
            bodies = ["守灯人关闭山门。", "交班时，山门重新开放。", "旧山门拆除，此门的开闭状态已结束。"]
            for ordinal, (example, body) in enumerate(zip(schema["examples"], bodies)):
                text += body
                saved = mcp.request(10 + ordinal * 10, "tools/call", {"name": "save_draft", "arguments": {
                    "text": text, "expected_revision": revision, "operation_id": f"example-save-{ordinal}",
                }})["result"]["structuredContent"]
                revision = saved["draft_revision"]
                update = deepcopy(example)
                change = update["state_changes"][0]
                if "entry_id" in change:
                    assert entry_id is not None
                    change["entry_id"] = entry_id
                response = mcp.request(11 + ordinal * 10, "tools/call", {"name": "remember", "arguments": {
                    "draft_ref": saved, "expected_memory_revision": memory_revision,
                    "update": update, "operation_id": f"example-remember-{ordinal}",
                }})["result"]
                assert response["isError"] is False, response
                receipt = response["structuredContent"]
                assert receipt["memory_revision"] == memory_revision + 1
                memory_revision = receipt["memory_revision"]
                if entry_id is None:
                    entry_id = receipt["local_ref_to_stable_id"][change["local_ref"]]
                recalled = mcp.request(12 + ordinal * 10, "tools/call", {"name": "recall", "arguments": {
                    "focus": [entry_id],
                }})["result"]["structuredContent"]
                assert recalled["delivery_complete"] is True
                rows = [row for unit in recalled["units"] for row in unit.get("records", [])]
                if change["op"] == "set":
                    row = next(row["record"] for row in rows if row["kind"] == "entries" and row["record"]["entry_id"] == entry_id)
                    assert row["value"] == change["entry"]["value"]
                    assert row["source_refs"] == [saved]
                else:
                    assert not any(row["kind"] == "entries" and row["record"]["entry_id"] == entry_id for row in rows)
                    assert any(row["kind"] == "ended_entries" and row["record"]["entry_id"] == entry_id and
                               row["record"]["effect"] == "cleared" for row in rows)
        snapshot = client.get(f"/api/v1/runs/{run_id}", headers=headers).json()
        assert snapshot["memory_revision"] == 3 and len(snapshot["memory_batches"]) == 3


def test_harness_cli_prepare_context_status_and_finish_use_same_run(tmp_path: Path) -> None:
    """验证harness prepare/context/status/finish CLI命令实际读写同一run。依赖：workspace_server、CLI子进程和token保护的HTTP保存入口。输入：损坏模型配置、原纲文件、request_id及一个保存检查点。输出：重复prepare恢复同run，context/status读取现状，finish完成该run。实现：逐条启动真实CLI进程并以HTTP创建唯一正文checkpoint。"""

    root = make_library(tmp_path)
    workspace = tmp_path / "workspace"
    config_path = tmp_path / "broken-model-config.json"
    config_path.write_text("{invalid model configuration", encoding="utf-8")
    outline_path = tmp_path / "outline.md"
    outline_path.write_text("作者原始路线：守灯人离开山门。", encoding="utf-8")
    app = create_app(root, workspace, config_path)

    with workspace_server(app) as backend:
        prepare_args = (
            "prepare", "--story", "demo", "--outline-file", str(outline_path),
            "--request-id", "cli-request-stable", "--request", "写出离开的瞬间。",
        )
        prepared_process = _run_harness_cli(backend, *prepare_args)
        assert prepared_process.returncode == 0, prepared_process.stderr or prepared_process.stdout
        prepared = json.loads(prepared_process.stdout)
        run_id = prepared["run_id"]
        assert prepared["request_id"] == "cli-request-stable"
        assert prepared["context"]["status"] == "prepared"
        assert prepared["backend_identity"]["workspace_root"] == str(workspace.resolve())
        assert prepared["workspace_url"].endswith("?run=" + run_id)

        recovered_process = _run_harness_cli(backend, *prepare_args)
        assert recovered_process.returncode == 0, recovered_process.stderr or recovered_process.stdout
        recovered = json.loads(recovered_process.stdout)
        assert recovered["run_id"] == run_id
        assert len(list((workspace / "demo" / "main" / "runs").glob("*/run.json"))) == 1

        context_process = _run_harness_cli(backend, "context", "--run-id", run_id)
        assert context_process.returncode == 0, context_process.stderr or context_process.stdout
        context = json.loads(context_process.stdout)
        assert context["run_id"] == run_id
        assert context["status"] == "prepared"
        assert "作者原始路线：守灯人离开山门。" in json.dumps(context["messages"], ensure_ascii=False)

        status_process = _run_harness_cli(backend, "status", "--run-id", run_id)
        assert status_process.returncode == 0, status_process.stderr or status_process.stdout
        assert json.loads(status_process.stdout)["status"] == "prepared"

        with httpx.Client(base_url=backend, timeout=3) as client:
            token = client.get("/api/v1/harness/bootstrap").json()["token"]
            saved = client.post(
                f"/api/v1/runs/{run_id}/harness-tool",
                headers={"x-workspace-token": token},
                json={
                    "name": "save_draft",
                    "operation_id": "cli-finish-checkpoint",
                    "arguments": {"text": "守灯人放下钥匙，走进雨里。", "expected_revision": 0},
                },
            )
            assert saved.status_code == 200, saved.text

        finish_process = _run_harness_cli(backend, "finish", "--run-id", run_id, "--status", "completed")
        assert finish_process.returncode == 0, finish_process.stderr or finish_process.stdout
        assert json.loads(finish_process.stdout)["status"] == "completed"
        final_status = _run_harness_cli(backend, "status", "--run-id", run_id)
        assert final_status.returncode == 0, final_status.stderr or final_status.stdout
        assert json.loads(final_status.stdout)["status"] == "completed"


def test_harness_cli_accepts_large_context_and_preserves_bad_input_identity(tmp_path: Path) -> None:
    """依赖：真实workspace_server/CLI子进程。输入：20000字原纲与非法JSON坐标。输出：完整原纲及可恢复run/request_id，坏输入不新增run。实现：无默认预算的准备上下文与输入错误分别经JSON和权威目录核对。"""

    root = make_library(tmp_path)
    workspace = tmp_path / "workspace"
    app = create_app(root, workspace, tmp_path / "missing-model-config.json")
    large_outline = tmp_path / "large-outline.md"
    large_outline.write_text("甲" * 20_000, encoding="utf-8")
    ordinary_outline = tmp_path / "ordinary-outline.md"
    ordinary_outline.write_text("正常路线。", encoding="utf-8")

    with workspace_server(app) as backend:
        large_process = _run_harness_cli(
            backend,
            "prepare", "--story", "demo", "--outline-file", str(large_outline),
            "--request-id", "cli-large-context-request",
        )
        assert large_process.returncode == 0, large_process.stderr or large_process.stdout
        large = json.loads(large_process.stdout)
        assert large["run_id"]
        assert large["request_id"] == "cli-large-context-request"
        assert json.loads(large["context"]["messages"][1]["content"])["outline_original"] == "甲" * 20_000

        bad_input_process = _run_harness_cli(
            backend,
            "prepare", "--story", "demo", "--outline-file", str(ordinary_outline),
            "--request-id", "cli-bad-coordinate-request", "--target-coordinate", "{not-json",
        )
        assert bad_input_process.returncode != 0
        bad_input = json.loads(bad_input_process.stdout)
        assert bad_input["run_id"] is None
        assert bad_input["request_id"] == "cli-bad-coordinate-request"
        assert bad_input["error"]["code"] == "source_invalid"
        assert len(list((workspace / "demo" / "main" / "runs").glob("*/run.json"))) == 1
        prepared = app.state.service.store.load(large["run_id"])
        assert prepared["status"] == "prepared"
        assert prepared["request_id"] == "cli-large-context-request"


def test_second_workspace_writer_is_refused_without_recovering_live_run(tmp_path: Path) -> None:
    """验证真实workspace生命周期锁阻止第二个CLI后端启动且不恢复活动run。依赖：workspace_server的实际ASGI lifespan、FileMutationLock和workspace CLI。输入：首后端持锁、标记running的同workspace run及端口0第二后端进程。输出：第二写者限时失败、原run仍running、首后端退出后锁释放。实现：先真实启动TCP后端并核对run快照，再用独立Python进程尝试同目录服务。"""

    root = make_library(tmp_path)
    workspace = tmp_path / "workspace"
    config_path = tmp_path / "model-config.json"
    app = create_app(root, workspace, config_path)
    project_root = Path(__file__).resolve().parents[1]

    with workspace_server(app):
        service = app.state.service
        run_id = service.prepare(
            GraphKey("demo", "main"),
            "write", "活动run保留状态", "第二写者不得启动恢复。",
        )
        service.store.set_status(run_id, "running")
        before = service.store.load(run_id)
        assert before["status"] == "running"

        try:
            second = subprocess.run(
                [
                    sys.executable, "-m", "novel_rag.cli",
                    "--library", str(root), "--model-config", str(config_path),
                    "workspace", "--workspace", str(workspace), "--port", "0",
                ],
                cwd=project_root,
                capture_output=True,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            pytest.fail(f"second workspace writer did not refuse startup in time: {exc}")

        assert second.returncode != 0
        output = ((second.stdout or b"") + (second.stderr or b"")).decode("utf-8", errors="replace")
        assert "lock" in output.lower() or "锁" in output
        after = service.store.load(run_id)
        assert after["status"] == "running"
        assert after["events"] == before["events"]

    assert not (workspace / ".writer.lock").exists()


@pytest.mark.parametrize("failure_kind", ["bad_status_line", "incomplete_read"])
def test_backend_client_does_not_retry_ambiguous_http_framing_failures(failure_kind: str, monkeypatch) -> None:
    """验证HTTP framing异常在写请求后映射为未知结果且不会自动重试。依赖：BackendClient与stdlib HTTPException。输入：BadStatusLine或IncompleteRead及稳定operation_id。输出：backend_protocol/effects_known=false且恰好一次open。实现：替换唯一opener.open捕捉实际请求并抛出对应传输异常。"""

    error = BadStatusLine("invalid status") if failure_kind == "bad_status_line" else IncompleteRead(b"partial", 8)
    client = BackendClient("http://127.0.0.1:8765")
    attempted: list[dict] = []

    def raise_framing_error(request, *, timeout: float) -> None:
        """依赖：urllib Request与请求JSON。输入：客户端实际请求和超时。输出：无，抛出固定stdlib HTTP framing错误。实现：记录单次操作ID后模拟响应边界损坏。"""

        attempted.append(json.loads(request.data.decode("utf-8")))
        raise error

    monkeypatch.setattr(client._opener, "open", raise_framing_error)
    with pytest.raises(BackendError) as raised:
        client._send(
            "/api/v1/runs/run-stable/harness-tool",
            {"name": "remember", "arguments": {"update": {}}, "operation_id": "memory-op-stable"},
        )

    assert raised.value.error["code"] == "backend_protocol"
    assert raised.value.error["effects_known"] is False
    assert attempted == [{"name": "remember", "arguments": {"update": {}}, "operation_id": "memory-op-stable"}]


def test_harness_http_routes_use_real_workspace_and_preserve_auth_boundary(tmp_path: Path) -> None:
    """验证harness bootstrap、run、五工具、记忆和finish走真实TCP后端。依赖：workspace_server、FastAPI app、httpx与Writer fixtures。输入：含单篇原文及损坏模型配置的本地工作区。输出：token保护下的工具回执/修订和已结束快照，History字节不变。实现：不调用ASGI伪客户端，完整请求随机loopback服务并验证应用生命周期独占共享writer lock。"""

    root = make_library(tmp_path)
    source_path = put_document(root, "chapter-one", "铜钥匙由甲保管。")
    original_source = source_path.read_bytes()
    workspace = tmp_path / "workspace"
    config_path = tmp_path / "broken-model-config.json"
    config_path.write_text("{invalid profile configuration", encoding="utf-8")
    app = create_app(root, workspace, config_path)

    with workspace_server(app) as backend:
        with httpx.Client(base_url=backend, timeout=3) as client:
            bootstrap_response = client.get("/api/v1/harness/bootstrap")
            assert bootstrap_response.status_code == 200
            bootstrap = bootstrap_response.json()
            token = bootstrap["token"]
            assert bootstrap["library_root"] == str(root.resolve())
            assert bootstrap["workspace_root"] == str(workspace.resolve())

            headers = {"x-workspace-token": token}
            unauthorized = client.get("/api/v1/runs/missing/harness-context")
            cross_origin = client.get(
                "/api/v1/runs/missing/harness-context",
                headers={**headers, "origin": "https://outside.invalid"},
            )
            assert unauthorized.status_code == 403
            assert cross_origin.status_code == 403

            created = client.post(
                "/api/v1/runs",
                headers=headers,
                json={
                    "driver": "harness",
                    "story_id": "demo",
                    "timeline_id": "main",
                    "task_kind": "write",
                    "outline": "作者原始路线保留。",
                    "request": "写钥匙交接。",
                    "request_id": "http-harness-request",
                },
            )
            assert created.status_code == 200, created.text
            run_id = created.json()["run_id"]
            context_response = client.get(f"/api/v1/runs/{run_id}/harness-context", headers=headers)
            tools_response = client.get(f"/api/v1/runs/{run_id}/harness-tools", headers=headers)
            assert context_response.status_code == 200
            assert tools_response.status_code == 200
            context = context_response.json()
            definitions = tools_response.json()["tools"]
            assert context["status"] == "prepared"
            assert {item["name"] for item in definitions} == {
                "recall", "read_document", "read_writing_reference", "save_draft", "remember",
            }

            read_response = client.post(
                f"/api/v1/runs/{run_id}/harness-tool",
                headers=headers,
                json={"name": "read_document", "arguments": {"document_id": "chapter-one"}},
            )
            assert read_response.status_code == 200, read_response.text
            assert "铜钥匙由甲保管。" in read_response.json()["text"]

            save_arguments = {"text": "甲把铜钥匙放进口袋。", "expected_revision": 0}
            saved_response = client.post(
                f"/api/v1/runs/{run_id}/harness-tool",
                headers=headers,
                json={"name": "save_draft", "arguments": save_arguments, "operation_id": "http-save"},
            )
            assert saved_response.status_code == 200, saved_response.text
            actual_draft_ref = saved_response.json()
            assert actual_draft_ref["kind"] == "draft"

            remembered_response = client.post(
                f"/api/v1/runs/{run_id}/harness-tool",
                headers=headers,
                json={
                    "name": "remember",
                    "operation_id": "http-remember",
                    "arguments": {
                        "draft_ref": actual_draft_ref,
                        "expected_memory_revision": 0,
                        "update": {
                            "event_lines": [{
                                "op": "create",
                                "local_ref": "handoff",
                                "record": {"record_kind": "event_line", "payload": {"title": "钥匙交接"}},
                            }],
                            "state_changes": [{
                                "op": "set",
                                "local_ref": "custody",
                                "entry": {
                                    "domain": "World",
                                    "kind": "custody",
                                    "value": "甲保管铜钥匙。",
                                    "lifetime": "carry",
                                },
                            }],
                        },
                    },
                },
            )
            assert remembered_response.status_code == 200, remembered_response.text
            assert remembered_response.json()["memory_revision"] == 1

            snapshot_response = client.get(f"/api/v1/runs/{run_id}", headers=headers)
            assert snapshot_response.status_code == 200
            snapshot = snapshot_response.json()
            assert snapshot["draft_ref"] == actual_draft_ref
            assert snapshot["draft_revision"] == 1
            assert snapshot["memory_revision"] == 1

            finished_response = client.post(
                f"/api/v1/runs/{run_id}/harness-finish",
                headers=headers,
                json={"status": "completed"},
            )
            assert finished_response.status_code == 200, finished_response.text
            assert finished_response.json()["status"] == "completed"
            assert source_path.read_bytes() == original_source
            assert config_path.read_text(encoding="utf-8") == "{invalid profile configuration"

            competing_lease = app.state.service.store.writer_lease()
            with pytest.raises(MutationLockError, match="锁已被占用"):
                competing_lease.acquire()

    assert not (workspace / ".writer.lock").exists()
