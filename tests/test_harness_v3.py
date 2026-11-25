from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading

import httpx
import pytest

from native_http_fixture import NativeEndpoint, workspace_server
from novel_rag.generation import store as store_module
from novel_rag.generation.session import RunService
from novel_rag.generation.store import DraftStore, StoreConflict
from novel_rag.identity import GraphKey
from novel_rag.memory.service import MemoryService
from novel_rag.service import load_story_sources
from novel_rag.std import atomic_io
from novel_rag.web.app import create_app
from test_writer_session import _runtime, _text_response
from writer_fixtures import make_library, put_document


class _NoModelConfig:
    """供纯宿主驱动测试使用的模型配置陷阱。"""

    def __getattr__(self, name: str):
        """依赖：Python属性访问。输入：任意模型配置成员名。输出：无。实现：一旦harness路径读配置就让测试失败。"""

        raise AssertionError(f"harness path accessed model config: {name}")


def _service(root: Path, workspace: Path) -> tuple[RunService, DraftStore, MemoryService]:
    """依赖：RunService、DraftStore与MemoryService。输入：资料库根和工作区。输出：不含模型配置的harness服务。实现：注入属性访问即失败的配置对象，确保宿主路径不读profile。"""

    store = DraftStore(workspace)
    memory = MemoryService(root, store)
    return RunService(root, store, memory, _NoModelConfig()), store, memory


def _state_and_event_update() -> dict:
    """依赖：MemoryService真实写入形状。输入：无。输出：引用正文检查点的事件线和状态差分。实现：使用本批local_ref，不预造稳定记忆ID。"""

    return {
        "event_lines": [{
            "op": "create",
            "local_ref": "handoff-line",
            "record": {"record_kind": "event_line", "payload": {"title": "交接发生"}},
        }],
        "state_changes": [{
            "op": "set",
            "local_ref": "key-custody",
            "entry": {
                "domain": "World",
                "kind": "custody",
                "value": "铜钥匙目前由甲保管。",
                "lifetime": "carry",
            },
        }],
    }


def test_harness_runs_five_native_tools_without_reading_model_config(tmp_path: Path) -> None:
    """验证harness准备、五工具提交和记忆版本推进不读取模型配置。依赖：RunService/DraftStore/MemoryService与标准fixture。输入：一本文档和无profile的作者任务。输出：五工具可用、实际DraftRef驱动记忆且run快照记录修订。实现：用会在任何配置读取时抛错的对象执行完整工具往返，并核对正式History字节不变。"""

    root = make_library(tmp_path)
    history_path = put_document(root, "chapter-one", "铜钥匙交给甲保管。")
    history_before = history_path.read_bytes()
    scope = GraphKey("demo", "main")
    source = load_story_sources(root, scope).source_refs["chapter-one"]
    service, store, _memory = _service(root, tmp_path / "workspace")

    run_id = service.prepare(scope, "write", "沿作者路线继续", "写出钥匙的交接。", base_ref=source)
    run = store.load(run_id)
    definitions = service.tool_dispatcher(run_id).definitions()
    assert run["driver"] == "harness"
    assert run["status"] == "prepared"
    assert run["profile_name"] is None
    assert set(item["name"] for item in definitions) == {
        "recall", "read_document", "read_writing_reference", "save_draft", "remember",
    }
    with pytest.raises(ValueError, match="harness任务由宿主模型驱动"):
        asyncio.run(service.run(run_id))

    recall = service.harness_tool(run_id, "recall", {"query": "铜钥匙"})
    read = service.harness_tool(run_id, "read_document", {"document_id": "chapter-one"})
    resource_id = next(item for item in definitions if item["name"] == "read_writing_reference")["parameters"]["properties"]["resource_id"]["enum"][0]
    reference = service.harness_tool(run_id, "read_writing_reference", {"resource_id": resource_id})
    saved = service.harness_tool(
        run_id,
        "save_draft",
        {"text": "甲把铜钥匙收进衣袋。", "expected_revision": 0},
        operation_id="save-opening",
    )
    remembered = service.harness_tool(
        run_id,
        "remember",
        {
            "draft_ref": saved,
            "expected_memory_revision": 0,
            "update": _state_and_event_update(),
        },
        operation_id="remember-handoff",
    )

    assert recall["memory_revision"] == 0
    assert "铜钥匙交给甲保管。" in read["text"]
    assert reference["resource_id"] == resource_id
    assert saved["kind"] == "draft"
    assert remembered["memory_revision"] == 1
    snapshot = store.snapshot(run_id)
    assert snapshot["draft_ref"] == saved
    assert snapshot["draft_revision"] == 1
    assert snapshot["memory_revision"] == 1
    assert snapshot["memory_batches"][0]["draft_ref"] == saved
    assert snapshot["memory_batches"][0]["source_refs"] == [saved]
    assert snapshot["memory_batches"][0]["update"]["state_changes"][0]["entry"]["source_refs"] == [saved]
    context = service.harness_context(run_id)
    assert context["draft_ref"] == saved
    assert context["draft_revision"] == 1
    assert context["memory_revision"] == 1
    assert set(context["committed_operations"]) == {
        "harness:save_draft:save-opening", "harness:remember:remember-handoff",
    }
    assert history_path.read_bytes() == history_before


