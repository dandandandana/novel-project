"""验证领域失效决策与唯一Store原子提交之间的兼容边界。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from novel_rag.generation.store import DraftStore, StoreConflict
from novel_rag.generation.types import MemoryCommit
from novel_rag.identity import GraphKey
from novel_rag.memory.effects import draft_selection_effect
from novel_rag.memory.service import MemoryService
from novel_rag.service import load_story_sources
from test_adoption_v3 import _environment, _remember_state
from test_run_store import _binding
from writer_fixtures import make_library, put_document


@pytest.mark.parametrize("selected,invalidated", [("原文。后续。", ()), ("改写。", ("first",)), ("前移。原文。", ("first",))])
def test_draft_selection_effect_preserves_inputs_and_same_start_prefix(selected, invalidated):
    """依赖：纯draft_selection_effect/deepcopy。输入：追加、改写及中段搬移。输出：仅失效旧覆盖前缀且输入不变。实现：核对领域结果并修改返回签名验证无共享可变引用。"""
    drafts = {"first": {"text": "原文。"}, "uncovered": {"text": "未选正文。"}}
    batches = [{"source_refs": [{"kind": "draft", "checkpoint_id": key}
                                for key in ("first", "uncovered", "foreign")]}]
    signature = {"draft:first": "valid", "publications": {"source": ["original"]}}
    original = deepcopy((drafts, batches, signature))

    effect = draft_selection_effect("原文。", selected, drafts, batches, signature)

    assert effect.invalidated_checkpoints == invalidated
    assert effect.effect_signature["draft:first"] == ("stale" if invalidated else "valid")
    effect.effect_signature["publications"]["source"].append("local")
    assert (drafts, batches, signature) == original


@pytest.mark.parametrize("change", ["unchanged", "changed", "missing"])
def test_first_signature_counts_real_baseline_change_once(tmp_path: Path, monkeypatch, change):
    """依赖：真实来源/MemoryService/Store。输入：无旧签名run及原源不变、改写或删除。输出：首次正确计数、相同签名不写。实现：保存真实基线后改变来源并以新Store复读。"""
    root = make_library(tmp_path)
    source = put_document(root, "baseline", "原文。", category="canon")
    reference = load_story_sources(root, GraphKey("demo", "main")).source_refs["baseline"]
    store = DraftStore(tmp_path / "workspace")
    run = store.create(replace(_binding(story_id="demo"), baseline_source_refs=(reference,)), "路线", "请求")
    if change == "changed":
        put_document(root, "baseline", "新版本正文。", category="canon")
    elif change == "missing":
        source.unlink()
    memory = MemoryService(root, store)

    first = memory.current_snapshot(run["run_id"])["run"]

    assert first["memory_revision"] == int(change != "unchanged")
    assert "memory_effect_signature" in first
    write = Mock(wraps=store.write)
    monkeypatch.setattr(store, "write", write)
    assert memory.current_snapshot(run["run_id"])["run"] == first
    assert write.call_count == 0
    assert DraftStore(store.root).load(run["run_id"]) == first


def test_reconcile_rejects_selected_draft_change_without_memory_change(tmp_path: Path, monkeypatch):
    """依赖：实际Store双CAS。输入：记忆版本相同但选中稿已变的旧快照。输出：冲突且不写签名。实现：先捕获空稿，再保存新稿后提交旧观察。"""
    store = DraftStore(tmp_path)
    original = store.create(_binding(), "路线", "请求")
    store.save(original["run_id"], 0, "作者新稿。")
    current = store.load(original["run_id"])
    assert current["memory_revision"] == original["memory_revision"]
    write = Mock(wraps=store.write)
    monkeypatch.setattr(store, "write", write)

    with pytest.raises(StoreConflict, match="memory_snapshot已过期"):
        store.reconcile_memory_effect(original["run_id"], expected_memory_revision=original["memory_revision"],
                                      expected_draft_ref=original["draft_ref"], signature={"old": True},
                                      initially_invalid=False)

    assert write.call_count == 0
    assert store.load(original["run_id"]) == current


@pytest.mark.parametrize("legacy_signature", [False, True])
def test_saved_invalidation_and_later_reconcile_share_one_revision(tmp_path: Path, legacy_signature):
    """依赖：真实remember/save/recall。输入：有无签名的已有批次、追加及改写。输出：追加不增版本、改写仅增一次。实现：沿同一save入口验证旧run首次签名排除已计数本地失效。"""
    _, _, store, memory, run, ref = _environment(tmp_path)
    _remember_state(store, memory, run, ref)
    if legacy_signature:
        with store.lock:
            current = store.load(run["run_id"])
            current.pop("memory_effect_signature")
            store.write(current)
    store.save(run["run_id"], 1, store.load(run["run_id"])["draft_text"] + "追加。")
    assert store.load(run["run_id"])["memory_revision"] == 1

    store.save(run["run_id"], 2, "完全改写正文。")

    current = store.load(run["run_id"])
    assert current["memory_revision"] == 2
    assert current["memory_local_invalidations"] == [ref["checkpoint_id"]]
    assert memory.current_snapshot(run["run_id"])["run"]["memory_revision"] == 2
    assert memory.current_snapshot(run["run_id"])["run"]["memory_revision"] == 2


def test_explicit_commit_keeps_signature_outside_batch_and_preserves_builder_values(tmp_path: Path):
    """依赖：MemoryCommit/原Store幂等表。输入：独立批次、回执、签名。输出：单次持久提交且builder输入不变。实现：重启以原身份恢复，并核批次无内部效力字段。"""
    store = DraftStore(tmp_path)
    run = store.create(_binding(), "路线", "请求")
    commit = MemoryCommit({"batch_id": "batch-1", "source_refs": [], "memory_revision": 0},
                          {"accepted_record_ids": ["record-1"], "memory_revision": 0},
                          {"publications": {"source": ["original"]}})
    original = deepcopy(commit)
    builder = Mock(return_value=commit)
    arguments = {"expected_memory_revision": 0}

    result = store.commit_memory(run["run_id"], "memory-op", arguments, builder)
    restarted = DraftStore(store.root)

    assert restarted.commit_memory(run["run_id"], "memory-op", arguments, builder) == result
    assert builder.call_count == 1
    assert commit == original
    current = restarted.load(run["run_id"])
    assert current["memory_revision"] == result["memory_revision"] == 1
    assert current["memory_effect_signature"] == commit.effect_signature
    assert set(current["memory_batches"][0]) == {"batch_id", "source_refs", "memory_revision"}
    commit.effect_signature["publications"]["source"].append("after")
    assert restarted.load(run["run_id"])["memory_effect_signature"] == original.effect_signature


def test_legacy_pair_commit_leaves_existing_signature_unchanged(tmp_path: Path):
    """依赖：原二元组builder/命名协调入口。输入：旧builder与已有签名。输出：仍走单提交路径且不覆盖签名。实现：先初始化签名，再用旧调用形状提交一批。"""
    store = DraftStore(tmp_path)
    run = store.create(_binding(), "路线", "请求")
    store.reconcile_memory_effect(run["run_id"], expected_memory_revision=0, expected_draft_ref=None,
                                  signature={"publications": {}}, initially_invalid=False)
    builder = Mock(return_value=({"batch_id": "batch-legacy"}, {"accepted_record_ids": []}))

    store.commit_memory(run["run_id"], "legacy-op", {"expected_memory_revision": 0}, builder)

    current = store.load(run["run_id"])
    assert current["memory_effect_signature"] == {"publications": {}}
    assert current["memory_revision"] == current["memory_batches"][0]["memory_revision"] == 1


def test_legacy_pair_signature_keeps_disk_shape_and_replays_without_rebuilding(tmp_path: Path):
    """依赖：旧二元组builder/真实磁盘/原幂等表。输入：带内部签名的旧批次。输出：签名只存run、原值不变、重启原ID不重建。实现：比较真实JSON及回放前后字节，核一次构建和版本。"""
    store = DraftStore(tmp_path)
    run = store.create(_binding(), "路线", "请求")
    signature = {"publications": {"source": ["original"]}, "draft:checkpoint-original": "valid"}
    legacy = ({"batch_id": "batch-legacy-signature", "source_refs": [], "_effect_signature": signature},
              {"accepted_record_ids": ["record-legacy"]})
    original = deepcopy(legacy)
    builder = Mock(return_value=legacy)
    arguments = {"expected_memory_revision": 0}

    result = store.commit_memory(run["run_id"], "legacy-signature-op", arguments, builder)
    run_path = store._run_path(run["run_id"])
    committed_bytes = run_path.read_bytes()
    persisted = json.loads(committed_bytes)
    restarted = DraftStore(store.root)

    assert persisted["memory_effect_signature"] == signature
    assert persisted["memory_batches"] == [{"batch_id": "batch-legacy-signature", "source_refs": [], "memory_revision": 1}]
    assert restarted.commit_memory(run["run_id"], "legacy-signature-op", arguments, builder) == result
    assert run_path.read_bytes() == committed_bytes
    assert restarted.load(run["run_id"])["memory_revision"] == result["memory_revision"] == 1
    assert builder.call_count == 1
    assert legacy == original
    signature["publications"]["source"].append("changed-after-return")
    assert restarted.load(run["run_id"])["memory_effect_signature"] == original[0]["_effect_signature"]


def test_adoption_receipt_preserves_newer_run_fields(tmp_path: Path):
    """依赖：命名采用回执/原Store草稿和取消。输入：旧采用结果与更新后的run。输出：回执写入不覆盖新草稿或取消标志。实现：只传run身份和回执，以新实例核持久结果。"""
    store = DraftStore(tmp_path)
    old = store.create(_binding(), "路线", "请求")
    receipt = {"adopted": True, "memory_state": "memory_pending", "draft_ref": old["draft_ref"]}
    latest = store.save(old["run_id"], 0, "采用等待期间的作者新稿。")
    with store.lock:
        current = store.load(old["run_id"])
        current["cancel_requested"] = True
        store.write(current)

    store.record_adoption_receipt(old["run_id"], receipt)

    restored = DraftStore(store.root).load(old["run_id"])
    assert restored == dict(current, adoption=receipt)
    assert restored["draft_ref"] == latest.as_dict()
    assert restored["cancel_requested"] is True
    receipt["memory_state"] = "changed-after-return"
    assert store.load(old["run_id"])["adoption"]["memory_state"] == "memory_pending"
