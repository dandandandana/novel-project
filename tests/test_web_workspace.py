from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
from collections.abc import Callable
import json
from pathlib import Path
import threading
from typing import AsyncIterator

import httpx

from native_http_fixture import NativeEndpoint
from novel_rag.documents import read_yaml_mapping
from novel_rag.generation.session import RunService
from novel_rag.generation.store import DraftStore
from novel_rag.memory.service import MemoryService
from novel_rag.model_config.store import ModelConfigStore
from novel_rag.web.app import create_app
from writer_fixtures import make_library

from test_writer_session import _text_response


@asynccontextmanager
async def _asgi_client(app) -> AsyncIterator[httpx.AsyncClient]:
    """依赖：实际 ASGI lifespan、HTTPX ASGITransport。
    输入：create_app 返回的 FastAPI 应用。
    输出：已启动/关闭 lifespan 的异步测试客户端。
    实现：显式进入 app.router.lifespan_context，再通过真实 ASGI middleware/路由发送请求。
    """
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            yield client


def _token_headers(token: str, **extra: str) -> dict[str, str]:
    """依赖：Web workspace token HTTP 契约。
    输入：bootstrap 返回 token 与可选附加 header。
    输出：供真实 API 请求使用的 header 映射。
    实现：把身份 token 放入专用 header 并合并测试边界字段。
    """
    return {"x-workspace-token": token, **extra}


def _text_callback(text: str) -> Callable[[dict], dict]:
    """依赖：独立原生响应编码器与 NativeEndpoint callback 契约。
    输入：预设公开终稿文本。
    输出：返回固定 Chat 响应脚本的具名 callback。
    实现：闭包只接收真实请求记录，不读取或改写 provider 请求。
    """
    def respond(_request_record: dict) -> dict:
        """依赖：原生 Chat SSE response helper。
        输入：endpoint 记录的请求对象。
        输出：完整终稿 SSE 脚本。
        实现：按测试预设文本返回 finish_reason stop 的独立响应。
        """
        return _text_response("chat", text)

    return respond


def _sse_records(body: str) -> tuple[list[int], list[tuple[str, dict]]]:
    """依赖：Web events 路由的 SSE id/event/data 行。
    输入：完整 event-stream 文本。
    输出：持久 seq 列表和解码后的事件记录。
    实现：逐空行分段解析，不改变服务器发出的事件内容。
    """
    ids: list[int] = []
    records: list[tuple[str, dict]] = []
    event_name, data_lines, event_id = "message", [], None
    for line in body.splitlines() + [""]:
        if not line:
            if data_lines:
                records.append((event_name, json.loads("\n".join(data_lines))))
            if event_id is not None:
                ids.append(int(event_id))
            event_name, data_lines, event_id = "message", [], None
        elif line.startswith("id:"):
            event_id = line[3:].strip()
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    return ids, records


async def _wait_for_status(client: httpx.AsyncClient, token: str, run_id: str, status: str) -> dict:
    """依赖：带 token 的 run snapshot 路由与异步轮询。
    输入：HTTPX客户端、workspace token、run ID 和目标终态。
    输出：首个匹配状态的安全快照，超时则断言失败。
    实现：以有界短间隔读取真实 Store 投影，不直接访问任务映射。
    """
    for _ in range(200):
        response = await client.get(f"/api/v1/runs/{run_id}", headers=_token_headers(token))
        assert response.status_code == 200, response.text
        snapshot = response.json()
        if snapshot["status"] == status:
            return snapshot
        await asyncio.sleep(0.01)
    raise AssertionError(f"run {run_id} did not reach {status}")