def test_harness_request_id_is_idempotent_and_conflicts_on_changed_inputs(tmp_path: Path) -> None:
    """验证prepare的稳定request_id恢复与参数冲突。依赖：真实RunService/DraftStore。输入：同一作品线的两次相同请求及一次改纲请求。输出：相同请求返回原run、改参不新建run。实现：检查磁盘run列表和StoreConflict。"""

    root = make_library(tmp_path)
    service, store, _memory = _service(root, tmp_path / "workspace")
    arguments = (GraphKey("demo", "main"), "write", "原始大纲", "本轮请求")
    first = service.prepare(*arguments, request_id="host-request-01")
    recovered = service.prepare(*arguments, request_id="host-request-01")

    assert recovered == first
    with pytest.raises(StoreConflict, match="同请求ID参数不同"):
        service.prepare(arguments[0], arguments[1], "修改后的大纲", arguments[3], request_id="host-request-01")
    with pytest.raises(StoreConflict, match="同请求ID参数不同"):
        service.prepare(*arguments, driver="builtin", request_id="host-request-01")
    with pytest.raises(ValueError, match="driver/profile组合不合法"):
        service.prepare(*arguments, profile_name="unused-profile", request_id="host-request-02")
    run_files = list((store.root / "demo" / "main" / "runs").glob("*/run.json"))
    assert len(run_files) == 1


def test_read_document_respects_story_and_narrative_cursor(tmp_path: Path) -> None:
    """验证read_document不能读取另一作品或游标之后的来源。依赖：load_story_sources与真实ToolDispatcher。输入：基线、未来章节和另一作品正文。输出：仅基线可读且上下文不泄露越界正文。实现：固定基线DocumentRef后经实际工具路径分别请求三类文档。"""

    root = make_library(tmp_path)
    put_document(root, "past-scene", "基线正文标记：雨停了。", chapter=1, scene=1)
    put_document(root, "future-scene", "未来正文标记：钟声响起。", chapter=2, scene=1)
    put_document(root, "foreign-scene", "异书正文标记：门被推开。", story="other", chapter=1, scene=1)
    scope = GraphKey("demo", "main")
    base = load_story_sources(root, scope).source_refs["past-scene"]
    service, _store, _memory = _service(root, tmp_path / "workspace")
    run_id = service.prepare(scope, "write", "继续原路线", "推进后续。", base_ref=base)

    allowed = service.harness_tool(run_id, "read_document", {"document_id": "past-scene"})
    future = service.harness_tool(run_id, "read_document", {"document_id": "future-scene"})
    foreign = service.harness_tool(run_id, "read_document", {"document_id": "foreign-scene"})
    context_text = json.dumps(service.harness_context(run_id)["messages"], ensure_ascii=False)

    assert "基线正文标记：雨停了。" in allowed["text"]
    assert future["ok"] is False
    assert foreign["ok"] is False
    assert "未来正文标记：钟声响起。" not in context_text
    assert "异书正文标记：门被推开。" not in context_text


