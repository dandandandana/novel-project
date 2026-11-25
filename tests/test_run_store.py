from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest

import novel_rag.generation.store as run_store_module
from novel_rag.generation.store import DraftStore, StoreConflict
from novel_rag.generation.types import DraftRef, NarrativeCursor, RunBinding
from novel_rag.identity import GraphKey
from novel_rag.mutations.types import fingerprint_bytes


def _binding(
    *,
    story_id: str = "store-story",
    timeline_id: str = "main",
    base_ref: DraftRef | None = None,
    branch: str = "branch",
    selected_parent_checkpoint: str | None = None,
    initial_memory_revision: int = 0,
) -> RunBinding:
    """构造隔离测试使用的固定绑定。

    依赖：GraphKey、NarrativeCursor 与纯值 RunBinding。
    输入：故事/分支身份及可选父检查点。
    输出：不含外部读取的运行绑定。
    实现：固定 before 游标并显式传入父引用。
    """
    return RunBinding(
        scope=GraphKey(story_id, timeline_id),
        task_kind="scene",
        narrative_cursor=NarrativeCursor("before"),
        base_ref=base_ref,
        draft_branch=branch,
        selected_parent_checkpoint=selected_parent_checkpoint,
        initial_memory_revision=initial_memory_revision,
    )


def test_same_revision_drafts_from_different_runs_have_unique_refs_and_real_hashes(
    tmp_path: Path,
) -> None:
    """验证不同运行的同修订草稿引用唯一且指向真实 UTF-8 字节。

    依赖：DraftStore、公共指纹函数和 pytest 临时目录。
    输入：同一 scope 下两个独立运行及相同正文。
    输出：修订号可相同，引用身份唯一且 hash 与正文文件一致。
    实现：分别保存、读取 DraftRef，再检查各自实际文件字节。
    """
    store = DraftStore(tmp_path)
    first = store.create(_binding(), "提纲一", "请求一")
    second = store.create(_binding(), "提纲二", "请求二")
    text = "第一行\n雪与星空\n"

    first_ref = store.save(first["run_id"], 0, text)
    second_ref = store.save(second["run_id"], 0, text)

    assert first_ref.draft_revision == second_ref.draft_revision == 1
    assert first_ref.draft_document_id != second_ref.draft_document_id
    assert first_ref.checkpoint_id != second_ref.checkpoint_id
    for run, ref in ((first, first_ref), (second, second_ref)):
        resolved_run, resolved_text = store.resolve_draft(ref.as_dict())
        body_path = (
            tmp_path
            / run["binding"]["scope"]["story_id"]
            / run["binding"]["scope"]["timeline_id"]
            / "runs"
            / run["run_id"]
            / "drafts"
            / "1.txt"
        )
        body_bytes = body_path.read_bytes()
        assert resolved_run["run_id"] == run["run_id"]
        assert resolved_text == text
        assert body_bytes == text.encode("utf-8")
        assert ref.content_hash == fingerprint_bytes(body_bytes)


def test_partial_receive_survives_new_store_without_advancing_draft_revision(
    tmp_path: Path,
) -> None:
    """验证接收 partial 可恢复，但不会变成已保存草稿。

    依赖：DraftStore 的 receive/received 与真实磁盘快照。
    输入：新运行及一个未完成 turn 的累计文本。
    输出：新 Store 可读取 partial，draft revision 仍为零。
    实现：接收文本后丢弃旧实例并从新实例读取权威文件。
    """
    store = DraftStore(tmp_path)
    run = store.create(_binding(), "路线", "请求")
    partial = "已经收到的开头："

    store.receive(run["run_id"], "turn-partial", partial, complete=False)
    restored = DraftStore(tmp_path)

    received = restored.received(run["run_id"])
    current = restored.load(run["run_id"])
    assert received["text"] == partial
    assert received["complete"] is False
    assert received["persisted_bytes"] == len(partial.encode("utf-8"))
    assert current["draft_revision"] == 0
    assert current["draft_ref"] is None
    assert current["draft_text"] == ""


