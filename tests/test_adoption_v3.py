from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
import yaml

import novel_rag.mutations.coordinator as coordinator_module
import novel_rag.writeback.adopt as adoption_module
from novel_rag.documents import read_yaml_snapshot
from novel_rag.generation.store import DraftStore, StoreConflict
from novel_rag.generation.types import NarrativeCursor, RunBinding
from novel_rag.identity import GraphKey, StoryCoordinate
from novel_rag.memory.service import MemoryService
from novel_rag.mutations.types import fingerprint_bytes, fingerprint_file
from novel_rag.service import load_story_sources
from novel_rag.writeback.adopt import AdoptionService
from writer_fixtures import make_library, put_document, write_yaml


_SCOPE = GraphKey("demo", "main")
_COORDINATE = StoryCoordinate(1, 1, 1)


def _new_run(
    store: DraftStore,
    text: str,
    *,
    outline: str = "作者路线：保留信物去向。",
    task_kind: str = "scene",
    base_ref: Any | None = None,
    coordinate: StoryCoordinate = _COORDINATE,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """依赖：DraftStore/RunBinding。输入：正文、任务来源与坐标。输出：真实运行快照和DraftRef。实现：保存固定作者输入后写入完整草稿检查点。"""

    run = store.create(
        RunBinding(
            scope=_SCOPE,
            task_kind=task_kind,
            narrative_cursor=NarrativeCursor("after"),
            base_ref=base_ref,
            draft_branch="main",
            target_coordinate=coordinate,
        ),
        outline,
        "本轮请求：按路线写作。",
    )
    ref = store.save(run["run_id"], 0, text).as_dict()
    return run, ref


def _environment(
    tmp_path: Path,
    text: str = "正文：甲交出刻有雾灯的信物。\n",
    *,
    outline: str = "作者路线：保留信物去向。",
) -> tuple[
    Path, Path, DraftStore, MemoryService, dict[str, Any], dict[str, Any]
]:
    """依赖：writer_fixtures/DraftStore/MemoryService。输入：隔离目录和正文。输出：真实库、工作区、服务、运行及稿源。实现：建立注册作品并保存作者输入和UTF-8草稿。"""

    root = make_library(tmp_path)
    workspace = tmp_path / "workspace"
    store = DraftStore(workspace)
    memory = MemoryService(root, store)
    run, draft_ref = _new_run(store, text, outline=outline)
    return root, workspace, store, memory, run, draft_ref


def _target_path(root: Path, coordinate: StoryCoordinate = _COORDINATE) -> Path:
    """依赖：AdoptionService规范History布局。输入：库根与完整坐标。输出：新History目标路径。实现：按source owner使用的两位卷章场目录拼接。"""

    return (
        root
        / "stories"
        / _SCOPE.story_id
        / "timelines"
        / _SCOPE.timeline_id
        / "history"
        / f"volume-{coordinate.volume:02d}"
        / f"chapter-{coordinate.chapter:02d}"
        / f"scene-{coordinate.scene:02d}.yaml"
    )


def _journal_path(store: DraftStore, operation_id: str) -> Path:
    """依赖：DraftStore工作区和公共字节指纹。输入：工作区及操作ID。输出：durable intent路径。实现：复用AdoptionService的安全哈希文件名。"""

    key = fingerprint_bytes(operation_id.encode("utf-8")).split(":", 1)[1]
    return store.root / _SCOPE.story_id / _SCOPE.timeline_id / "adoptions" / f"{key}.json"


def _adopt(
    root: Path,
    store: DraftStore,
    memory: MemoryService,
    run: dict[str, Any],
    draft_ref: dict[str, Any],
    operation_id: str,
    *,
    expected_source_hash: str | None = None,
    coordinate: StoryCoordinate = _COORDINATE,
) -> dict[str, Any]:
    """依赖：AdoptionService真实source coordinator。输入：运行、所选DraftRef、源CAS、坐标及操作ID。输出：持久采用回执。实现：走正式factory、文件锁、校验与原子单源替换。"""

    return AdoptionService(root, store, memory).adopt(
        run["run_id"],
        draft_ref["draft_revision"],
        expected_source_hash,
        coordinate,
        operation_id,
    )


def _remember_state(
    store: DraftStore,
    memory: MemoryService,
    run: dict[str, Any],
    draft_ref: dict[str, Any],
) -> dict[str, Any]:
    """依赖：MemoryService真实remember与DraftStore。输入：run及实际DraftRef。输出：规范状态批次回执。实现：用host分配local_ref并保存一个World Set变化。"""

    update = {
        "state_changes": [
            {
                "op": "set",
                "local_ref": "custody",
                "entry": {
                    "domain": "World",
                    "kind": "holder",
                    "value": "雾灯信物由乙保管。",
                    "lifetime": "carry",
                },
            }
        ]
    }
    return memory.remember(
        run["run_id"],
        "remember-state-" + run["run_id"],
        draft_ref=draft_ref,
        expected_memory_revision=0,
        update=update,
    )


def _remember_author_note(
    store: DraftStore,
    memory: MemoryService,
    run: dict[str, Any],
) -> dict[str, Any]:
    """依赖：run固定输入引用与MemoryService。输入：真实运行。输出：作者输入笔记批次回执。实现：以该run的outline引用提交允许的note记录。"""

    input_ref = next(
        ref for ref in run["binding"]["input_snapshot_refs"] if ref["input_slot"] == "outline"
    )
    update = {
        "notes": [
            {
                "op": "create",
                "local_ref": "outline-note",
                "record": {
                    "record_kind": "note",
                    "payload": {"text": "作者计划：雾灯信物要留给后续场景。"},
                    "source_refs": [input_ref],
                },
            }
        ]
    }
    memory.remember(
        run["run_id"],
        "remember-note-" + run["run_id"],
        draft_ref=None,
        expected_memory_revision=0,
        update=update,
    )
    return input_ref


@pytest.mark.parametrize("damage", ["delete", "corrupt", "author_note"])
def test_published_clear_survives_container_loss_restart_and_new_run(tmp_path: Path, damage: str) -> None:
    """依赖：真实采用fixture/SourceCorpus/新Store。输入：两章Set/Clear及丢失容器方式。输出：旧Set不复活、控制缺口可见、早游标仍有旧值。实现：实际保存/采用后破坏Clear摘要并重建生产读取链。"""
    root, workspace, store, memory, first, ref = _environment(tmp_path)
    state_id = _remember_state(store, memory, first, ref)["accepted_record_ids"][0]
    _adopt(root, store, memory, first, ref, "set-first")
    coordinate = StoryCoordinate(1, 2, 1)
    second, second_ref = _new_run(store, "正文：乙归还信物。", coordinate=coordinate)
    memory.remember(second["run_id"], "clear-second", draft_ref=second_ref, expected_memory_revision=0,
                    update={"state_changes": [{"op": "clear", "entry_id": state_id}]})
    assert _adopt(root, store, memory, second, second_ref, "adopt-clear", coordinate=coordinate)["memory_state"] == "complete"
    reader, _ = _new_run(store, "第三章", coordinate=StoryCoordinate(1, 3, 1))
    assert memory.recall(reader["run_id"])["state_view"]["entries"] == []
    projection = next(doc.path for doc in load_story_sources(root, _SCOPE).documents
                      if doc.metadata.get("memory_kind") == "memory_projection" and
                      any(change.get("op") == "clear" for batch in doc.metadata["memory_batches"]
                          for change in batch["update"].get("state_changes", [])))
    if damage == "delete":
        projection.unlink()
    elif damage == "corrupt":
        projection.write_text("[bad yaml", encoding="utf-8")
    else:
        payload = yaml.safe_load(projection.read_text(encoding="utf-8"))
        payload["metadata"].update(memory_kind="author_note", ownership="user")
        write_yaml(projection, payload)
    restarted = DraftStore(workspace)
    fresh_memory = MemoryService(root, restarted)
    from novel_rag.composition import build_writer_service
    service = build_writer_service(root, workspace, tmp_path / "unused-model-config.json")
    new_id = service.prepare(_SCOPE, "write", "路线", "继续")
    for packet in (memory.recall(reader["run_id"]), fresh_memory.recall(reader["run_id"]), service.memory.recall(new_id)):
        assert packet["state_view"]["entries"] == []
        assert state_id in packet["state_view"]["invalidated_keys"]
        assert packet["gaps"] and packet["state_view"]["coverage"] != "bound"
    for original in (first, second):
        directory = workspace / "demo" / "main" / "runs" / original["run_id"]
        assert directory.resolve().is_relative_to(workspace.resolve())
        shutil.rmtree(directory)
    cleaned_id = service.prepare(_SCOPE, "write", "清理后", "继续")
    cleaned = service.memory.recall(cleaned_id)
    assert cleaned["state_view"]["entries"] == []
    assert state_id in cleaned["state_view"]["invalidated_keys"]
    early = restarted.create(RunBinding(scope=_SCOPE, task_kind="revise", narrative_cursor=NarrativeCursor("before", coordinate),
                                      base_ref=None, draft_branch="early"), "", "")
    assert any(entry["entry_id"] == state_id for entry in fresh_memory.recall(early["run_id"])["state_view"]["entries"])


def test_late_earlier_checkpoint_is_replayed_before_later_value_and_published(tmp_path: Path) -> None:
    """依赖：真实Store/remember/采用fixture。输入：cp1借出、cp2归还、迟到cp1修正。输出：草稿及正式新run都保持cp2值且覆盖不退。实现：使用host同ID更新并采用较晚真实检查点。"""
    root, workspace, store, memory, run, first_ref = _environment(tmp_path, "甲交出信物。")
    state_id = _remember_state(store, memory, run, first_ref)["accepted_record_ids"][0]
    second_ref = store.save(run["run_id"], 1, "甲交出信物。乙归还信物。").as_dict()
    entry = {"domain": "World", "kind": "holder", "value": "信物已归还甲。", "lifetime": "carry"}
    memory.remember(run["run_id"], "later-value", draft_ref=second_ref, expected_memory_revision=1,
                    update={"state_changes": [{"op": "set", "entry_id": state_id, "entry": entry}]})
    memory.remember(run["run_id"], "earlier-correction", draft_ref=first_ref, expected_memory_revision=2,
                    update={"state_changes": [{"op": "set", "entry_id": state_id,
                             "entry": {**entry, "value": "甲暂借信物给乙。"}}]})
    before = memory.recall(run["run_id"])
    assert before["state_view"]["entries"][0]["value"] == "信物已归还甲。"
    assert before["state_view"]["recorded_through"]["checkpoint_id"] == second_ref["checkpoint_id"]
    assert _adopt(root, store, memory, run, second_ref, "publish-late-order")["memory_state"] == "complete"
    restarted = DraftStore(workspace)
    new, _ = _new_run(restarted, "下章", coordinate=StoryCoordinate(1, 2, 1))
    formal = MemoryService(root, restarted).recall(new["run_id"])
    assert formal["state_view"]["entries"][0]["value"] == "信物已归还甲。"


def _write_external_history(path: Path, content: str = "外部作者另存的正文。\n") -> None:
    """依赖：writer_fixtures.write_yaml。输入：History路径与正文。输出：真实并发源文件。实现：写入完整且可由source-only factory校验的metadata。"""

    write_yaml(
        path,
        {
            "metadata": {
                "document_id": "external-history",
                "story_id": _SCOPE.story_id,
                "timeline_id": _SCOPE.timeline_id,
                "document_type": "history",
                "title": "外部History",
                "status": "canon",
                "version": "1",
                "source_revision": 1,
                "volume": 1,
                "chapter": 1,
                "scene": 1,
            },
            "content": content,
        },
    )


def test_new_chapter_double_click_with_same_operation_is_idempotent(tmp_path: Path) -> None:
    """依赖：真实Store、MemoryService、source-only factory与线程池。输入：同一新章和同一operation_id的双提交。输出：同一采用结果和唯一History。实现：并发触发同一服务并核验实际YAML字节及源指纹。"""

    root, _, store, memory, run, draft_ref = _environment(tmp_path)
    service = AdoptionService(root, store, memory)
    args = (run["run_id"], draft_ref["draft_revision"], None, _COORDINATE, "adopt-double-click")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.adopt, *args)
        second = pool.submit(service.adopt, *args)
        results = [first.result(), second.result()]

    target = _target_path(root)
    snapshot = read_yaml_snapshot(target)
    assert results[0] == results[1]
    assert results[0]["adopted"] is True
    assert results[0]["source_revision"] == 1
    assert snapshot.data["metadata"]["adoption_id"] == "adopt-double-click"
    assert snapshot.data["content"] == store.resolve_draft(draft_ref)[1]
    assert snapshot.source_hash == results[0]["source_hash"] == fingerprint_file(target)