def test_harness_feedback_inherits_driver_and_saves_only_one_parent_prefix(tmp_path: Path) -> None:
    """验证finish后反馈继承harness、保留原大纲并只拼接一次父稿。依赖：RunService/DraftStore共享拼装器。输入：已完成父稿及反馈请求。输出：新分支正文为父稿加完整后缀，原稿路线保留。实现：父子run均经实际稳定工具写入，再由Store解析不可变检查点。"""

    root = make_library(tmp_path)
    service, store, _memory = _service(root, tmp_path / "workspace")
    scope = GraphKey("demo", "main")
    original_outline = "先交接铜钥匙，再让甲独自离开。"
    parent_id = service.prepare(scope, "write", original_outline, "写交接场景。")
    parent_ref = service.harness_tool(
        parent_id,
        "save_draft",
        {"text": "正文前缀：甲接过铜钥匙。", "expected_revision": 0},
        operation_id="parent-save",
    )
    parent = store.load(parent_id)
    service.finish_harness(parent_id, "completed")

    child_id = service.feedback(parent["session_id"], parent_id, "write", "补写甲离开后的动作。")
    child = store.load(child_id)
    suffix = "后缀正文：甲把钥匙放进口袋，独自走进雨里。"
    child_ref = service.harness_tool(
        child_id,
        "save_draft",
        {"text": suffix, "expected_revision": child["draft_revision"]},
        operation_id="child-save",
    )
    service.finish_harness(child_id, "completed")
    _child_run, assembled = store.resolve_draft(child_ref)

    assert parent["status"] == "prepared"
    assert child["driver"] == "harness"
    assert child["status"] == "prepared"
    assert child["parent_run_id"] == parent_id
    assert child["request_snapshot"]["outline"] == original_outline
    assert child["request_snapshot"]["request"] == "补写甲离开后的动作。"
    assert child["binding"]["base_ref"] == parent_ref
    assert child["binding"]["output_mode"] == "append_suffix"
    assert child["binding"]["draft_branch"] != parent["binding"]["draft_branch"]
    assert assembled == "正文前缀：甲接过铜钥匙。" + suffix
    assert assembled.count("正文前缀：甲接过铜钥匙。") == 1
    assert store.snapshot(child_id)["status"] == "completed"