@pytest.mark.parametrize("retry_suffix", ["", "再继续。"])
def test_receive_republishes_only_missing_text_after_snapshot_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, retry_suffix: str,
) -> None:
    """依赖：DraftStore 与原子 JSON 写故障注入。输入：当前 turn 的待发布前缀与重试文本。

    输出：重启后仅补发原事件未覆盖的新文本，旧草稿和已发布事件保持。
    实现：中断 received 保存后的 run 替换，再重试相同或更长文本并核对恢复游标。
    """
    store = DraftStore(tmp_path)
    run_id = store.create(_binding(), "路线", "请求")["run_id"]
    draft = store.save(run_id, 0, "作者草稿")
    store.set_status(run_id, "running")
    turn_id = "turn-current"
    store.receive(run_id, turn_id, "已经发布。")
    prior = store.snapshot(run_id, view="live")
    pending = "已经发布。待发布。"

    with monkeypatch.context() as patch:
        real_write = run_store_module.atomic_write_json

        def fail_event_write(path: Path, payload: dict) -> None:
            """依赖：原 JSON writer。输入：替换路径及数据。
            输出：有新事件的 run 替换失败。实现：其余写入仍真实落盘。
            """
            if path.name == "run.json" and len(payload["events"]) > prior["event_seq"]:
                raise OSError("文本发布失败")
            real_write(path, payload)

        patch.setattr(run_store_module, "atomic_write_json", fail_event_write)
        with pytest.raises(OSError, match="文本发布失败"):
            store.receive(run_id, turn_id, pending)

    reopened = DraftStore(tmp_path)
    assert reopened.recover() == [run_id]
    assert reopened.received(run_id)["text"] == pending
    assert reopened.load(run_id)["received_published_chars"] == len("已经发布。")
    assert reopened.snapshot(run_id, view="live", after=prior["event_seq"])["events"] == []

    final_text = pending + retry_suffix
    reopened.receive(run_id, turn_id, final_text)
    reopened.receive(run_id, turn_id, final_text)
    after = DraftStore(tmp_path).snapshot(run_id, view="live", after=prior["event_seq"])
    assert after["received_text"] == final_text
    assert after["draft_revision"] == 1
    assert after["draft_ref"] == draft.as_dict()
    assert after["draft_text"] == "作者草稿"
    assert after["event_seq"] == prior["event_seq"] + 1
    assert after["events"] == [{"run_id": run_id, "seq": after["event_seq"], "type": "text_delta",
                                "payload": {"turn_id": turn_id, "text": "待发布。" + retry_suffix}}]


