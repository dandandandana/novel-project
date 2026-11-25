from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from novel_rag.generation.session import RunService
from novel_rag.generation.store import DraftStore, StoreConflict
from novel_rag.identity import GraphKey
from novel_rag.memory.service import MemoryService
from writer_fixtures import make_library, put_document


def _author_service(tmp_path: Path):
    """依赖：隔离库夹具和原Store/Memory/RunService。输入：临时目录。输出：真实应用服务。实现：使用无模型配置的harness准备路径，不调用provider。"""
    root = make_library(tmp_path)
    store = DraftStore(tmp_path / "workspace")
    return RunService(root, store, MemoryService(root, store), object())


def test_author_partial_save_assembles_parent_once_and_survives_cancellation(tmp_path: Path) -> None:
    """依赖：原prepare/received/Store。输入：父草稿和取消后的接收后缀。输出：完整正文、partial归属和作者保护。实现：从公共作者入口保存，再核真实字节与模型停止门。"""
    service = _author_service(tmp_path)
    parent_id = service.prepare(GraphKey("demo", "main"), "write", "路线", "先写开头")
    parent = service.store.save(parent_id, 0, "父稿。", origin="model")
    run_id = service.prepare(GraphKey("demo", "main"), "write", "路线", "继续", base_ref=parent)
    service.store.receive(run_id, "turn-partial", "收到后缀。")
    service.cancel(run_id)

    saved = service.save_author_draft(run_id, 1, "收到后缀。")

    run = service.store.load(run_id)
    assert run["draft_text"] == "父稿。收到后缀。"
    assert service.store.resolve_draft(saved.as_dict())[1] == run["draft_text"]
    assert run["drafts"][saved.checkpoint_id]["origin"] == "partial"
    assert run["author_revision"] == saved.draft_revision == 2
    denied = service.harness_tool(run_id, "save_draft", {"text": "迟到模型稿", "expected_revision": 2}, "late-model")
    assert denied["ok"] is False and denied["error"]["code"] == "cancelled"
    assert service.store.load(run_id)["draft_ref"] == saved.as_dict()


def test_author_save_keeps_full_text_and_cas_without_replacing_model_draft(tmp_path: Path) -> None:
    """依赖：原Store CAS和工具选择门。输入：父稿、作者完整改稿和迟到模型保存。输出：作者选中稿不变、模型稿另存、旧CAS拒绝。实现：经同一应用入口和harness执行真实保存。"""
    service = _author_service(tmp_path)
    parent_id = service.prepare(GraphKey("demo", "main"), "write", "路线", "开头")
    parent = service.store.save(parent_id, 0, "旧父稿。", origin="model")
    run_id = service.prepare(GraphKey("demo", "main"), "write", "路线", "继续", base_ref=parent)
    saved = service.save_author_draft(run_id, 1, "作者改写全部内容。")
    with pytest.raises(StoreConflict, match="revision_conflict"):
        service.save_author_draft(run_id, 1, "旧页面覆盖。")
    generated = service.harness_tool(run_id, "save_draft", {"text": "模型后缀。", "expected_revision": 2}, "model-save")
    run = service.store.load(run_id)
    assert run["draft_ref"] == saved.as_dict()
    assert run["draft_text"] == "作者改写全部内容。"
    assert run["generated_draft_ref"] == generated
    assert run["generated_draft_text"] == "旧父稿。模型后缀。"