@pytest.mark.parametrize("failure", ["prefix", "prefix_snapshot", "session"])
def test_feedback_replays_unfinished_creation_after_backend_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    """依赖：真实HTTP后端/磁盘Store。输入：正文或索引I/O失败、同ID并发重试。输出：仅一个原子稿及索引。实现：注入一次写失败，改选父稿后重启，比对分支绑定、真实稿字节和终态重放。"""
    root = make_library(tmp_path)
    workspace = tmp_path / "workspace"
    model_config = tmp_path / "no-model.json"
    store = DraftStore(workspace)
    prefix = "不可变的父稿。" * 550
    child_dir = workspace / "demo" / "main" / "runs"
    operation = {"request_id": "feedback-create-once", "request": "续写原父稿。"}

    first_app = create_app(root, workspace, model_config)
    with workspace_server(first_app) as backend:
        with httpx.Client(base_url=backend, timeout=15) as client:
            headers = {"x-workspace-token": client.get("/api/v1/harness/bootstrap").json()["token"]}
            opened = client.post("/api/v1/runs", headers=headers, json={"driver": "harness", "story_id": "demo"})
            opened.raise_for_status()
            parent_id, session_id = opened.json()["run_id"], opened.json()["session_id"]
            parent_ref = first_app.state.service.save_author_draft(parent_id, 0, prefix).as_dict()
            session_path = child_dir.parent / "sessions" / session_id / "session.json"
            feedback_url = f"/api/v1/sessions/{session_id}/feedback"
            operation["base_run_id"] = parent_id
            if failure == "session":
                operation["base_ref"] = parent_ref
            if failure != "prefix_snapshot":
                operation["selected_parent_checkpoint"] = parent_ref["checkpoint_id"]
            original_write_bytes = store_module.atomic_write_bytes
            original_write_run = store_module.atomic_write_json
            original_write_json = atomic_io.atomic_write_json

            def fail_prefix(path: Path, raw: bytes) -> None:
                """依赖：正文写入原语。输入：目标与字节。输出：子稿首次写入故障。实现：其余文件沿用真实写入。"""
                if path.parent.name == "drafts" and path.parent.parent.name != parent_id:
                    raise OSError("injected prefix write failure")
                original_write_bytes(path, raw)

            def fail_run(path: Path, data: dict) -> None:
                """依赖：快照写入原语。输入：目标与JSON。输出：子稿引用提交故障。实现：在正文写入后拒绝首次草稿快照。"""
                if path.name == "run.json" and path.parent.name != parent_id and data["draft_revision"] == 1:
                    raise OSError("injected prefix snapshot failure")
                original_write_run(path, data)

            def fail_index(path: Path, data: dict) -> None:
                """依赖：索引写入原语。输入：目标与JSON。输出：子run登记故障。实现：其余文件沿用真实写入。"""
                if path == session_path:
                    raise OSError("injected session index write failure")
                original_write_json(path, data)

            with monkeypatch.context() as patch:
                if failure == "prefix":
                    patch.setattr(store_module, "atomic_write_bytes", fail_prefix)
                elif failure == "prefix_snapshot":
                    patch.setattr(store_module, "atomic_write_json", fail_run)
                else:
                    patch.setattr(atomic_io, "atomic_write_json", fail_index)
                failed = client.post(feedback_url, headers=headers, json=operation)
            assert failed.status_code == 400
            assert failed.json()["error"]["code"] == "save_failed"
            child_path, = [path for path in child_dir.glob("*/run.json") if path.parent.name != parent_id]
            child_id = child_path.parent.name
            persisted = store.load(child_id)
            assert persisted["draft_revision"] == (1 if failure == "session" else 0)
            assert persisted["binding"]["base_ref"] == parent_ref
            assert json.loads(session_path.read_bytes())["run_ids"] == [parent_id]
            if failure == "prefix_snapshot":
                assert (child_path.parent / "drafts" / "1.txt").read_bytes() == prefix.encode("utf-8")
            if failure == "session":
                assert "payload_storage" in json.loads(child_path.read_bytes())
            changed_parent_ref = first_app.state.service.save_author_draft(parent_id, 1, "父稿改选之后的正文。").as_dict()

    restarted_app = create_app(root, workspace, model_config)
    with workspace_server(restarted_app) as backend:
        with httpx.Client(base_url=backend, timeout=15) as client:
            headers = {"x-workspace-token": client.get("/api/v1/harness/bootstrap").json()["token"]}
            conflict = client.post(feedback_url, headers=headers, json={**operation, "base_ref": changed_parent_ref,
                                  "selected_parent_checkpoint": changed_parent_ref["checkpoint_id"]})
            assert conflict.status_code == 409
            if failure == "prefix":
                implicit_conflict = client.post(feedback_url, headers=headers, json={**operation,
                    "selected_parent_checkpoint": changed_parent_ref["checkpoint_id"]})
                assert implicit_conflict.status_code == 409
            assert store.load(child_id) == persisted
            with ThreadPoolExecutor(max_workers=2) as executor:
                retried = [executor.submit(client.post, feedback_url, headers=headers, json=operation) for _ in range(2)]
                replies = [future.result() for future in retried]
            assert [response.status_code for response in replies] == [200, 200], [response.text for response in replies]
            assert [response.json()["run_id"] for response in replies] == [child_id, child_id]
            recovered = store.load(child_id)
            assert recovered["binding"] == persisted["binding"]
            assert recovered["draft_revision"] == len(recovered["drafts"]) == 1
            assert store.resolve_draft(recovered["draft_ref"])[1] == prefix
            assert json.loads(session_path.read_bytes())["run_ids"] == [parent_id, child_id]
            if persisted["draft_ref"]:
                assert recovered["draft_ref"] == persisted["draft_ref"]
            saved = client.post(f"/api/v1/runs/{child_id}/harness-tool", headers=headers,
                                json={"name": "save_draft", "operation_id": "recovered-child-save",
                                      "arguments": {"text": "恢复后生成的后缀。", "expected_revision": 1}})
            saved.raise_for_status()
            assert store.resolve_draft(saved.json())[1] == prefix + "恢复后生成的后缀。"
            edited = restarted_app.state.service.save_author_draft(child_id, 2, "作者独立编辑后的子稿。").as_dict()
            finished = client.post(f"/api/v1/runs/{child_id}/harness-finish", headers=headers,
                                   json={"status": "completed"})
            finished.raise_for_status()
            before_retry = child_path.read_bytes(), session_path.read_bytes()
            replayed = client.post(feedback_url, headers=headers, json=operation)
            assert replayed.json()["run_id"] == child_id
            assert store.load(child_id)["status"] == "completed"
            assert store.resolve_draft(edited)[1] == "作者独立编辑后的子稿。"
            assert (child_path.read_bytes(), session_path.read_bytes()) == before_retry
            assert len(list(child_dir.glob("*/run.json"))) == 2