@pytest.mark.parametrize("layout", ["current", "legacy-inline", "legacy-payload"])
def test_restart_shows_unpublished_next_turn_without_replaying_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layout: str,
) -> None:
    """依赖：原turn转录及接收文件。输入：已发布一轮、下一轮首段落盘后发布失败。

    输出：重启投影下一轮持久前缀，原事件与草稿保持，下一轮未接收时仍显示上一轮。
    实现：跨三种转录布局注入原子替换失败，重开核对full/live与实际权威快照。
    """
    store = DraftStore(tmp_path)
    run_id = store.create(_binding(), "路线", "请求")["run_id"]
    store.set_status(run_id, "running")
    first_turn, second_turn = "turn-first", "turn-second"
    store.prepare_turn(run_id, first_turn, "attempt-first", {})
    store.commit_turn(run_id, first_turn, {"text": "上一轮正文。"})
    manifest = {} if layout == "legacy-inline" else {"context": "长" * 4000}
    store.prepare_turn(run_id, second_turn, "attempt-second", manifest)
    run_path = next(tmp_path.glob(f"*/*/runs/{run_id}/run.json"))
    if layout != "current":
        legacy = store.load(run_id)
        legacy.pop("last_turn_id", None)
        store.write(legacy)
    before = store.snapshot(run_id, view="live")
    assert before["received_text"] == "上一轮正文。"
    assert before["received_turn_id"] == first_turn

    with monkeypatch.context() as patch:
        real_write = run_store_module.atomic_write_json

        def fail_publication(path: Path, payload: dict) -> None:
            """依赖：原JSON writer。输入：路径与快照。输出：run替换失败。实现：收到正文仍真实保存。"""
            if path.name == "run.json":
                raise OSError("文本发布失败")
            real_write(path, payload)

        patch.setattr(run_store_module, "atomic_write_json", fail_publication)
        with pytest.raises(OSError, match="文本发布失败"):
            store.receive(run_id, second_turn, "下一轮的持久前缀。")

    turn_root = run_path.parent / "turns"
    newest_mtime = (turn_root / second_turn / "received.json").stat().st_mtime + 10
    os.utime(turn_root / first_turn / "received.json", (newest_mtime, newest_mtime))
    reopened = DraftStore(tmp_path)
    assert reopened.recover() == [run_id]
    interrupted = run_path.read_bytes()
    full = reopened.snapshot(run_id)
    assert full["events"] == before["events"]
    assert full["received_turn_id"] == second_turn
    assert full["received_text"] == "下一轮的持久前缀。"
    assert full["draft_revision"] == 0
    assert full["draft_ref"] is None
    assert "last_turn_id" not in full
    assert reopened.public_turn_text(run_id, second_turn) == full["received_text"]
    if layout == "current":
        patch = Mock(side_effect=AssertionError("当前布局热读不应读外置 turn"))
        monkeypatch.setattr(reopened, "_read_payload", patch)
    live = reopened.snapshot(run_id, view="live", after=before["event_seq"])
    assert live["status"] == "interrupted"
    assert live["received_turn_id"] == second_turn
    assert live["received_text"] == full["received_text"]
    assert live["event_seq"] == before["event_seq"] and live["events"] == []
    assert "last_turn_id" not in live
    assert reopened.received(run_id)["complete"] is False
    assert reopened.received(run_id, first_turn)["text"] == "上一轮正文。"
    assert run_path.read_bytes() == interrupted

    reopened.receive(run_id, second_turn, live["received_text"])
    published = reopened.snapshot(run_id, view="live", after=before["event_seq"])
    assert published["event_seq"] == before["event_seq"] + 1
    assert published["events"] == [
        {"run_id": run_id, "seq": published["event_seq"], "type": "text_delta",
         "payload": {"turn_id": second_turn, "text": live["received_text"]}},
    ]


def test_receive_updates_event_and_turn_reference_once_with_legacy_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """依赖：旧 run 事件形状和原子 writer。输入：旧前缀、新 turn 及重复的完整回执。

    输出：每段只替换一次含指针和对应事件的 run，完成标记保留且不重复发布。
    实现：从未含位置的原事件恢复前缀，用 writer 检查写入顺序和各次落盘形状。
    """
    store = DraftStore(tmp_path)
    run_id = store.create(_binding(), "路线", "请求")["run_id"]
    old_turn = "turn-legacy"
    store.receive(run_id, old_turn, "旧前缀。")
    legacy = store.load(run_id)
    legacy.pop("received_published_chars", None)
    store.write(legacy)
    real_write = run_store_module.atomic_write_json
    writes = []

    def record_write(path: Path, payload: dict) -> None:
        """依赖：原 JSON writer。输入：路径及数据。输出：真实写入。
        实现：写入成功后记录路径与该次数据供断言。
        """
        real_write(path, payload)
        writes.append((path.name, payload))

    monkeypatch.setattr(run_store_module, "atomic_write_json", record_write)
    reopened = DraftStore(tmp_path)
    reopened.receive(run_id, old_turn, "旧前缀。最新。")
    new_turn = "turn-new"
    reopened.receive(run_id, new_turn, "下一轮。")
    reopened.receive(run_id, new_turn, "下一轮。", complete=True)
    reopened.receive(run_id, new_turn, "下一轮。", complete=True)
    reopened.receive(run_id, new_turn, "下一轮。")
    with pytest.raises(StoreConflict, match="增量前缀不一致"):
        reopened.receive(run_id, new_turn, "前缀已变。")
    with pytest.raises(StoreConflict, match="完整turn不能追加增量"):
        reopened.receive(run_id, new_turn, "下一轮。追加。")
    assert [name for name, _ in writes] == ["received.json", "run.json", "received.json", "run.json", "received.json"]
    for (_, state), turn_id, before, expected in (
        (writes[1], old_turn, "旧前缀。", "最新。"), (writes[3], new_turn, "", "下一轮。"),
    ):
        assert state["received_turn_id"] == turn_id
        assert state["received_published_chars"] == len(before + expected)
        assert state["events"][-1]["payload"] == {"turn_id": turn_id, "text": expected}
        assert state["events"][-1]["seq"] == len(state["events"])
    result = DraftStore(tmp_path)
    assert result.received(run_id, old_turn)["text"] == "旧前缀。最新。"
    assert result.received(run_id) == {"turn_id": new_turn, "text": "下一轮。", "complete": True,
                                       "persisted_bytes": len("下一轮。".encode("utf-8"))}
    assert "received_published_chars" not in result.snapshot(run_id)
    assert "received_published_chars" not in result.snapshot(run_id, view="live")