def test_same_operation_id_with_different_parameters_is_rejected(tmp_path: Path) -> None:
    """依赖：AdoptionService durable intent與Store CAS。输入：已采用operation_id和不同草稿修订。输出：参数冲突且正式文件不变。实现：保存真实第二版正文后复用ID触发argument-hash校验。"""

    root, _, store, memory, run, first_ref = _environment(tmp_path)
    first = _adopt(root, store, memory, run, first_ref, "adopt-parameter-conflict")
    path = _target_path(root)
    before = path.read_bytes()
    second_ref = store.save(run["run_id"], 1, "第二版正文：改了雾灯结尾。\n").as_dict()

    with pytest.raises(StoreConflict, match="同采用ID参数不同"):
        _adopt(root, store, memory, run, second_ref, "adopt-parameter-conflict")

    assert path.read_bytes() == before
    assert fingerprint_file(path) == first["source_hash"]


def test_history_metadata_revision_change_conflicts_with_captured_source_hash(tmp_path: Path) -> None:
    """依赖：writer_fixtures、SourceCorpus与真实AdoptionService。输入：绑定旧History后仅改source_revision元数据。输出：revision conflict且新源保留。实现：使用真实文件hash证明metadata改动也触发CAS。"""

    root = make_library(tmp_path)
    target = put_document(
        root,
        "history-baseline",
        "历史正文不变。\n",
        extra_metadata={"source_revision": 7},
    )
    baseline = load_story_sources(root, _SCOPE).source_refs["history-baseline"]
    store = DraftStore(tmp_path / "workspace")
    memory = MemoryService(root, store)
    run, draft_ref = _new_run(store, "修订正文：雾灯转交乙。\n", task_kind="revise", base_ref=baseline)
    changed_source = yaml.safe_load(target.read_text(encoding="utf-8"))
    changed_source["metadata"]["source_revision"] = 8
    write_yaml(target, changed_source)
    changed_hash = fingerprint_file(target)

    with pytest.raises(StoreConflict, match="正式源已改变"):
        _adopt(
            root,
            store,
            memory,
            run,
            draft_ref,
            "adopt-stale-history",
            expected_source_hash=baseline.source_hash,
        )

    assert changed_hash != baseline.source_hash
    assert fingerprint_file(target) == changed_hash
    assert yaml.safe_load(target.read_text(encoding="utf-8"))["metadata"]["source_revision"] == 8
    assert not _journal_path(store, "adopt-stale-history").exists()