def test_feedback_replay_repairs_missing_index_without_changing_running_or_interrupted_draft(tmp_path: Path) -> None:
    """依赖：原Store/startup recover。输入：缺索引、已改稿且仍为旧内联格式的运行。输出：仅补索引并保持执行状态及正文。实现：模拟旧反馈遗留，运行态重试，再重新启动为interrupted并重放。"""
    root = make_library(tmp_path)
    service, store, _memory = _service(root, tmp_path / "workspace")
    parent_id = service.prepare(GraphKey("demo", "main"), "write", "继续", "先写父稿。")
    parent_ref = service.save_author_draft(parent_id, 0, "原父稿。").as_dict()
    parent = store.load(parent_id)
    session_id = parent["session_id"]
    arguments = (session_id, parent_id, "write", "继续该父稿。", parent_ref)
    child_id = service.feedback(*arguments, request_id="legacy-feedback")
    edited = service.save_author_draft(child_id, 1, "作者已改写的子稿。" * 400).as_dict()
    child = store.set_status(child_id, "running")
    root_path = store.root / "demo" / "main"
    run_path = root_path / "runs" / child_id / "run.json"
    session_path = root_path / "sessions" / session_id / "session.json"
    index = json.loads(session_path.read_bytes())
    atomic_io.atomic_write_json(session_path, {**index, "run_ids": [parent_id]})
    atomic_io.atomic_write_json(run_path, child)
    inline_before_retry = run_path.read_bytes()

    assert service.feedback(*arguments, request_id="legacy-feedback") == child_id
    assert run_path.read_bytes() == inline_before_retry
    assert store.load(child_id)["status"] == "running"
    assert json.loads(session_path.read_bytes()) == index

    restarted, restarted_store, _memory = _service(root, store.root)
    with restarted.writer_lease():
        assert restarted.recover() == [child_id]
        assert restarted.feedback(*arguments, request_id="legacy-feedback") == child_id
    interrupted = restarted_store.load(child_id)
    assert interrupted["status"] == "interrupted"
    assert interrupted["draft_ref"] == edited
    assert interrupted["draft_revision"] == len(interrupted["drafts"]) == 2
    assert restarted_store.resolve_draft(edited)[1] == "作者已改写的子稿。" * 400
    assert json.loads(session_path.read_bytes()) == index


@pytest.mark.parametrize("terminal", ["completed", "cancelled"])
def test_harness_recovers_committed_operation_after_terminal_and_rejects_new_write(
    terminal: str,
    tmp_path: Path,
) -> None:
    """验证completed/cancelled后稳定ID恢复旧提交且拒绝新写。依赖：RunService/DraftStore幂等回执。输入：已提交的save_draft、一个终态和新operation_id。输出：旧DraftRef原样返回且新副作用返回cancelled。实现：真实终止run后分别重放同ID与发送新ID并比较检查点数量。"""

    root = make_library(tmp_path)
    service, store, _memory = _service(root, tmp_path / "workspace")
    run_id = service.prepare(GraphKey("demo", "main"), "write", "一条路线", "保存一个检查点。")
    arguments = {"text": "已提交正文。", "expected_revision": 0}
    committed = service.harness_tool(run_id, "save_draft", arguments, operation_id="save-once")

    if terminal == "completed":
        service.finish_harness(run_id, "completed")
    else:
        service.cancel(run_id)

    replayed = service.harness_tool(run_id, "save_draft", arguments, operation_id="save-once")
    rejected = service.harness_tool(
        run_id,
        "save_draft",
        {"text": "终态之后的新正文。", "expected_revision": 1},
        operation_id="save-after-terminal",
    )
    snapshot = store.load(run_id)

    assert replayed == committed
    assert rejected["ok"] is False
    assert rejected["error"]["code"] == "cancelled"
    assert len(snapshot["drafts"]) == 1
    assert snapshot["status"] == terminal