def test_partial_receipt_keeps_committed_body_when_snapshot_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    """依赖：原父草稿、接收前缀、回执和Store。输入：写入后运行快照读取故障。输出：确切修订、实际全文和独立读取状态。实现：禁止读取快照与记忆，回读不可变草稿核对。"""
    service = _author_service(tmp_path)
    scope = GraphKey("demo", "main")
    parent_id = service.prepare(scope, "write", "路线", "开头")
    parent = service.save_author_draft(parent_id, 0, "父稿。")
    child_id = service.prepare(scope, "write", "路线", "继续", base_ref=parent)
    service.store.receive(child_id, "turn-receipt", "后缀。")

    def unreadable(*args, **kwargs):
        """依赖：OSError。输入：快照调用。输出：磁盘读取错误。实现：模拟提交后的独立视图暂不可读。"""
        raise OSError("snapshot unavailable")

    def unexpected_recall(*args, **kwargs):
        """依赖：断言。输入：记忆调用。输出：测试失败。实现：捕获轻量保存中的隐式召回。"""
        raise AssertionError("live save accessed memory")

    monkeypatch.setattr(service.store, "snapshot", unreadable)
    monkeypatch.setattr(service.memory, "recall", unexpected_recall)
    receipt = service.save_author_draft_receipt(child_id, 1, "后缀。", view="live")
    assert receipt["snapshot_read"]["status"] == "unavailable" and "draft_text" not in receipt
    assert receipt["memory_read"] == {"status": "not_requested"}
    assert receipt["saved_draft_ref"]["draft_revision"] == receipt["saved_draft_revision"] == 2
    assert service.store.resolve_draft(receipt["saved_draft_ref"])[1] == receipt["saved_draft_text"] == "父稿。后缀。"


def test_save_receipt_identifies_own_commit_if_another_edit_precedes_the_view(tmp_path: Path, monkeypatch) -> None:
    """依赖：原保存与Store快照。输入：同run先后两份作者稿。输出：回执指向提交稿、视图指向新稿。实现：在首份提交与读视图之间插入第二次合法CAS。"""
    service = _author_service(tmp_path)
    run_id = service.prepare(GraphKey("demo", "main"), "write", "路线", "开头")
    read_snapshot = service.store.snapshot

    def later_edit(*args, **kwargs):
        """依赖：原保存及快照。输入：当前视图参数。输出：第二稿的运行快照。实现：在读视图时先提交竞争者的下一修订。"""
        service.save_author_draft(run_id, 1, "第二稿。")
        return read_snapshot(*args, **kwargs)

    monkeypatch.setattr(service.store, "snapshot", later_edit)
    receipt = service.save_author_draft_receipt(run_id, 0, "第一稿。", view="live")
    assert receipt["saved_draft_revision"] == 1 and receipt["saved_draft_text"] == "第一稿。"
    assert receipt["draft_revision"] == 2 and receipt["draft_text"] == "第二稿。"
    assert receipt["saved_draft_ref"] != receipt["draft_ref"]


def test_author_save_after_formal_history_does_not_prefix_previous_chapter(tmp_path: Path) -> None:
    """依赖：SourceCorpus正式来源/RunService。输入：正式前章和下一章partial。输出：新稿仅下一章文本。实现：通过既有output_mode决定拼装，不按存在base_ref误拼正文。"""
    service = _author_service(tmp_path)
    put_document(service.root, "previous-chapter", "正式前章。")
    run_id = service.prepare(GraphKey("demo", "main"), "write", "路线", "下一章")
    service.store.receive(run_id, "next-chapter", "新章未完。")
    saved = service.save_author_draft(run_id, 0, "新章未完。")
    assert service.store.resolve_draft(saved.as_dict())[1] == "新章未完。"


def test_source_factory_compatibility_delegates_exact_hooks(monkeypatch, tmp_path: Path) -> None:
    """依赖：组合根兼容入口与唯一源owner。输入：两个锁内hook。输出：唯一工厂结果及原hook身份。实现：替换底层工厂验证兼容入口不复制策略、不丢回调。"""
    from novel_rag import composition
    from novel_rag.mutations import source

    calls, sentinel = [], object()
    pre_commit, after_source_commit = object(), object()

    def build(root, **hooks):
        """依赖：测试记录。输入：库根与hooks。输出：哨兵。实现：记录唯一委托参数。"""
        calls.append((root, hooks))
        return sentinel

    monkeypatch.setattr(source, "build_source_mutation_coordinator", build)
    result = composition.build_source_mutation_coordinator(
        tmp_path, pre_commit=pre_commit, after_source_commit=after_source_commit,
    )
    assert result is sentinel
    assert calls == [(tmp_path, {"pre_commit": pre_commit, "after_source_commit": after_source_commit})]