def test_history_run_baseline_conflicts_even_if_caller_supplies_current_file_hash(tmp_path: Path) -> None:
    """依赖：RunBinding固定DocumentRef与真实source CAS。输入：绑定旧History后源revision改变且请求携带新hash。输出：旧run仍被拒绝。实现：验证采用不会把用户提供的新指纹当成基线迁移授权。"""

    root = make_library(tmp_path)
    target = put_document(
        root,
        "history-bound-source",
        "旧版本正文。\n",
        extra_metadata={"source_revision": 3},
    )
    baseline = load_story_sources(root, _SCOPE).source_refs["history-bound-source"]
    store = DraftStore(tmp_path / "workspace")
    memory = MemoryService(root, store)
    run, draft_ref = _new_run(
        store,
        "基于旧资料写出的修订。\n",
        task_kind="revise",
        base_ref=baseline,
    )
    changed_source = yaml.safe_load(target.read_text(encoding="utf-8"))
    changed_source["metadata"]["source_revision"] = 4
    write_yaml(target, changed_source)
    current_hash = fingerprint_file(target)
    before = target.read_bytes()

    with pytest.raises(StoreConflict, match="基线|revision_conflict"):
        _adopt(
            root,
            store,
            memory,
            run,
            draft_ref,
            "adopt-stale-run-baseline",
            expected_source_hash=current_hash,
        )

    assert current_hash != baseline.source_hash
    assert target.read_bytes() == before