def test_harness_author_save_protects_selection_and_operation_arguments(tmp_path: Path) -> None:
    """验证作者提交后模型检查点只另存，稳定ID重试不重复落盘且改参冲突。依赖：DraftStore作者修订与harness工具幂等。输入：作者稿和同ID两次save_draft。输出：作者稿仍选中、原DraftRef恢复、改参被拒。实现：核对权威run快照中的drafts、修订与选中指针。"""

    root = make_library(tmp_path)
    service, store, _memory = _service(root, tmp_path / "workspace")
    run_id = service.prepare(GraphKey("demo", "main"), "write", "保留路线", "修改措辞。")
    author_ref = store.save(run_id, 0, "作者确认正文。", origin="author").as_dict()
    arguments = {"text": "模型生成的另存稿。", "expected_revision": 1}

    generated_ref = service.harness_tool(run_id, "save_draft", arguments, operation_id="stable-save")
    before_retry = store.load(run_id)
    retried_ref = service.harness_tool(run_id, "save_draft", arguments, operation_id="stable-save")
    after_retry = store.load(run_id)

    assert generated_ref["draft_revision"] == 2
    assert generated_ref != author_ref
    assert before_retry["draft_ref"] == author_ref
    assert before_retry["draft_revision"] == 1
    assert before_retry["generated_draft_ref"] == generated_ref
    assert after_retry["draft_ref"] == author_ref
    assert len(after_retry["drafts"]) == len(before_retry["drafts"]) == 2
    assert retried_ref == generated_ref
    with pytest.raises(StoreConflict, match="同调用ID参数不同"):
        service.harness_tool(
            run_id,
            "save_draft",
            {"text": "相同操作ID改了正文。", "expected_revision": 1},
            operation_id="stable-save",
        )


def test_harness_rejects_boolean_and_unknown_tool_arguments(tmp_path: Path) -> None:
    """验证工具基础类型和字段白名单拒绝bool冒充整数及未知字段。依赖：ToolDispatcher唯一schema校验。输入：合法harness run、非法CAS值及额外参数。输出：均为source_invalid且没有提交副作用。实现：经外部工具入口检查结构化错误和原始run修订。"""

    root = make_library(tmp_path)
    service, store, _memory = _service(root, tmp_path / "workspace")
    run_id = service.prepare(GraphKey("demo", "main"), "write", "路线", "检查参数。")

    boolean_revision = service.harness_tool(
        run_id,
        "save_draft",
        {"text": "不应保存。", "expected_revision": True},
        operation_id="invalid-bool",
    )
    unknown_field = service.harness_tool(run_id, "recall", {"query": "铜钥匙", "scope": "other/main"})
    with pytest.raises(ValueError, match="需要1–128字符稳定operation_id"):
        service.harness_tool(run_id, "save_draft", {"text": "缺ID", "expected_revision": 0})
    snapshot = store.load(run_id)

    assert boolean_revision["ok"] is False
    assert boolean_revision["error"]["code"] == "source_invalid"
    assert unknown_field["ok"] is False
    assert unknown_field["error"]["code"] == "source_invalid"
    assert snapshot["draft_revision"] == 0
    assert snapshot["memory_revision"] == 0
    assert snapshot["tool_commits"] == {}


@pytest.mark.parametrize("terminal", ["completed", "cancelled"])
def test_author_input_note_without_draft_ref_replays_after_terminal(
    terminal: str,
    tmp_path: Path,
) -> None:
    """验证真实AuthorInputRef笔记可省略draft_ref，且终态后同操作恢复原结果。依赖：RunService、ToolDispatcher与MemoryService唯一remember参数。输入：run真实input_snapshot_ref、纯作者计划note、completed或cancelled终态。输出：省略/显式None同语义、单批次单版本、改update冲突。实现：同稳定operation_id在终态前后提交/重放，并检查源引用与权威提交表。"""

    root = make_library(tmp_path)
    service, store, _memory = _service(root, tmp_path / "workspace")
    run_id = service.prepare(GraphKey("demo", "main"), "discuss", "作者计划保留", "记录可能的后续方向。")
    run = store.load(run_id)
    input_ref = run["binding"]["input_snapshot_refs"][0]
    assert input_ref["kind"] == "author_input"
    update = {"notes": [{
        "op": "create",
        "local_ref": "author-plan",
        "record": {
            "record_kind": "note",
            "payload": {"text": "作者计划：下一幕揭示铜钥匙的来历。"},
            "source_refs": [input_ref],
        },
    }]}
    omitted_arguments = {"expected_memory_revision": 0, "update": update}
    call_id = "author-plan-note"

    committed = service.harness_tool(run_id, "remember", omitted_arguments, operation_id=call_id)
    if terminal == "completed":
        service.finish_harness(run_id, "completed")
    else:
        service.cancel(run_id)

    omitted_replay = service.harness_tool(run_id, "remember", omitted_arguments, operation_id=call_id)
    explicit_none_replay = service.harness_tool(
        run_id,
        "remember",
        {**omitted_arguments, "draft_ref": None},
        operation_id=call_id,
    )
    changed_update = {"notes": [{
        "op": "create",
        "local_ref": "author-plan",
        "record": {
            "record_kind": "note",
            "payload": {"text": "作者计划已更改，不能复用原操作ID。"},
            "source_refs": [input_ref],
        },
    }]}
    with pytest.raises(StoreConflict, match="同调用ID参数不同"):
        service.harness_tool(
            run_id,
            "remember",
            {"expected_memory_revision": 0, "update": changed_update},
            operation_id=call_id,
        )

    snapshot = store.load(run_id)
    batch = snapshot["memory_batches"][0]
    assert committed["memory_revision"] == 1
    assert omitted_replay == committed
    assert explicit_none_replay == committed
    assert snapshot["status"] == terminal
    assert snapshot["memory_revision"] == 1
    assert len(snapshot["memory_batches"]) == 1
    assert batch["draft_ref"] is None
    assert batch["source_refs"] == [input_ref]
    assert batch["update"]["notes"][0]["record"]["source_refs"] == [input_ref]
    assert list(snapshot["tool_commits"]) == ["harness:remember:author-plan-note"]