def test_bootstrap_run_sse_and_origin_host_boundaries_use_real_asgi_workspace(tmp_path: Path) -> None:
    """验证真实 Web bootstrap、run/SSE/snapshot 和 token/Host/Origin 边界。

    依赖：create_app、实际 ASGI lifespan、配置 Store、DraftStore 与本地模型 endpoint。
    输入：含私有 profile key 的临时工作区和一次受控原生 Chat 回复。
    输出：可轮询的完成稿、持久事件 seq/snapshot、bootstrap 不泄密及越界请求拒绝。
    实现：走真实 HTTPX ASGI middleware/路由/RunService，再核对磁盘快照和 JSON/SSE 响应。
    """
    async def scenario() -> None:
        """依赖：本地 FastAPI 应用 lifespan 与独立 localhost 模型 fixture。
        输入：本地书目、凭证化 profile、token 受限 run 和最终文本。
        输出：真实路由、SSE 游标恢复和来源边界的断言结果。
        实现：先取 bootstrap token，再通过 ASGI 客户端执行完整工作台调用序列。
        """
        root = make_library(tmp_path)
        workspace, config_path = tmp_path / "workspace", tmp_path / "model-config.json"
        secret = "web-workspace-secret-must-never-leave-server"
        final_text = "山门后的灯火把雨夜照出一道窄路。"
        with NativeEndpoint([{"mode": "chat", "callback": _text_callback(final_text)}]) as endpoint:
            assert endpoint.base_url is not None
            config = ModelConfigStore(config_path)
            config.set_profile("fixture", {
                "base_url": endpoint.base_url,
                "model": "web-fixture-model",
                "mode": "chat",
                "api_key": secret,
                "no_auth": False,
                "timeout": 4,
                "retries": 0,
            })
            app = create_app(root, workspace, config_path)
            assert isinstance(app.state.service.store, DraftStore)
            assert isinstance(app.state.service, RunService)
            assert isinstance(app.state.service.memory, MemoryService)

            async with _asgi_client(app) as client:
                bootstrap_response = await client.get("/api/v1/bootstrap")
                assert bootstrap_response.status_code == 200
                bootstrap = bootstrap_response.json()
                token = bootstrap["token"]
                assert bootstrap["stories"] == [{
                    "story_id": "demo", "title": "Demo", "timelines": [{
                        "story_id": "demo", "timeline_id": "main", "parent_timeline_id": None,
                        "divergence_at": None, "divergence_snapshot": None, "status": "active",
                    }],
                }, {
                    "story_id": "other", "title": "Other", "timelines": [{
                        "story_id": "other", "timeline_id": "main", "parent_timeline_id": None,
                        "divergence_at": None, "divergence_snapshot": None, "status": "active",
                    }],
                }]
                assert bootstrap["profiles"] == [{"name": "fixture", "model": "web-fixture-model", "mode": "chat"}]
                assert secret not in bootstrap_response.text

                assert (await client.get("/api/v1/runs/not-a-run")).status_code == 403
                invalid_origin = await client.get("/api/v1/runs/not-a-run", headers=_token_headers(
                    token, origin="https://attacker.example"))
                assert invalid_origin.status_code == 403
                invalid_host = await client.get("/api/v1/bootstrap", headers={"host": "attacker.example"})
                assert invalid_host.status_code == 403
                invalid_host_api = await client.get("/api/v1/runs/not-a-run", headers=_token_headers(
                    token, host="attacker.example"))
                assert invalid_host_api.status_code == 403
                bootstrap_origin = await client.get("/api/v1/bootstrap", headers={"origin": "https://attacker.example"})
                assert bootstrap_origin.status_code == 403
                localhost_same_origin = await client.get("/api/v1/bootstrap", headers={
                    "host": "localhost", "origin": "http://localhost",
                })
                assert localhost_same_origin.status_code == 200

                created_response = await client.post("/api/v1/runs", headers=_token_headers(token), json={
                    "story_id": "demo",
                    "timeline_id": "main",
                    "task_kind": "write",
                    "outline": "沿着山路找到旧门。",
                    "request": "写灯火照出雨夜中的窄路。",
                    "profile_name": "fixture",
                })
                assert created_response.status_code == 200, created_response.text
                created = created_response.json()
                run_id = created["run_id"]
                assert created["session_id"].startswith("session-")

                event_response = await client.get(f"/api/v1/runs/{run_id}/events", headers=_token_headers(token))
                assert event_response.status_code == 200
                seqs, event_records = _sse_records(event_response.text)
                assert seqs == sorted(set(seqs)) and seqs
                assert seqs == list(range(1, seqs[-1] + 1))
                assert [row["seq"] for name, row in event_records if name == "message"] == seqs
                assert any(name == "message" and row["type"] == "text_delta" and row["payload"].get("text")
                           for name, row in event_records)

                recovered_response = await client.get(f"/api/v1/runs/{run_id}/events?after=99999",
                                                      headers=_token_headers(token))
                assert recovered_response.status_code == 200
                recovered_ids, recovered_records = _sse_records(recovered_response.text)
                snapshot_record = next(row for name, row in recovered_records if name == "snapshot")
                assert snapshot_record["status"] == "completed"
                assert snapshot_record["draft_text"] == final_text
                assert recovered_ids == seqs

                snapshot_response = await client.get(f"/api/v1/runs/{run_id}", headers=_token_headers(token))
                assert snapshot_response.status_code == 200
                snapshot = snapshot_response.json()
                assert snapshot["status"] == "completed"
                assert snapshot["draft_text"] == final_text
                assert secret not in snapshot_response.text
                assert secret not in json.dumps(app.state.service.store.load(run_id), ensure_ascii=False)
                assert endpoint.requests[0]["path"] == "/v1/chat/completions"
                assert secret not in json.dumps(endpoint.requests[0]["body"], ensure_ascii=False)
                assert endpoint.callback_errors == []

    asyncio.run(scenario())


