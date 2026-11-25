"""热观察、作者浏览与原Store物理布局的实际边界回归。"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from novel_rag.composition import build_writer_service
from novel_rag.generation.context import active_recall_selection, context_binding
from novel_rag.generation.store import DraftStore, StoreConflict
from novel_rag.model_api import ToolCall
from novel_rag.identity import GraphKey
from novel_rag.web.app import create_app
from test_candidate_navigation import navigation_runtime
from writer_fixtures import make_library


@pytest.fixture
def observation_runtime(tmp_path: Path):
    """依赖：真实Writer及临时库。输入：pytest目录。输出：库/Writer/run。实现：无模型harness准备，所有产物只写隔离目录。"""
    root = make_library(tmp_path)
    writer = build_writer_service(root, tmp_path / "workspace", tmp_path / "no-model.json")
    run_id = writer.prepare(GraphKey("demo", "main"), "write", "保留来源。", "继续写作。")
    return root, writer, run_id


def test_unchanged_reconcile_and_live_http_do_no_recall_or_write(observation_runtime, tmp_path: Path, monkeypatch) -> None:
    """依赖：真实Memory/ASGI和writer计数。输入：未变化run。输出：暖读不写、live不recall且有同次seq。实现：先初始化效力，包装原保存，再走实际HTTP路由。"""
    root, writer, run_id = observation_runtime
    writer.memory.current_snapshot(run_id)
    writes = []
    original = writer.store.write

    def record_write(run):
        """依赖：原Store writer。输入：逻辑run。输出：原保存结果。实现：记录真实调用并委托，不伪造持久结果。"""
        writes.append(run["run_id"])
        return original(run)

    monkeypatch.setattr(writer.store, "write", record_write)
    writer.memory.current_snapshot(run_id)
    writer.memory.current_snapshot(run_id)
    assert writes == []
    app = create_app(root, writer.store.root, tmp_path / "no-model.json")

    def forbidden(*args, **kwargs):
        """依赖：pytest失败。输入：意外调用。输出：AssertionError。实现：live观察不得进入recall、冷load或写入。"""
        raise AssertionError("live观察触发冷读取/召回/写入")

    monkeypatch.setattr(app.state.service.memory, "recall", forbidden)
    monkeypatch.setattr(app.state.service.store, "load", forbidden)
    monkeypatch.setattr(app.state.service.store, "write", forbidden)

    async def scenario():
        """依赖：实际ASGI路由。输入：闭包app/run。输出：live形状及错误边界断言。实现：带原token访问，不启动模型。"""
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            headers = {"x-workspace-token": app.state.token}
            for _ in range(3):
                response = await client.get(f"/api/v1/runs/{run_id}?view=live&after=0", headers=headers)
                assert response.status_code == 200, response.text
                data = response.json()
                assert data["snapshot_view"] == "live" and data["event_seq"] == len(data["events"])
                assert not {"memory_state", "tool_results", "turns", "payload_storage"} & data.keys()
            bad = await client.get(f"/api/v1/runs/{run_id}?view=live&after=-1", headers=headers)
            assert bad.status_code == 400
    asyncio.run(scenario())


def test_store_payload_roundtrip_legacy_restart_hot_receive_and_corruption(observation_runtime, monkeypatch) -> None:
    """依赖：原Store/真实文件。输入：大工具行/turn及用户同名字典。输出：旧布局/新布局逻辑相等，热接收不加载，坏产物拒绝。实现：真实重启并改隔离payload字节，不重建回执。"""
    _, writer, run_id = observation_runtime
    store = writer.store
    run = store.load(run_id)
    original = {"text": "原文" * 8000, "$run_payload": "这是用户原文"}
    run["tool_results"] = [{"name": "read_document", "call_id": "one", "arguments": {"$run_payload": "literal"},
                            "result": original, "delivered_result": deepcopy(original)}]
    run["turns"] = [{"turn_id": "turn-large", "continuation": {"exact": "原生项" * 8000}}]
    store.write(run)
    run_path = next(store.root.glob(f"*/*/runs/{run_id}/run.json"))
    physical = json.loads(run_path.read_text(encoding="utf-8"))
    refs = physical["payload_storage"]["refs"]
    assert refs["tool_results/0/result"] == refs["tool_results/0/delivered_result"]
    assert run_path.stat().st_size < 10000
    fresh = DraftStore(store.root)
    assert fresh.load(run_id) == run
    assert fresh.load(run_id)["tool_results"][0]["arguments"] == {"$run_payload": "literal"}
    inconsistent = deepcopy(physical)
    inconsistent["tool_results"][0]["result"] = {"text": "冲突内联"}
    run_path.write_text(json.dumps(inconsistent), encoding="utf-8")
    with pytest.raises(StoreConflict, match="source_invalid"):
        fresh.load(run_id)
    run_path.write_text(json.dumps(physical), encoding="utf-8")

    def forbidden_load(*args, **kwargs):
        """依赖：pytest。输入：误入冷load的调用。输出：失败。实现：热接收、事件和live路径必须不展开历史工具产物。"""
        raise AssertionError("热接收不应调用完整load")

    monkeypatch.setattr(fresh, "load", forbidden_load)
    fresh.receive(run_id, "turn-new", "已持久的中文前缀。")
    view = fresh.snapshot(run_id, view="live")
    assert view["received_text"] == "已持久的中文前缀。"
    assert view["events"][-1]["type"] == "text_delta"
    assert fresh.snapshot(run_id, view="live", after=view["event_seq"])["events"] == []
    assert fresh.snapshot(run_id, view="live", after=999)["events_reset"] is True
    restarted = DraftStore(store.root)
    assert restarted.load(run_id)["tool_results"] == run["tool_results"]
    digest = refs["tool_results/0/result"]
    payload = run_path.parent / "payloads" / (digest[7:] + ".json")
    saved = payload.read_bytes()
    payload.write_bytes(b'{}')
    with pytest.raises(StoreConflict, match="source_invalid"):
        restarted.load(run_id)
    payload.write_bytes(saved)
    payload.unlink()
    with pytest.raises(StoreConflict, match="source_invalid"):
        restarted.load(run_id)


def test_payload_failure_never_replaces_committed_run(observation_runtime, monkeypatch) -> None:
    """依赖：真实原子保存故障注入。输入：待外置大回执。输出：payload失败/引用提升失败都保留原run。实现：包装原writer，在独立目录核原字节。"""
    import novel_rag.generation.store as store_module

    _, writer, run_id = observation_runtime
    store = writer.store
    path = next(store.root.glob(f"*/*/runs/{run_id}/run.json"))
    before = path.read_bytes()
    proposed = store.load(run_id)
    proposed["tool_results"] = [{"call_id": "new", "result": {"text": "新内容" * 5000}}]
    original_bytes = store_module.atomic_write_bytes

    def failed_payload(target, value):
        """依赖：原bytes writer。输入：保存路径/字节。输出：故障或原结果。实现：仅拒绝payload，run不应提升。"""
        if target.parent.name == "payloads":
            raise OSError("payload unavailable")
        return original_bytes(target, value)

    monkeypatch.setattr(store_module, "atomic_write_bytes", failed_payload)
    with pytest.raises(OSError):
        store.write(proposed)
    assert path.read_bytes() == before
    monkeypatch.setattr(store_module, "atomic_write_bytes", original_bytes)
    original_json = store_module.atomic_write_json

    def failed_run(target, value):
        """依赖：原JSON writer。输入：保存路径/run。输出：故障或原结果。实现：payload可先保存，但只拒绝run提升。"""
        if target.name == "run.json":
            raise OSError("run unavailable")
        return original_json(target, value)

    monkeypatch.setattr(store_module, "atomic_write_json", failed_run)
    with pytest.raises(OSError):
        store.write(proposed)
    assert path.read_bytes() == before
    assert DraftStore(store.root).load(run_id).get("tool_results") is None


def test_small_author_browse_has_explicit_terminal_progress(observation_runtime) -> None:
    """依赖：真实作者浏览/router。输入：小于64可见节点的空记忆run。输出：准确访问数/已结束/无下一入口。实现：小包也给作者计数，不改变模型默认recall形状。"""
    _, writer, run_id = observation_runtime
    page = writer.browse_memory(run_id, {})["packet"]
    assert page["candidate_search"]["complete"] is True
    assert page["candidate_search"]["next_arguments"] is None
    assert page["candidate_search"]["visited_count"] == page["candidate_search"]["page_visited_count"]
    model = writer.harness_tool(run_id, "recall", {})
    assert "candidate_search" not in model


def test_recovery_does_not_downgrade_unknown_payload_layout(observation_runtime) -> None:
    """依赖：真实Store恢复/布局校验。输入：未知version的运行中物理文件。输出：明确拒绝且原字节不变。实现：独立目录改header，不把未知格式重新写成当前版本。"""
    _, writer, run_id = observation_runtime
    path = next(writer.store.root.glob(f"*/*/runs/{run_id}/run.json"))
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.update(status="running", payload_storage={"version": 2, "refs": {}})
    path.write_text(json.dumps(raw), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(StoreConflict, match="source_invalid"):
        DraftStore(writer.store.root).recover()
    assert path.read_bytes() == before


def test_live_snapshot_retains_parent_adoption_target_without_cold_load(observation_runtime, tmp_path: Path, monkeypatch) -> None:
    """依赖：真实草稿字节/父链/ASGI。输入：父run采用事实夹具及子run。输出：live采用hash/坐标与原owner一致且无冷load。实现：实际保存Ref后构造隔离父采用header，HTTP读轻视图。"""
    root, writer, run_id = observation_runtime
    draft = writer.harness_tool(run_id, "save_draft", {"text": "父稿正文。", "expected_revision": 0}, "save")
    parent = writer.store.load(run_id)
    target = {"kind": "document", "document_id": "history-parent", "source_revision": 1,
              "source_hash": "sha256:" + "a" * 64, "scope": {"story_id": "demo", "timeline_id": "main"},
              "coordinate": {"volume": 1, "chapter": 2, "scene": 3}}
    parent["adoption"] = {"source_ref": target}
    writer.store.write(parent)
    child = deepcopy(parent)
    child.update(run_id="run-child", adoption=None, tool_results=[], drafts={})
    child["binding"]["base_ref"] = draft
    writer.store.write(child)
    app = create_app(root, writer.store.root, tmp_path / "no-model.json")

    def forbidden(*args, **kwargs):
        """依赖：pytest。输入：意外冷读取/召回。输出：失败。实现：live父链只可读取检查点和热header。"""
        raise AssertionError("live父链触发冷读取")

    monkeypatch.setattr(app.state.service.store, "load", forbidden)
    monkeypatch.setattr(app.state.service.memory, "recall", forbidden)

    async def scenario():
        """依赖：真实ASGI中间件。输入：闭包app/child。输出：采用目标/默认建议坐标断言。实现：原token读live，父正文引用仍由Store核验。"""
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            response = await client.get("/api/v1/runs/run-child?view=live", headers={"x-workspace-token": app.state.token})
            assert response.status_code == 200, response.text
            view = response.json()
            assert view["adoption_target_source_hash"] == target["source_hash"]
            assert view["adoption_target_coordinate"] == view["suggested_coordinate"] == target["coordinate"]
    asyncio.run(scenario())


@pytest.mark.parametrize("navigation_runtime", [130], indirect=True)
def test_author_browse_isolated_from_model_context_and_survives_cancel(navigation_runtime) -> None:
    """依赖：真实130线索/原context与工具。输入：模型焦点及作者取消后翻批。输出：64/64/2和来源失效，模型选择/材料/事件/稿件保持。实现：原origin行冻结，重启同Store续查。"""
    root, writer, run_id, ids = navigation_runtime
    writer.harness_tool(run_id, "recall", {"focus": [next(iter(ids.values()))], "query": "铜牌"})
    writer.cancel(run_id)
    before = writer.store.load(run_id)
    definitions = writer.tool_dispatcher(run_id).definitions()
    expected = context_binding(before, writer.memory, writer.store, definitions)
    first = writer.browse_memory(run_id, {})["packet"]
    assert len(first["hooks"]) == 64
    second = writer.browse_memory(run_id, first["candidate_search"]["next_arguments"])["packet"]
    assert len(second["hooks"]) == 64
    restarted = build_writer_service(root, writer.store.root, writer.config.path)
    third = restarted.browse_memory(run_id, second["candidate_search"]["next_arguments"])["packet"]
    assert len(third["hooks"]) == 2 and third["candidate_search"]["next_arguments"] is None
    after = writer.store.load(run_id)
    assert active_recall_selection(after) == active_recall_selection(before)
    assert all(after[key] == before[key] for key in ("events", "draft_ref", "memory_batches", "tool_commits", "memory_revision"))
    actual = context_binding(after, writer.memory, writer.store, definitions)
    assert actual["manifest"] == expected["manifest"]
    assert actual["recovery_materials"] == expected["recovery_materials"]
    assert writer.harness_tool(run_id, "recall", {})["error"]["code"] == "cancelled"
    current = writer.store.load(run_id)
    current.update(cancel_requested=False, status="prepared")
    writer.store.write(current)
    cross = writer.execute_tool(run_id, ToolCall("model-cursor", "recall", first["candidate_search"]["next_arguments"]))
    assert cross["error"]["code"] == "scope_denied"