def test_same_harness_operation_can_race_without_duplicate_checkpoint(tmp_path: Path) -> None:
    """验证同一稳定operation_id并发提交只落一个检查点。依赖：RunService持锁工具入口与DraftStore提交表。输入：同时启动的两个同参数save_draft调用。输出：两方收到同一DraftRef且仅一个草稿提交。实现：Barrier同步两个线程争抢同一operation_id，再读取权威run快照。"""

    root = make_library(tmp_path)
    service, store, _memory = _service(root, tmp_path / "workspace")
    run_id = service.prepare(GraphKey("demo", "main"), "write", "路线", "并发保存。")
    arguments = {"text": "并发调用的同一正文。", "expected_revision": 0}
    start = threading.Barrier(3)

    def save_after_barrier() -> dict:
        """依赖：同一个RunService和Barrier。输入：无。输出：并发harness工具结果。实现：屏障释放后用相同稳定ID进入唯一保存路径。"""

        start.wait(timeout=3)
        return service.harness_tool(run_id, "save_draft", arguments, operation_id="racing-save")

    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(save_after_barrier) for _ in range(2)]
        start.wait(timeout=3)
        first, second = (call.result(timeout=5) for call in calls)

    snapshot = store.load(run_id)
    assert first == second
    assert first["kind"] == "draft"
    assert len(snapshot["drafts"]) == 1
    assert snapshot["draft_revision"] == 1
    assert list(snapshot["tool_commits"]) == ["harness:save_draft:racing-save"]


def test_builtin_start_and_model_run_remain_available_with_explicit_harness_feedback(tmp_path: Path) -> None:
    """验证旧builtin start/run正常完成且可显式切换harness反馈。依赖：NativeEndpoint、既有writer runtime factory与RunService。输入：原生文本响应和完成run的反馈请求。输出：builtin正文保持可用，新反馈host-owned且复用原始大纲。实现：发送一次本地模型请求，再经feedback(driver=harness)创建新分支。"""

    root = make_library(tmp_path)
    scope = GraphKey("demo", "main")
    outline = "作者原路线：让甲在雨中离开。"
    with NativeEndpoint([{
        "mode": "chat",
        "frames": _text_response("chat", "甲在雨中离开。")["frames"],
    }]) as endpoint:
        service, store, _memory, _config = _runtime(root, tmp_path / "workspace", endpoint, "chat")
        run_id = service.start(scope, "write", outline, "写下离开场景。", profile_name="fixture")
        completed = asyncio.run(service.run(run_id))

        host_run_id = service.feedback(
            completed["session_id"], run_id, "write", "补写路上的一个细节。", driver="harness",
        )
        host_run = store.load(host_run_id)

    assert completed["driver"] == "builtin"
    assert completed["status"] == "completed"
    assert completed["draft_text"] == "甲在雨中离开。"
    assert endpoint.callback_errors == []
    assert host_run["driver"] == "harness"
    assert host_run["status"] == "prepared"
    assert host_run["profile_name"] is None
    assert host_run["request_snapshot"]["outline"] == outline
    assert host_run["request_snapshot"]["request"] == "补写路上的一个细节。"
    assert host_run["parent_run_id"] == run_id
    assert host_run["binding"]["base_ref"] == completed["draft_ref"]
    assert host_run["binding"]["output_mode"] == "append_suffix"