def test_failed_run_snapshot_leaves_old_draft_visible_and_new_body_orphaned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证正文先落盘而 run 快照失败时旧修订仍为唯一可见成功。

    依赖：真实正文文件、DraftStore 与原子 JSON 写入口。
    输入：已有草稿及仅对下一次 run.json 写入失败的故障点。
    输出：失败时旧引用、revision、事件保持，同调用重试只提交一次正文及事件。
    实现：注入一次快照写失败，跨 Store 检查磁盘后重试并核对成功的替换内容。
    """
    store = DraftStore(tmp_path)
    run = store.create(_binding(), "路线", "请求")
    run_id = run["run_id"]
    old_text = "旧正文\n"
    old_ref = store.save(run_id, 0, old_text).as_dict()
    old_events = store.load(run_id)["events"]
    new_text = "孤立新正文\n"
    arguments = {"expected_revision": 1, "text": new_text}
    call_id = "call-save-retry"
    real_atomic_write_json = run_store_module.atomic_write_json
    attempted_runs = []

    def fail_next_run_snapshot(path: Path, payload: dict) -> None:
        """只让指定 Store run 快照的下一次原子替换失败。

        依赖：原 atomic_write_json 和 pytest monkeypatch。
        输入：目标路径与待写 JSON 映射。
        输出：run.json 首次调用抛 OSError，其余调用正常委托。
        实现：保留原 writer，仅在目标名匹配时触发一次故障。
        """
        if path.name == "run.json":
            attempted_runs.append(payload)
            if len(attempted_runs) == 1:
                raise OSError("injected run snapshot failure")
        real_atomic_write_json(path, payload)

    monkeypatch.setattr(run_store_module, "atomic_write_json", fail_next_run_snapshot)
    with pytest.raises(OSError, match="injected run snapshot failure"):
        store.save(run_id, 1, new_text, call_id=call_id, arguments=arguments)

    restored = DraftStore(tmp_path)
    current = restored.load(run_id)
    resolved_run, resolved_old = restored.resolve_draft(old_ref)
    run_dir = (
        tmp_path
        / run["binding"]["scope"]["story_id"]
        / run["binding"]["scope"]["timeline_id"]
        / "runs"
        / run_id
    )
    orphan = run_dir / "drafts" / "2.txt"
    assert current["draft_revision"] == 1
    assert current["draft_ref"] == old_ref
    assert set(current["drafts"]) == {old_ref["checkpoint_id"]}
    assert current["events"] == old_events
    assert call_id not in current["tool_commits"]
    assert resolved_run["run_id"] == run_id
    assert resolved_old == old_text
    assert orphan.read_bytes() == new_text.encode("utf-8")

    new_ref = restored.save(run_id, 1, new_text, call_id=call_id, arguments=arguments)
    assert restored.save(run_id, 1, new_text, call_id=call_id, arguments=arguments) == new_ref
    assert len(attempted_runs) == 2
    committed = attempted_runs[-1]
    assert committed == restored.load(run_id)
    assert committed["draft_revision"] == 2
    assert committed["events"] == old_events + [
        {"run_id": run_id, "seq": len(old_events) + 1, "type": "draft_saved",
         "payload": {"draft_ref": new_ref.as_dict(), "draft_revision": 2, "draft_text": new_text}},
    ]


def test_memory_commit_recovers_lost_reply_and_rejects_reuse_or_stale_cas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 memory commit 的持久幂等结果和 CAS 边界。

    依赖：DraftStore、StoreConflict、monkeypatch 与磁盘 run 快照。
    输入：纯 builder、固定 call ID、参数和 expected memory revision。
    输出：丢失回执可恢复；同 ID 改参及新调用旧 CAS 均拒绝且不写入。
    实现：首次丢弃返回值，重建 Store 后重放并比较权威字节。
    """
    store = DraftStore(tmp_path)
    run = store.create(_binding(), "路线", "请求")
    run_id = run["run_id"]
    arguments = {
        "expected_memory_revision": 0,
        "candidates": [{"candidate_id": "candidate-1", "value": "雪"}],
    }

    def build(_run_snapshot: dict) -> tuple[dict, dict]:
        """为 memory commit 纯构造一批记录和可恢复结果。

        依赖：输入快照仅供读取。
        输入：互斥区内的独立 run 映射。
        输出：不含副作用的 batch/result 两个新映射。
        实现：返回固定批次身份与候选到记录的稳定映射。
        """
        return (
            {"batch_id": "batch-1", "records": [{"record_id": "record-1"}]},
            {"batch_id": "batch-1", "local_refs": {"candidate-1": "record-1"}},
        )

    store.commit_memory(run_id, "call-1", arguments, build)
    restarted = DraftStore(tmp_path)
    recovered_result = restarted.commit_memory(run_id, "call-1", arguments, build)
    committed = restarted.load(run_id)
    run_path = (
        tmp_path
        / run["binding"]["scope"]["story_id"]
        / run["binding"]["scope"]["timeline_id"]
        / "runs"
        / run_id
        / "run.json"
    )
    committed_bytes = run_path.read_bytes()

    assert recovered_result == committed["tool_commits"]["call-1"]["result"]
    assert recovered_result["batch_id"] == "batch-1"
    assert recovered_result["memory_revision"] == 1
    assert committed["memory_revision"] == 1
    assert len(committed["memory_batches"]) == 1
    assert committed["memory_batches"][0]["batch_id"] == "batch-1"
    atomic_json_writer = Mock(wraps=run_store_module.atomic_write_json)
    monkeypatch.setattr(run_store_module, "atomic_write_json", atomic_json_writer)

    changed_arguments = {
        **arguments,
        "candidates": [{"candidate_id": "candidate-1", "value": "改参"}],
    }
    with pytest.raises(StoreConflict, match="同调用ID参数不同"):
        restarted.commit_memory(run_id, "call-1", changed_arguments, build)
    stale_arguments = {
        "expected_memory_revision": 0,
        "candidates": [{"candidate_id": "candidate-2", "value": "旧版本"}],
    }
    with pytest.raises(StoreConflict, match="记忆版本已变化"):
        restarted.commit_memory(run_id, "call-2", stale_arguments, build)
    assert run_path.read_bytes() == committed_bytes
    assert atomic_json_writer.call_count == 0
    assert len(restarted.load(run_id)["memory_batches"]) == 1