def test_legacy_history_without_document_id_gets_stable_identity_and_exact_backup(tmp_path: Path) -> None:
    """依赖：source snapshots、DraftStore备份区与真实AdoptionService。输入：缺document_id且source_revision为6的History。输出：稳定ID、revision 7和原始字节备份。实现：按同次SourceCorpus引用修订后逐字节核验backup。"""

    root = make_library(tmp_path)
    target = root / "stories" / "demo" / "timelines" / "main" / "history" / "legacy-scene.yaml"
    write_yaml(
        target,
        {
            "metadata": {
                "story_id": "demo",
                "timeline_id": "main",
                "document_type": "history",
                "title": "旧资料身份",
                "status": "canon",
                "version": "6",
                "source_revision": 6,
                "volume": 1,
                "chapter": 1,
                "scene": 1,
            },
            "text": "完整旧正文：留存原始字节。\n",
        },
    )
    old_bytes = target.read_bytes()
    corpus = load_story_sources(root, _SCOPE)
    old_document = next(document for document in corpus.documents if document.path == target)
    old_ref = corpus.source_refs[old_document.document_id]
    store = DraftStore(tmp_path / "workspace")
    memory = MemoryService(root, store)
    run, draft_ref = _new_run(
        store,
        "续写正文：旧资料的雾灯仍在。\n",
        task_kind="revise",
        base_ref=old_ref,
    )

    result = _adopt(
        root,
        store,
        memory,
        run,
        draft_ref,
        "adopt-legacy-id",
        expected_source_hash=old_ref.source_hash,
    )

    current = read_yaml_snapshot(target)
    stable_id = old_ref.document_id
    assert current.data["metadata"]["document_id"] == stable_id
    assert current.data["metadata"]["source_revision"] == 7
    assert result["document_id"] == stable_id
    relative_key = fingerprint_bytes(str(target.relative_to(root)).encode("utf-8")).split(":", 1)[1]
    old_hash = fingerprint_bytes(old_bytes).split(":", 1)[1]
    backup = store.root / "demo" / "main" / "source-versions" / relative_key / f"{old_hash}.yaml"
    assert backup.read_bytes() == old_bytes
    assert fingerprint_file(backup) == old_ref.source_hash
    assert result["source_hash"] == fingerprint_file(target)


def test_source_replaced_before_hook_and_runtime_receipt_failures_recovers_in_new_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """依赖：真实source提交、after-source hook、Store回执与重启恢复。输入：源提交后一次hook及runtime回执故障。输出：新Service从磁盘恢复adopted。实现：hook先真实固化后抛错，随后让真实Store回执失败并重建全部服务。"""

    root, workspace, store, memory, run, draft_ref = _environment(tmp_path)
    real_recover = AdoptionService._recover_intent
    hook_failed = False
    receipt_failed = False
    real_store_write = store.write

    def fail_after_hook_persist(
        service: AdoptionService,
        path: Path,
        intent: dict[str, Any],
    ) -> None:
        """依赖：原intent恢复实现。输入：真实journal与采用事实。输出：一次hook故障。实现：先从正式文件核验并持久化adopted，再注入hook异常。"""

        nonlocal hook_failed
        real_recover(service, path, intent)
        if intent.get("state") == "adopted" and not hook_failed:
            hook_failed = True
            raise RuntimeError("after source hook interrupted")

    def fail_runtime_receipt(snapshot: dict[str, Any]) -> None:
        """依赖：DraftStore真实write。输入：完整run快照。输出：一次外部回执故障。实现：仅在正式源及adopted journal均存在后拒绝run receipt写入。"""

        nonlocal receipt_failed
        if snapshot["run_id"] == run["run_id"] and snapshot.get("adoption") and not receipt_failed:
            receipt_failed = True
            raise OSError("runtime adoption receipt unavailable")
        real_store_write(snapshot)

    monkeypatch.setattr(AdoptionService, "_recover_intent", fail_after_hook_persist)
    monkeypatch.setattr(store, "write", fail_runtime_receipt)

    first = _adopt(root, store, memory, run, draft_ref, "adopt-post-commit-recovery")
    assert first["adopted"] is True
    assert first["receipt_state"] == "pending"

    target = _target_path(root)
    committed_bytes = target.read_bytes()
    committed = read_yaml_snapshot(target)
    assert hook_failed and receipt_failed
    assert committed.data["metadata"]["adoption_id"] == "adopt-post-commit-recovery"
    assert committed.data["content"] == store.resolve_draft(draft_ref)[1]
    assert committed.source_hash == fingerprint_bytes(committed_bytes)
    monkeypatch.setattr(AdoptionService, "_recover_intent", real_recover)

    restored_store = DraftStore(workspace)
    restored_memory = MemoryService(root, restored_store)
    restored = _adopt(
        root,
        restored_store,
        restored_memory,
        restored_store.load(run["run_id"]),
        draft_ref,
        "adopt-post-commit-recovery",
    )

    assert restored["adopted"] is True
    assert restored["document_id"] == committed.data["metadata"]["document_id"]
    assert restored["source_revision"] == committed.data["metadata"]["source_revision"] == 1
    assert restored["source_hash"] == committed.source_hash
    assert read_yaml_snapshot(target).raw_bytes == committed_bytes