def test_v3_memory_adoption_and_summary_work_without_composition(tmp_path: Path) -> None:
    """依赖：独立Python进程、真实v3服务/源提交/发布。输入：新临时作品。输出：记忆与正文发布成功且未加载composition。实现：从首次导入拦截组合根，运行prepare/save/remember/adopt及原ID恢复。"""
    import novel_rag

    root = make_library(tmp_path)
    script = '''
import importlib.abc
from pathlib import Path
import sys

class NoComposition(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        """依赖：导入hook。输入：模块名。输出：继续发现或错误。实现：拒绝任何v3对组合根的反向导入。"""
        if fullname == "novel_rag.composition":
            raise AssertionError("v3 business imported composition")
        return None

sys.path.insert(0, sys.argv[2])
sys.meta_path.insert(0, NoComposition())
from novel_rag.generation.session import RunService
from novel_rag.generation.store import DraftStore
from novel_rag.identity import GraphKey
from novel_rag.memory.service import MemoryService
from novel_rag.writeback.adopt import AdoptionService

root = Path(sys.argv[1])
store = DraftStore(root.parent / "independent-workspace")
memory = MemoryService(root, store)
service = RunService(root, store, memory, object())
run_id = service.prepare(GraphKey("demo", "main"), "write", "outline", "write",
                         target_coordinate={"volume": 1, "chapter": 1, "scene": 1})
ref = service.save_author_draft(run_id, 0, "Body.").as_dict()
arguments = {"draft_ref": ref, "expected_memory_revision": 0,
             "update": {"event_lines": [{"op": "create", "local_ref": "event",
                        "record": {"record_kind": "event_line", "payload": {"title": "Event"}}}]}}
receipt = memory.remember(run_id, "remember", **arguments)
assert receipt["memory_revision"] == 1
assert memory.remember(run_id, "remember", **arguments) == receipt
adoption = AdoptionService(root, store, memory)
result = adoption.adopt(run_id, ref["draft_revision"], None, None, "adopt")
assert result["adopted"] and result["memory_state"] == "complete", result
assert adoption.adopt(run_id, ref["draft_revision"], None, None, "adopt") == result
assert len(list((root / "stories" / "demo" / "timelines" / "main" / "summaries").glob("memory-*.yaml"))) == 1
assert "novel_rag.composition" not in sys.modules
print("v3 source submission and original-operation replay passed")
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(root), str(Path(novel_rag.__file__).resolve().parent.parent)],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("projection_owner", ["composition", "importers"])
def test_source_projection_skips_only_source_guard_while_it_is_held(tmp_path: Path, projection_owner: str) -> None:
    """依赖：两条既有源投影路径和真实FileMutationLock。输入：持有guard的库及同名用户资料。输出：源副本与本批覆盖完整、源锁guard不复制。实现：真实锁内复制，控制区YAML保留，其他位置同名文件不全局屏蔽。"""
    from novel_rag.composition import _projected_library as graph_projection
    from novel_rag.importers.helpers import _projected_library as importer_projection
    from novel_rag.mutations.locks import FileMutationLock

    root = make_library(tmp_path)
    document = put_document(root, "source", "原始资料。")
    control = root / ".novel-rag"
    stage = control / "staging" / ".mutation-projection"
    stage.mkdir(parents=True)
    (control / "retained.yaml").write_text("source: unchanged\n", encoding="utf-8")
    staged_file = stage / "replacement.yaml"
    staged_file.write_text("replacement bytes\n", encoding="utf-8")
    nested = root / "stories" / "demo" / ".novel-rag"
    nested.mkdir()
    (nested / "mutation.lock.guard").write_text("user material", encoding="utf-8")
    (root / "mutation.lock.guard").write_text("root material", encoding="utf-8")
    projected = graph_projection if projection_owner == "composition" else importer_projection

    with FileMutationLock(control / "mutation.lock"):
        result = projected(SimpleNamespace(root=stage, staged_files={document: staged_file}), root)

    assert not (result / ".novel-rag" / "mutation.lock.guard").exists()
    assert (result / ".novel-rag" / "retained.yaml").read_bytes() == (control / "retained.yaml").read_bytes()
    assert (result / document.relative_to(root)).read_bytes() == staged_file.read_bytes()
    assert (result / nested.relative_to(root) / "mutation.lock.guard").read_text(encoding="utf-8") == "user material"
    assert (result / "mutation.lock.guard").read_text(encoding="utf-8") == "root material"


@pytest.mark.parametrize("projection_owner", ["composition", "importers"])
@pytest.mark.parametrize("lease_phase", ["before_owner", "owned", "before_release"])
def test_source_projection_excludes_reserved_writer_guard_through_lease_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, projection_owner: str, lease_phase: str,
) -> None:
    """依赖：两条源投影路径、真实DraftStore租约与OS guard。输入：库内workspace及取得/持有/释放窗口。输出：投影完整且排除保留名.writer.lock.guard。实现：在owner写前或删除后确定性交错复制，普通YAML和其他guard文件逐字保留。"""
    from novel_rag.composition import _projected_library as graph_projection
    from novel_rag.importers.helpers import _projected_library as importer_projection

    root = make_library(tmp_path)
    put_document(root, "source", "原始资料。")
    workspace = root / ".novel-rag" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "ordinary.yaml").write_text("source: keep\n", encoding="utf-8")
    (workspace / "ordinary.guard").write_text("ordinary guard suffix", encoding="utf-8")
    stage = root / ".novel-rag" / "staging" / ".mutation-writer-projection"
    stage.mkdir(parents=True)
    store = DraftStore(workspace)
    lease = store.writer_lease()
    projector = graph_projection if projection_owner == "composition" else importer_projection
    results = []

    def project_during_lease():
        """依赖：真实lease与投影器闭包。输入：当前租约生命周期。输出：记录投影路径。实现：验证guard已持有及owner窗口后复制整个库，不模拟复制异常。"""
        assert lease._guard._descriptor is not None
        assert lease.path.exists() == (lease_phase == "owned")
        results.append(projector(SimpleNamespace(root=stage, staged_files={}), root))

    if lease_phase == "before_owner":
        create_owner = lease._create_owner

        def create_after_projection(payload):
            """依赖：原owner创建和投影闭包。输入：owner字节。输出：原创建结果。实现：guard取得后、元数据出现前插入真实复制。"""
            project_during_lease()
            return create_owner(payload)

        monkeypatch.setattr(lease, "_create_owner", create_after_projection)
    elif lease_phase == "before_release":
        release_guard = lease._release_guard

        def release_after_projection():
            """依赖：原guard释放和投影闭包。输入：无。输出：原释放结果。实现：元数据删除后、guard解锁前复制，异常也释放真实OS资源。"""
            try:
                project_during_lease()
            finally:
                release_guard()

        monkeypatch.setattr(lease, "_release_guard", release_after_projection)

    with lease:
        if lease_phase == "owned":
            project_during_lease()

    assert len(results) == 1
    projected_workspace = results[0] / workspace.relative_to(root)
    assert not (projected_workspace / ".writer.lock.guard").exists()
    for filename in ("ordinary.yaml", "ordinary.guard"):
        assert (projected_workspace / filename).read_bytes() == (workspace / filename).read_bytes()
    assert (workspace / ".writer.lock.guard").is_file()
    assert not lease.path.exists()


@pytest.mark.parametrize("view", ["full", "live"])
def test_workspace_application_snapshot_matches_http_without_changing_legacy_fields(tmp_path: Path, view: str) -> None:
    """依赖：真实应用服务/ASGI/原库夹具。输入：已保存harness稿与full/live视图。输出：服务和HTTP同形同值。实现：先暖读来源效力，再比较公开JSON及旧记忆投影边界。"""
    import asyncio
    from novel_rag.web.app import create_app
    from test_web_workspace import _asgi_client, _token_headers

    root = make_library(tmp_path)
    app = create_app(root, tmp_path / "workspace", tmp_path / "no-model.json")
    service = app.state.service
    run_id = service.prepare(GraphKey("demo", "main"), "write", "原路线", "当前请求")
    saved = service.save_author_draft(run_id, 0, "作者正文。")
    service.workspace_snapshot(run_id, view=view)

    async def scenario():
        """依赖：实际ASGI生命周期。输入：闭包app/视图。输出：JSON兼容断言。实现：令HTTP只转发查询，全文/热视图分别核对。"""
        async with _asgi_client(app) as client:
            expected = service.workspace_snapshot(run_id, view=view)
            response = await client.get(f"/api/v1/runs/{run_id}?view={view}", headers=_token_headers(app.state.token))
            assert response.status_code == 200, response.text
            assert response.json() == expected
            assert expected["draft_ref"] == saved.as_dict()
            assert expected["suggested_coordinate"] == {"volume": 1, "chapter": 1, "scene": 1}
            assert ("memory_state" in expected) == (view == "full")
            assert ("tool_results" in expected) == (view == "full")

    asyncio.run(scenario())


def test_application_target_projection_inherits_adoption_but_new_chapter_has_no_target(tmp_path: Path) -> None:
    """依赖：真实RunService采用/父DraftRef/来源。输入：已采用父稿、同稿续写与正式后章。输出：父目标CAS继承、下一章无旧目标hash。实现：经公共操作发布真实History并比较full/live投影。"""
    service = _author_service(tmp_path)
    coordinate = {"volume": 1, "chapter": 2, "scene": 3}
    parent_id = service.prepare(GraphKey("demo", "main"), "write", "路线", "父稿", target_coordinate=coordinate)
    saved = service.save_author_draft(parent_id, 0, "父稿正文。")
    adopted = service.adopt_draft(parent_id, saved.draft_revision, None, coordinate, "parent-adopt")
    assert adopted["adopted"] is True
    parent = service.workspace_snapshot(parent_id, view="live")
    child_id = service.feedback(parent["session_id"], parent_id, "write", "接写")
    for view in ("live", "full"):
        child = service.workspace_snapshot(child_id, view=view)
        assert child["suggested_coordinate"] == child["adoption_target_coordinate"] == coordinate
        assert child["adoption_target_source_hash"] == parent["adoption_target_source_hash"]
        assert child["adoption_target_source_hash"] is not None
    next_id = service.prepare(GraphKey("demo", "main"), "write", "路线", "新章")
    next_view = service.workspace_snapshot(next_id, view="live")
    assert next_view["suggested_coordinate"] == {"volume": 1, "chapter": 2, "scene": 4}
    assert next_view["adoption_target_coordinate"] is None
    assert next_view["adoption_target_source_hash"] is None


def test_application_live_observation_never_loads_recalls_or_writes(tmp_path: Path, monkeypatch) -> None:
    """依赖：真实Store热快照/stat提示。输入：取消后的run和上次观察提示。输出：live/身份/观察均无冷读召回写入，无变化不取快照。实现：禁止副作用入口，实际stat继续工作。"""
    service = _author_service(tmp_path)
    run_id = service.prepare(GraphKey("demo", "main"), "write", "路线", "请求")
    service.cancel(run_id)

    def forbidden(*args, **kwargs):
        """依赖：断言。输入：意外冷读/召回/写调用。输出：失败。实现：验证应用封装保持原热观察边界。"""
        raise AssertionError("application observation performed a cold read, recall or write")

    monkeypatch.setattr(service.store, "load", forbidden)
    monkeypatch.setattr(service.store, "write", forbidden)
    monkeypatch.setattr(service.memory, "recall", forbidden)
    live = service.workspace_snapshot(run_id, view="live")
    assert "memory_state" not in live
    assert service.run_info(run_id)["launchable"] is False
    observed = service.observe(run_id, after=999)
    assert observed["terminal"] is True
    assert observed["snapshot"]["events_reset"] is True
    assert "suggested_coordinate" not in observed["snapshot"]
    monkeypatch.setattr(service.store, "snapshot", forbidden)
    assert service.observe(run_id, after=999, revision=observed["revision"]) is None


def test_application_run_result_keeps_cli_fields_and_error_without_recall(tmp_path: Path, monkeypatch) -> None:
    """依赖：原作者保存/取消/公开快照。输入：保存稿、非完成状态及调用异常。输出：原CLI五字段与优先错误。实现：禁止recall并核对正常状态错误和失败恢复结果。"""
    service = _author_service(tmp_path)
    run_id = service.prepare(GraphKey("demo", "main"), "write", "路线", "请求")
    saved = service.save_author_draft(run_id, 0, "保存的正文。")
    service.cancel(run_id)

    def forbidden(*args, **kwargs):
        """依赖：断言。输入：意外recall。输出：失败。实现：CLI读取结果不得引入工作台full的召回。"""
        raise AssertionError("CLI result recalled memory")

    monkeypatch.setattr(service.memory, "recall", forbidden)
    result = service.run_result(run_id)
    assert result == {"run_id": run_id, "status": "cancelled", "draft_ref": saved.as_dict(),
                      "draft_text": "保存的正文。", "error": {"code": "cancelled", "message": "写作任务状态：cancelled"}}
    failure = RuntimeError("output interrupted")
    assert service.run_result(run_id, error=failure)["error"] is failure
    stored = {"code": "source_invalid", "message": "保存的错误"}
    service.store.set_status(run_id, "failed", stored)
    assert service.run_result(run_id, error=failure)["error"] == stored


def test_application_bootstrap_harness_has_no_config_dependency_and_profiles_are_safe(tmp_path: Path, monkeypatch) -> None:
    """依赖：原ModelConfigStore/应用启动与宿主工具查询。输入：有效含密钥配置与损坏配置。输出：脱敏选择、能力降级、harness身份/五工具仍可读。实现：损坏后同时走HTTP及服务，保持旧响应字段。"""
    import asyncio
    from novel_rag.model_config import ModelConfigStore
    from novel_rag.web.app import create_app
    from test_web_workspace import _asgi_client, _token_headers

    root = make_library(tmp_path)
    config_path = tmp_path / "models.json"
    config = ModelConfigStore(config_path)
    config.set_profile("fixture", base_url="http://127.0.0.1:1/v1", model="fixture-model", mode="chat",
                       api_key="private-bootstrap-secret", no_auth=False)
    app = create_app(root, tmp_path / "workspace", config_path)
    service = app.state.service
    settings = service.workspace_bootstrap()
    assert settings["profiles"] == [{"name": "fixture", "model": "fixture-model", "mode": "chat"}]
    assert "private-bootstrap-secret" not in str(settings)
    run_id = service.prepare(GraphKey("demo", "main"), "write", "路线", "请求")
    config_path.write_text("{broken", encoding="utf-8")
    assert service.workspace_bootstrap()["model_configuration_error"]["code"] == "capability"

    def forbidden(*args, **kwargs):
        """依赖：断言。输入：意外模型配置读取。输出：失败。实现：harness查询独立于任何profile读取。"""
        raise AssertionError("harness read model configuration")

    monkeypatch.setattr(service.config, "list_profiles", forbidden)
    monkeypatch.setattr(service.config, "get", forbidden)
    assert len(service.harness_tools(run_id)["tools"]) == 5
    assert service.workspace_bootstrap(harness=True) == {"library_root": str(root.resolve()),
                                                        "workspace_root": str((tmp_path / "workspace").resolve())}

    async def scenario():
        """依赖：真实ASGI边界。输入：闭包harness和损坏配置。输出：原握手/工具JSON。实现：使用实际token访问，两条路由都不触碰配置。"""
        async with _asgi_client(app) as client:
            response = await client.get("/api/v1/harness/bootstrap")
            assert response.status_code == 200, response.text
            assert response.json() == {"token": app.state.token, **service.workspace_bootstrap(harness=True)}
            tools = await client.get(f"/api/v1/runs/{run_id}/harness-tools", headers=_token_headers(app.state.token))
            assert tools.status_code == 200, tools.text
            assert tools.json() == service.harness_tools(run_id)

    asyncio.run(scenario())