def test_accepts_prefix_tracks_parent_branch_and_rejects_rewrite_or_sibling(
    tmp_path: Path,
) -> None:
    """验证前缀采用按实际分支继承且改写、兄弟引用失效。

    依赖：DraftStore 的 DraftRef 解析和 accepts_prefix。
    输入：父稿、继承父检查点的子稿与兄弟稿。
    输出：追加正文接受父前缀，改写正文和兄弟来源均拒绝。
    实现：以真实保存检查点建立分支，再按所选正文校验。
    """
    store = DraftStore(tmp_path)
    parent = store.create(_binding(branch="parent"), "路线", "请求")
    parent_text = "共同开头\n父稿末尾\n"
    parent_ref = store.save(parent["run_id"], 0, parent_text)
    parent_ref_dict = parent_ref.as_dict()

    child = store.create(
        _binding(
            base_ref=parent_ref,
            branch="child",
            selected_parent_checkpoint=parent_ref.checkpoint_id,
        ),
        "路线",
        "继续",
    )
    child_text = parent_text + "子分支新增\n"
    child_ref = store.save(child["run_id"], 0, child_text)
    child_snapshot = store.load(child["run_id"])

    assert store.accepts_prefix(child_snapshot, parent_ref_dict, selected_text=child_text)
    assert not store.accepts_prefix(
        child_snapshot,
        parent_ref_dict,
        selected_text="改写共同开头\n父稿末尾\n子分支新增\n",
    )

    sibling = store.create(
        _binding(
            base_ref=parent_ref,
            branch="sibling",
            selected_parent_checkpoint=parent_ref.checkpoint_id,
        ),
        "路线",
        "另一个方向",
    )
    sibling_text = parent_text + "兄弟分支新增\n"
    store.save(sibling["run_id"], 0, sibling_text)
    sibling_snapshot = store.load(sibling["run_id"])
    assert not store.accepts_prefix(
        sibling_snapshot,
        child_ref.as_dict(),
        selected_text=sibling_text,
    )