def test_retry_old_adoption_receipt_after_new_revision_returns_old_result_without_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """依赖：AdoptionService intent账本和真实History CAS。输入：A提交后回执失败、B修订及重试A。输出：A旧回执且正式源仍为B。实现：只让A的runtime receipt写失败，B以A真实DocumentRef修订后再重试A。"""

    root, _, store, memory, run_a, ref_a = _environment(tmp_path)
    real_store_write = store.write
    failed_a = False

    def fail_a_receipt(snapshot: dict[str, Any]) -> None:
        """依赖：DraftStore真实write。输入：完整run快照。输出：A的一次回执错误。实现：只对A的adoption回执拒绝保存，其他run正常落盘。"""

        nonlocal failed_a
        if snapshot["run_id"] == run_a["run_id"] and snapshot.get("adoption") and not failed_a:
            failed_a = True
            raise OSError("A runtime receipt failed")
        real_store_write(snapshot)

    monkeypatch.setattr(store, "write", fail_a_receipt)
    committed_a = _adopt(root, store, memory, run_a, ref_a, "adoption-A")
    assert committed_a["adopted"] is True
    assert committed_a["receipt_state"] == "pending"
    first_path = _target_path(root)
    first_source = read_yaml_snapshot(first_path)
    result_a = json.loads(_journal_path(store, "adoption-A").read_text(encoding="utf-8"))["result"]
    source_ref_a = load_story_sources(root, _SCOPE).source_refs[result_a["document_id"]]

    run_b, ref_b = _new_run(
        store,
        "B修订正文：雾灯信物交还甲。\n",
        task_kind="revise",
        base_ref=source_ref_a,
    )
    result_b = _adopt(
        root,
        store,
        memory,
        run_b,
        ref_b,
        "adoption-B",
        expected_source_hash=result_a["source_hash"],
    )
    second_source = read_yaml_snapshot(first_path)
    retried_a = _adopt(root, store, memory, run_a, ref_a, "adoption-A")

    assert first_source.data["metadata"]["source_revision"] == 1
    assert result_b["source_revision"] == second_source.data["metadata"]["source_revision"] == 2
    assert second_source.data["metadata"]["adoption_id"] == "adoption-B"
    assert second_source.data["content"] == "B修订正文：雾灯信物交还甲。\n"
    assert retried_a == result_a
    assert read_yaml_snapshot(first_path).raw_bytes == second_source.raw_bytes


def test_prepared_intent_recovers_as_uncommitted_when_source_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """依赖：真实source coordinator与durable intent三分恢复。输入：replace被进程中断的新目标。输出：prepared→uncommitted并可安全重试。实现：只对真实History替换抛KeyboardInterrupt，重建Service后核验磁盘源和journal。"""

    root, workspace, store, memory, run, draft_ref = _environment(tmp_path)
    target = _target_path(root)
    real_replace = coordinator_module.os.replace

    def interrupt_source_replace(source: str | Path, destination: str | Path) -> None:
        """依赖：真实os.replace。输入：staged源与目标。输出：单次进程中断。实现：只在目标为History时中断，其他staging/journal替换委托系统。"""

        if Path(destination).resolve() == target.resolve():
            raise KeyboardInterrupt("process stopped before History replace")
        real_replace(source, destination)

    monkeypatch.setattr(coordinator_module.os, "replace", interrupt_source_replace)
    with pytest.raises(KeyboardInterrupt, match="before History replace"):
        _adopt(root, store, memory, run, draft_ref, "adopt-uncommitted")
    monkeypatch.setattr(coordinator_module.os, "replace", real_replace)

    journal = _journal_path(store, "adopt-uncommitted")
    intent = json.loads(journal.read_text(encoding="utf-8"))
    assert intent["state"] == "prepared"
    assert not target.exists()
    restored_store = DraftStore(workspace)
    restored_service = AdoptionService(root, restored_store, MemoryService(root, restored_store))
    restored_service._recover_intent(journal, intent)
    assert intent["state"] == "uncommitted"
    assert json.loads(journal.read_text(encoding="utf-8"))["state"] == "uncommitted"

    result = _adopt(
        root,
        restored_store,
        restored_service.memory,
        restored_store.load(run["run_id"]),
        draft_ref,
        "adopt-uncommitted",
    )

    assert result["adopted"] is True
    assert read_yaml_snapshot(target).data["metadata"]["adoption_id"] == "adopt-uncommitted"


def test_prepared_intent_conflicts_when_external_source_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """依赖：真实Coordinator replace与intent恢复。输入：prepared缺失源后作者创建同路径History。输出：conflict且作者文件不被覆盖。实现：中断首次replace、保存真实外部YAML，再由新Service恢复并拒绝重放。"""

    root, workspace, store, memory, run, draft_ref = _environment(tmp_path)
    target = _target_path(root)
    real_replace = coordinator_module.os.replace

    def interrupt_source_replace(source: str | Path, destination: str | Path) -> None:
        """依赖：真实os.replace。输入：staged源与目标。输出：单次进程中断。实现：只阻断History替换并委托其余系统替换。"""

        if Path(destination).resolve() == target.resolve():
            raise KeyboardInterrupt("process stopped before History replace")
        real_replace(source, destination)

    monkeypatch.setattr(coordinator_module.os, "replace", interrupt_source_replace)
    with pytest.raises(KeyboardInterrupt, match="before History replace"):
        _adopt(root, store, memory, run, draft_ref, "adopt-external-conflict")
    monkeypatch.setattr(coordinator_module.os, "replace", real_replace)
    external_text = "作者并发保存，保留此版本。\n"
    _write_external_history(target, external_text)
    external_bytes = target.read_bytes()
    restored_store = DraftStore(workspace)
    restored_memory = MemoryService(root, restored_store)

    with pytest.raises(StoreConflict, match="无法恢复，保留intent"):
        _adopt(
            root,
            restored_store,
            restored_memory,
            restored_store.load(run["run_id"]),
            draft_ref,
            "adopt-external-conflict",
        )

    assert json.loads(_journal_path(restored_store, "adopt-external-conflict").read_text(encoding="utf-8"))["state"] == "conflict"
    assert target.read_bytes() == external_bytes