def test_feedback_cancel_and_adopt_selected_draft_with_draft_cas(tmp_path: Path) -> None:
    """验证 Web 草稿 CAS、选定父稿反馈、显式取消及所选修订正式采用。

    依赖：实际 create_app lifespan、RunService、DraftStore、AdoptionService 和本地 endpoint。
    输入：父 run、过期/有效编辑 CAS、父检查点 feedback、header-wait cancel 与采用坐标。
    输出：父前缀只拼一次的子稿、取消终态及落盘 History 精确采用正文。
    实现：所有操作经带 token 的真实 ASGI 路由，校验返回快照与规范 YAML 文件。
    """
    async def scenario() -> None:
        """依赖：三个确定原生响应、线程 barrier 与真实工作区 lifespan。
        输入：初稿、作者选择稿、续写后缀和一个可取消请求。
        输出：CAS 冲突、feedback 分支、cancelled 快照及 adopted History。
        实现：依次驱动 start/edit/feedback/cancel/adopt，最终回读来源文件确认提交字节。
        """
        root = make_library(tmp_path)
        workspace, config_path = tmp_path / "workspace", tmp_path / "model-config.json"
        secret, selected_coordinate = "web-private-profile-secret", {"volume": 1, "chapter": 1, "scene": 1}
        parent_text = "模型初稿：旧屋门口积着雨水。"
        author_text = "作者选定正文：雨水从门檐落下，门缝透出一线灯光。"
        suffix = "甲没有敲门，先把湿透的地图收进怀里。"
        release_gate, waiting_gate = threading.Event(), threading.Event()

        with NativeEndpoint([
            {"mode": "chat", "callback": _text_callback(parent_text)},
            {"mode": "chat", "callback": _text_callback(suffix)},
            {"mode": "chat", "json": {"choices": [{"message": {"role": "assistant", "content": "不得提交"},
                                                         "finish_reason": "stop"}]},
             "wait_headers": release_gate, "headers_waiting": waiting_gate},
        ], barrier_timeout=5) as endpoint:
            assert endpoint.base_url is not None
            config = ModelConfigStore(config_path)
            config.set_profile("fixture", {
                "base_url": endpoint.base_url, "model": "workspace-fixture", "mode": "chat",
                "api_key": secret, "no_auth": False, "timeout": 4, "retries": 0,
            })
            app = create_app(root, workspace, config_path)
            async with _asgi_client(app) as client:
                token = (await client.get("/api/v1/bootstrap")).json()["token"]
                headers = _token_headers(token)
                started_response = await client.post("/api/v1/runs", headers=headers, json={
                    "story_id": "demo", "timeline_id": "main", "task_kind": "write",
                    "outline": "沿山路到旧屋，原路线保持不变。", "request": "先写到门口。",
                    "target_coordinate": selected_coordinate, "profile_name": "fixture",
                })
                assert started_response.status_code == 200, started_response.text
                parent = started_response.json()
                parent_id, session_id = parent["run_id"], parent["session_id"]
                parent_snapshot = await _wait_for_status(client, token, parent_id, "completed")
                assert parent_snapshot["draft_text"] == parent_text
                assert parent_snapshot["draft_revision"] == 1

                conflict = await client.put(f"/api/v1/runs/{parent_id}/draft", headers=headers, json={
                    "expected_revision": 0, "text": "过期作者版本，不应被选中。",
                })
                assert conflict.status_code == 409
                assert conflict.json()["error"]["code"] == "revision_conflict"
                after_conflict = (await client.get(f"/api/v1/runs/{parent_id}", headers=headers)).json()
                assert after_conflict["draft_revision"] == 1
                assert after_conflict["draft_text"] == parent_text

                edited_response = await client.put(f"/api/v1/runs/{parent_id}/draft", headers=headers, json={
                    "expected_revision": 1, "text": author_text,
                })
                assert edited_response.status_code == 200, edited_response.text
                edited = edited_response.json()
                selected_ref = edited["draft_ref"]
                assert edited["draft_revision"] == 2
                assert edited["draft_text"] == author_text

                feedback_response = await client.post(f"/api/v1/sessions/{session_id}/feedback", headers=headers, json={
                    "base_run_id": parent_id, "task_kind": "write", "request": "从所选正文续写。",
                    "base_ref": selected_ref,
                    "selected_parent_checkpoint": selected_ref["checkpoint_id"],
                })
                assert feedback_response.status_code == 200, feedback_response.text
                child = feedback_response.json()
                assert child["session_id"] == session_id and child["run_id"] != parent_id
                child_snapshot = await _wait_for_status(client, token, child["run_id"], "completed")
                adopted_text = author_text + suffix
                assert child_snapshot["parent_run_id"] == parent_id
                assert child_snapshot["binding"]["output_mode"] == "append_suffix"
                assert child_snapshot["draft_text"] == adopted_text
                assert child_snapshot["draft_text"].count(author_text) == 1
                assert child_snapshot["request_snapshot"]["outline"] == "沿山路到旧屋，原路线保持不变。"

                cancel_start = await client.post("/api/v1/runs", headers=headers, json={
                    "story_id": "demo", "timeline_id": "main", "task_kind": "write",
                    "outline": "独立取消测试。", "request": "请求应被取消。", "profile_name": "fixture",
                })
                assert cancel_start.status_code == 200
                cancel_id = cancel_start.json()["run_id"]
                assert await asyncio.to_thread(waiting_gate.wait, 2)
                cancel_response = await client.post(f"/api/v1/runs/{cancel_id}/cancel", headers=headers)
                assert cancel_response.status_code == 200
                assert cancel_response.json()["cancel_requested"] is True
                release_gate.set()
                cancelled = await _wait_for_status(client, token, cancel_id, "cancelled")
                assert cancelled["draft_revision"] == 0
                assert cancelled["received_text"] == ""

                adoption_response = await client.post(f"/api/v1/runs/{child['run_id']}/adopt", headers=headers, json={
                    "draft_revision": child_snapshot["draft_revision"],
                    "expected_source_hash": None,
                    "coordinates": selected_coordinate,
                    "operation_id": "web-selected-draft-adoption-1",
                })
                assert adoption_response.status_code == 200, adoption_response.text
                adopted = adoption_response.json()
                assert adopted["adoption"]["adopted"] is True
                assert adopted["draft_text"] == adopted_text
                history_path = (root / "stories" / "demo" / "timelines" / "main" / "history"
                                / "volume-01" / "chapter-01" / "scene-01.yaml")
                history = read_yaml_mapping(history_path)
                assert history["metadata"]["document_type"] == "history"
                assert history["content"] == adopted_text
                assert secret not in adoption_response.text
                assert endpoint.callback_errors == []

        assert endpoint.thread is not None and not endpoint.thread.is_alive()
        assert all(not thread.is_alive() for thread in endpoint.request_threads)

    asyncio.run(scenario())