def test_recover_marks_running_run_interrupted_without_changing_turns(
    tmp_path: Path,
) -> None:
    """验证启动恢复只标记 interrupted，不重放未完成请求。

    依赖：DraftStore 的状态快照与 recover。
    输入：持久化为 running 的运行。
    输出：新 Store 将其标为 interrupted，turn/event 内容不被重发。
    实现：跨实例恢复后比较状态、turns 和已有事件。
    """
    store = DraftStore(tmp_path)
    run = store.create(_binding(), "路线", "请求")
    running = store.set_status(run["run_id"], "running")
    prior_turns = running["turns"]
    prior_events = running["events"]

    recovered = DraftStore(tmp_path)
    assert recovered.recover() == [run["run_id"]]
    restored = DraftStore(tmp_path)
    current = restored.load(run["run_id"])

    assert current["status"] == "interrupted"
    assert current["turns"] == prior_turns
    assert current["events"] == prior_events
    assert restored.recover() == []


def test_protected_input_survives_removal_of_run_directory(tmp_path: Path) -> None:
    """验证保护后的作者输入可脱离原 run 按原 hash 回读。

    依赖：DraftStore 输入引用、atomic_write_bytes 与临时目录边界。
    输入：含 Unicode 的 outline 输入和固定 AuthorInputRef。
    输出：移除 run 目录后新 Store 仍返回相同文本及指纹。
    实现：保护输入、核对删除路径位于 tmp_path，再跨实例回读。
    """
    root = tmp_path.resolve()
    store = DraftStore(root)
    binding = _binding()
    outline = "原始提纲：月下雪景\n"
    run = store.create(binding, outline, "作者请求\n")
    ref = run["binding"]["input_snapshot_refs"][0]
    run_dir = (
        root
        / run["binding"]["scope"]["story_id"]
        / run["binding"]["scope"]["timeline_id"]
        / "runs"
        / run["run_id"]
    ).resolve()

    store.protect_input(run, ref)
    protected_hash = ref["snapshot_hash"].split(":", 1)[1]
    protected_files = list(root.rglob(f"{protected_hash}.txt"))
    assert len(protected_files) == 1
    assert protected_files[0].read_bytes() == outline.encode("utf-8")
    assert run_dir != root
    assert root in run_dir.parents
    shutil.rmtree(run_dir)

    restored = DraftStore(root)
    recovered_text = restored.input_text(ref)
    assert recovered_text == outline
    assert fingerprint_bytes(recovered_text.encode("utf-8")) == ref["snapshot_hash"]