def test_remember_state_experience_and_hook_batches_map_to_history_and_round_trip_without_model(
    tmp_path: Path,
) -> None:
    """依赖：真实MemoryService.remember/AdoptionService/summary读取。输入：一批状态、事件线、经历与伏笔。输出：正式DocumentRef来源的完整summary批次及可召回投影。实现：使用host local_ref分配并验证所有记录映射，不配置或调用模型。"""

    root, _, store, memory, run, draft_ref = _environment(tmp_path)
    update = {
        "state_changes": [
            {
                "op": "set",
                "local_ref": "state-holder",
                "entry": {
                    "domain": "World",
                    "kind": "custody",
                    "value": "雾灯标记显示信物由乙保管。",
                    "lifetime": "carry",
                },
            }
        ],
        "event_lines": [
            {
                "op": "create",
                "local_ref": "line-lantern",
                "record": {"record_kind": "event_line", "payload": {"title": "雾灯交接线"}},
            }
        ],
        "experiences": [
            {
                "op": "create",
                "local_ref": "experience-lantern",
                "record": {"record_kind": "experience", "payload": {"text": "雾灯下交出信物"}},
            }
        ],
        "hooks": [
            {
                "op": "create",
                "local_ref": "hook-lantern",
                "record": {
                    "record_kind": "hook",
                    "payload": {
                        "nature": "unresolved",
                        "text": "雾灯信物上的刻痕来历仍待揭晓。",
                        "explanation_candidates": [],
                    },
                },
            }
        ],
    }
    remembered = memory.remember(
        run["run_id"],
        "remember-mixed-" + run["run_id"],
        draft_ref=draft_ref,
        expected_memory_revision=0,
        update=update,
    )

    result = _adopt(root, store, memory, run, draft_ref, "adopt-mixed-memory")
    summary_path = root / "stories" / "demo" / "timelines" / "main" / "summaries"
    summary_files = list(summary_path.glob("memory-*.yaml"))
    summary = yaml.safe_load(summary_files[0].read_text(encoding="utf-8"))
    stored_batch = summary["metadata"]["memory_batches"][0]
    adopted_ref = summary["metadata"]["source_refs"][0]
    actual_ref = load_story_sources(root, _SCOPE).source_refs[result["document_id"]].as_dict()

    assert result["memory_state"] == "complete"
    assert adopted_ref == actual_ref
    assert stored_batch["source_refs"] == [actual_ref]
    assert stored_batch["update"]["state_changes"][0]["entry"]["source_refs"] == [actual_ref]
    assert stored_batch["update"]["state_changes"][0]["entry_id"] == remembered["local_ref_to_stable_id"]["state-holder"]
    for group, local_ref in (
        ("event_lines", "line-lantern"),
        ("experiences", "experience-lantern"),
        ("hooks", "hook-lantern"),
    ):
        record = stored_batch["update"][group][0]["record"]
        assert record["id"] == remembered["local_ref_to_stable_id"][local_ref]
        assert record["source_refs"] == [actual_ref]
        assert record["narrative_position"] == {
            "kind": "document",
            "endpoint": "after",
            "coordinate": {"volume": 1, "chapter": 1, "scene": 1},
        }

    reader_run, _ = _new_run(store, "只读检索会话。\n", coordinate=StoryCoordinate(1, 1, 2))
    packet = memory.recall(reader_run["run_id"], query="雾灯", available_tokens=10000)
    assert any("雾灯" in entry["value"] for entry in packet["state_view"]["entries"])
    assert packet["event_lines"]
    assert packet["experiences"]
    assert packet["hooks"]


@pytest.mark.parametrize(
    "case,rewritten",
    [
        ("covered-prefix-rewrite", "改写后的开头\n已覆盖中段\n结尾\n"),
        ("covered-middle-moved", "开头\n新插入的内容\n已覆盖中段\n结尾\n"),
    ],
)
def test_rewritten_prefix_or_moved_middle_memory_is_not_published(
    tmp_path: Path,
    case: str,
    rewritten: str,
) -> None:
    """依赖：DraftStore前缀映射及真实采用写入。输入：已remember的正文前缀及重写/搬移后的选择稿。输出：正文采用但不发布旧批次。实现：依次保存检查点、采用新稿并确认候选summary不存在。"""

    original = "开头\n已覆盖中段\n结尾\n"
    root, _, store, memory, run, first_ref = _environment(tmp_path, original)
    _remember_state(store, memory, run, first_ref)
    rewritten_ref = store.save(run["run_id"], 1, rewritten).as_dict()

    result = _adopt(root, store, memory, run, rewritten_ref, "adopt-" + case)
    summaries = root / "stories" / "demo" / "timelines" / "main" / "summaries"

    assert result["adopted"] is True
    assert result["memory_state"] == "complete"
    assert not list(summaries.glob("memory-*.yaml"))
    assert _target_path(root).read_text(encoding="utf-8")


def test_empty_memory_candidates_complete_without_summary_or_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """依赖：AdoptionService empty-candidate path。输入：没有remember批次的实际DraftRef。输出：adopted complete且无派生保存。实现：令summary writer若被调用即失败并检查真实History仍已提交。"""

    root, _, store, memory, run, draft_ref = _environment(tmp_path)

    def unexpected_summary_write(*args: Any, **kwargs: Any) -> None:
        """依赖：SummaryWriter.write_ai测试哨兵。输入：任意writer参数。输出：立即报错。实现：若空候选触发派生保存，则令验收明确失败。"""

        raise AssertionError("空候选不应触发summary发布或模型路径")

    monkeypatch.setattr(adoption_module.SummaryWriter, "write_ai", unexpected_summary_write)
    result = _adopt(root, store, memory, run, draft_ref, "adopt-empty-memory")

    assert result["adopted"] is True
    assert result["memory_state"] == "complete"
    assert read_yaml_snapshot(_target_path(root)).data["metadata"]["adoption_id"] == "adopt-empty-memory"
    assert not (root / "stories" / "demo" / "timelines" / "main" / "summaries").exists()


@pytest.mark.parametrize("failure_stage", ["protect-input", "summary-replace"])
def test_memory_publication_failure_stays_adopted_retries_and_survives_run_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_stage: str,
) -> None:
    """依赖：real source adoption、AuthorInputRef保护、SummaryWriter与MemoryService。输入：protect_input或真实summary替换一次失败。输出：adopted/memory_pending后同ID重试并在run删除后可召回。实现：只故障派生落盘点，最终通过input-versions和formal summary回读核验。"""

    outline = "作者计划：雾灯之后再归还信物。"
    root, workspace, store, memory, run, draft_ref = _environment(
        tmp_path,
        "正文：甲记住作者路线中的雾灯线索。\n",
        outline=outline,
    )
    input_ref = _remember_author_note(store, memory, run)
    operation_id = "adopt-memory-retry-" + failure_stage
    expected_summary = (
        root
        / "stories"
        / "demo"
        / "timelines"
        / "main"
        / "summaries"
        / ("memory-" + fingerprint_bytes(operation_id.encode("utf-8")).split(":", 1)[1] + ".yaml")
    )

    if failure_stage == "protect-input":
        real_protect = store.protect_input
        failed = False

        def fail_protect_once(snapshot: dict[str, Any], ref: dict[str, Any]) -> None:
            """依赖：DraftStore真实输入保护。输入：run快照和AuthorInputRef。输出：一次保存故障后恢复委托。实现：首调抛OSError，后续调用真实保护实现。"""

            nonlocal failed
            if not failed:
                failed = True
                raise OSError("input protection unavailable")
            real_protect(snapshot, ref)

        monkeypatch.setattr(store, "protect_input", fail_protect_once)
    else:
        real_replace = coordinator_module.os.replace
        failed = False

        def fail_summary_replace(source: str | Path, destination: str | Path) -> None:
            """依赖：真实os.replace与SummaryWriter source coordinator。输入：staged文件和目标。输出：一次summary保存故障。实现：只拒绝目标summary原子替换，其余提交全部委托系统。"""

            nonlocal failed
            if Path(destination).resolve() == expected_summary.resolve() and not failed:
                failed = True
                raise OSError("summary save unavailable")
            real_replace(source, destination)

        monkeypatch.setattr(coordinator_module.os, "replace", fail_summary_replace)

    first = _adopt(root, store, memory, run, draft_ref, operation_id)
    target = _target_path(root)
    assert first["adopted"] is True
    assert first["memory_state"] == "memory_pending"
    assert read_yaml_snapshot(target).data["metadata"]["adoption_id"] == operation_id
    assert not expected_summary.exists()

    if failure_stage == "summary-replace":
        monkeypatch.setattr(coordinator_module.os, "replace", real_replace)
    retried = _adopt(root, store, memory, run, draft_ref, operation_id)
    assert retried["adopted"] is True
    assert retried["memory_state"] == "complete"
    assert fingerprint_file(target) == first["source_hash"]
    assert expected_summary.is_file()
    assert store.input_text(input_ref) == outline

    run_directory = workspace / "demo" / "main" / "runs" / run["run_id"]
    assert run_directory.resolve().is_relative_to(workspace.resolve())
    shutil.rmtree(run_directory)
    restored_store = DraftStore(workspace)
    assert restored_store.input_text(input_ref) == outline
    reader, _ = _new_run(restored_store, "检查已发布的雾灯记忆。\n", coordinate=StoryCoordinate(1, 1, 2))
    packet = MemoryService(root, restored_store).recall(
        reader["run_id"],
        query="作者计划：雾灯之后",
        available_tokens=10000,
    )
    assert any(
        note["payload"]["text"] == "作者计划：雾灯信物要留给后续场景。"
        for note in packet["notes"]
    )


def test_revise_history_to_new_coordinate_creates_new_source_and_skips_stale_memory(
    tmp_path: Path,
) -> None:
    """依赖：真实History YAML、DraftStore、MemoryService与AdoptionService。输入：绑定旧History的revise稿、后续新坐标及失效旧候选。输出：新History和未变旧源。实现：同一真实文件CAS创建新目标，并验证不匹配的草稿记忆批次没有发布。"""

    root = make_library(tmp_path)
    original_path = put_document(
        root,
        "history-revise-base",
        "原章节完整正文：雾灯仍在甲手中。\n",
        volume=1,
        chapter=1,
        scene=1,
    )
    original_bytes = original_path.read_bytes()
    original_ref = load_story_sources(root, _SCOPE).source_refs["history-revise-base"]
    new_coordinate = StoryCoordinate(1, 2, 1)
    new_target = _target_path(root, new_coordinate)
    store = DraftStore(tmp_path / "workspace")
    memory = MemoryService(root, store)
    run = store.create(
        RunBinding(
            scope=_SCOPE,
            task_kind="revise",
            narrative_cursor=NarrativeCursor("before", original_ref.coordinate),
            base_ref=original_ref,
            draft_branch="revise-history",
            target_coordinate=new_coordinate,
        ),
        "作者路线：改写后在第二章另起新场景。",
        "保留原章节，选择新坐标保存。",
    )
    old_candidate_ref = store.save(
        run["run_id"], 0, "旧候选：雾灯信物由乙保管。\n"
    ).as_dict()
    _remember_state(store, memory, run, old_candidate_ref)
    selected_ref = store.save(
        run["run_id"], 1, "重写后另起一场：雾灯信物仍由甲保管。\n"
    ).as_dict()

    assert store.accepts_prefix(
        store.load(run["run_id"]), old_candidate_ref,
        selected_text=store.resolve_draft(selected_ref)[1],
    ) is False
    assert len(store.load(run["run_id"])["memory_batches"]) == 1
    assert not new_target.exists()

    result = _adopt(
        root,
        store,
        memory,
        run,
        selected_ref,
        "adopt-revise-new-coordinate",
        expected_source_hash=None,
        coordinate=new_coordinate,
    )

    corpus = load_story_sources(root, _SCOPE)
    new_ref = corpus.source_refs[result["document_id"]]
    summary_root = root / "stories" / "demo" / "timelines" / "main" / "summaries"
    assert result["adopted"] is True
    assert result["source_revision"] == 1
    assert result["document_id"] != original_ref.document_id
    assert new_ref.coordinate == new_coordinate
    assert read_yaml_snapshot(new_target).data["metadata"]["document_id"] == result["document_id"]
    assert original_path.read_bytes() == original_bytes
    assert corpus.source_refs[original_ref.document_id].coordinate == original_ref.coordinate
    assert corpus.source_refs[original_ref.document_id].source_hash == original_ref.source_hash
    assert not summary_root.exists() or not list(summary_root.glob("memory-*.yaml"))


def test_revising_unadopted_write_parent_does_not_target_its_adopted_base(
    tmp_path: Path,
) -> None:
    """依赖：真实已采用History、RunBinding/DraftStore父链及AdoptionService。输入：base为已采用前章的write父稿及其revise子稿。输出：新场景采用且前章身份/字节不变。实现：不采用父稿，直接采用真实子稿并核验目标坐标与正式来源。"""

    root, _, store, memory, first_run, first_ref = _environment(
        tmp_path,
        "已采用前章：甲把雾灯交给乙。\n",
    )
    previous = _adopt(root, store, memory, first_run, first_ref, "adopt-parent-base")
    previous_path = _target_path(root)
    previous_bytes = previous_path.read_bytes()
    previous_ref = load_story_sources(root, _SCOPE).source_refs[previous["document_id"]]
    next_coordinate = StoryCoordinate(1, 2, 1)
    next_target = _target_path(root, next_coordinate)

    parent = store.create(
        RunBinding(
            scope=_SCOPE,
            task_kind="write",
            narrative_cursor=NarrativeCursor("after", previous_ref.coordinate),
            base_ref=previous_ref,
            draft_branch="write-parent",
            target_coordinate=next_coordinate,
        ),
        "作者路线：写下一场。",
        "沿前章进入下一场。",
    )
    parent_ref = store.save(
        parent["run_id"], 0, "未采用父稿：乙拿着雾灯走进下一场。\n"
    ).as_dict()
    child = store.create(
        RunBinding(
            scope=_SCOPE,
            task_kind="revise",
            narrative_cursor=NarrativeCursor("before", next_coordinate),
            base_ref=parent_ref,
            draft_branch="revise-parent",
            target_coordinate=next_coordinate,
        ),
        "作者路线：改写未采用父稿。",
        "重写下一场的正文。",
        parent_run_id=parent["run_id"],
    )
    child_ref = store.save(
        child["run_id"], 0, "子稿重写下一场：乙把雾灯藏进旧书。\n"
    ).as_dict()

    assert parent["binding"]["task_kind"] == "write"
    assert parent["binding"]["base_ref"]["document_id"] == previous_ref.document_id
    assert child["binding"]["task_kind"] == "revise"
    assert child["binding"]["base_ref"] == parent_ref
    assert store.load(parent["run_id"])["adoption"] is None
    assert not next_target.exists()

    result = _adopt(
        root,
        store,
        memory,
        child,
        child_ref,
        "adopt-revise-unadopted-parent",
        expected_source_hash=None,
        coordinate=next_coordinate,
    )

    corpus = load_story_sources(root, _SCOPE)
    assert result["adopted"] is True
    assert result["document_id"] != previous_ref.document_id
    assert corpus.source_refs[previous_ref.document_id].coordinate == previous_ref.coordinate
    assert corpus.source_refs[previous_ref.document_id].source_hash == previous_ref.source_hash
    assert previous_path.read_bytes() == previous_bytes
    assert corpus.source_refs[result["document_id"]].coordinate == next_coordinate
    assert read_yaml_snapshot(next_target).data["metadata"]["document_id"] == result["document_id"]
    assert store.load(parent["run_id"])["adoption"] is None
