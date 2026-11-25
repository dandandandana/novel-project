"""执行模型实际收到的记忆样例，保持来源、整批拒绝与原操作恢复边界。"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from novel_rag.composition import build_writer_service
from novel_rag.generation.store import StoreConflict
from novel_rag.identity import GraphKey
from novel_rag.memory.schema import remember_update_examples, state_entry_schema, validate_memory_update
from novel_rag.std.serialization import json_text
from writer_fixtures import make_library


@pytest.fixture
def example_runtime(tmp_path: Path):
    """依赖：原服务/临时库。输入：隔离目录。输出：真实run与已交付update声明。实现：从dispatcher取样例，保留原Store及MemoryService执行链。"""
    root = make_library(tmp_path)
    service = build_writer_service(root, tmp_path / "workspace", tmp_path / "no-config.json")
    run_id = service.prepare(GraphKey("demo", "main"), "write", "山门关闭、开放，最后拆除旧门。", "按正文变化记忆。")
    definition = next(row for row in service.tool_dispatcher(run_id).definitions() if row["name"] == "remember")
    return service, run_id, definition["parameters"]["properties"]["update"]


def test_delivered_examples_execute_new_state_update_and_clear_with_actual_receipts(example_runtime) -> None:
    """依赖：真实harness/回读/同源样例。输入：工具声明三例和逐次正文。输出：稳定ID、最新来源、解除证据。实现：替换唯一占位ID，CAS和DraftRef逐次取真实回执，不另写成功路径样例。"""
    service, run_id, schema = example_runtime
    examples = schema["examples"]
    assert examples == remember_update_examples()
    assert json_text(examples) in schema["description"]
    bodies = ["守灯人关闭山门。", "交班时，他重新打开山门。", "旧山门随后拆除，不再保留该门的开闭状态。"]
    text, entry_id = "", None
    for ordinal, (example, body) in enumerate(zip(examples, bodies)):
        current = service.harness_context(run_id)
        text += body
        ref = service.harness_tool(run_id, "save_draft", {
            "text": text, "expected_revision": current["draft_revision"],
        }, f"example-save-{ordinal}")
        update = deepcopy(example)
        change = update["state_changes"][0]
        if "entry_id" in change:
            assert entry_id is not None
            change["entry_id"] = entry_id
        assert validate_memory_update(update) == []
        receipt = service.harness_tool(run_id, "remember", {
            "draft_ref": ref, "expected_memory_revision": service.harness_context(run_id)["memory_revision"],
            "update": update,
        }, f"example-remember-{ordinal}")
        assert receipt["memory_revision"] == ordinal + 1
        if entry_id is None:
            entry_id = receipt["local_ref_to_stable_id"][change["local_ref"]]
        else:
            assert receipt["local_ref_to_stable_id"] == {}
        recalled = service.harness_tool(run_id, "recall", {"focus": [entry_id]})
        entries = recalled["state_view"]["entries"]
        if change["op"] == "set":
            stored = next(row for row in entries if row["entry_id"] == entry_id)
            writable = {name: stored[name] for name in state_entry_schema()["properties"] if name in stored}
            assert writable == change["entry"]
            assert stored["source_refs"] == [ref]
            assert {"entry_id", "source_refs", "narrative_position"} <= stored.keys()
        else:
            assert not any(row["entry_id"] == entry_id for row in entries)
            ended = next(row for row in recalled["state_view"]["ended_entries"] if row["entry_id"] == entry_id)
            assert ended["effect"] == "cleared" and ref in ended["source_refs"]


@pytest.mark.parametrize("host_field", ["entry_id", "source_refs", "narrative_position", "scene_id", "holder", "target"])
def test_host_fields_and_null_world_identity_reject_whole_batch(example_runtime, host_field: str) -> None:
    """依赖：原整批校验/实际提交。输入：合法首项与混入host字段或null身份的次项。输出：定位次项、零提交、新ID修正可写。实现：污染交付样例后检查原子性，不放宽已有Schema。"""
    service, run_id, schema = example_runtime
    ref = service.harness_tool(run_id, "save_draft", {"text": "守灯人关闭山门。", "expected_revision": 0}, "save")
    update = deepcopy(schema["examples"][0])
    malformed = deepcopy(update["state_changes"][0])
    malformed["local_ref"] = "second-gate"
    malformed["entry"][host_field] = {
        "entry_id": "not-a-writable-field", "source_refs": [ref],
        "narrative_position": {"kind": "draft", "checkpoint_id": ref["checkpoint_id"]},
        "scene_id": "host-scene", "holder": None, "target": None,
    }[host_field]
    update["state_changes"].append(malformed)
    arguments = {"draft_ref": ref, "expected_memory_revision": 0, "update": update}
    rejected = service.harness_tool(run_id, "remember", arguments, "rejected-example")
    assert rejected["ok"] is False and rejected["memory_revision"] == 0
    assert any("update.state_changes[1].entry" in issue for issue in rejected["error"]["details"]["issues"])
    before_correction = service.store.load(run_id)
    assert before_correction["memory_batches"] == []
    assert "harness:remember:rejected-example" not in before_correction["tool_commits"]
    del malformed["entry"][host_field]
    accepted = service.harness_tool(run_id, "remember", arguments, "corrected-example")
    assert accepted["memory_revision"] == 1
    assert len(accepted["accepted_record_ids"]) == 2
    assert len(service.store.load(run_id)["memory_batches"]) == 1


def test_example_commit_with_lost_reply_recovers_only_original_id_and_parameters(example_runtime, monkeypatch) -> None:
    """依赖：真实原提交/一次丢回执/服务重启。输入：交付新建例及稳定operation_id。输出：同ID改参拒绝、原参恢复且仅一批。实现：真实提交后抛OSError模拟未知结果，重新打开原workspace恢复。"""
    service, run_id, schema = example_runtime
    ref = service.harness_tool(run_id, "save_draft", {"text": "守灯人关闭山门。", "expected_revision": 0}, "save")
    arguments = {"draft_ref": ref, "expected_memory_revision": 0, "update": deepcopy(schema["examples"][0])}
    original_call = service.harness_tool

    def lose_reply(*args, **kwargs):
        """依赖：原harness入口。输入：原工具参数。输出：提交后的模拟I/O错误。实现：保留真实提交点后丢失调用方回执。"""
        original_call(*args, **kwargs)
        raise OSError("模拟提交后回执丢失")

    monkeypatch.setattr(service, "harness_tool", lose_reply)
    with pytest.raises(OSError, match="提交后回执丢失"):
        service.harness_tool(run_id, "remember", arguments, "stable-example")
    monkeypatch.undo()
    changed = deepcopy(arguments)
    changed["update"]["state_changes"][0]["entry"]["value"] = "未经确认的改参。"
    with pytest.raises(StoreConflict, match="同调用ID参数不同"):
        service.harness_tool(run_id, "remember", changed, "stable-example")
    restored = build_writer_service(service.root, service.store.root, service.store.root.parent / "no-config.json")
    recovered = restored.harness_tool(run_id, "remember", arguments, "stable-example")
    assert recovered["memory_revision"] == 1
    assert "gate-status" in recovered["local_ref_to_stable_id"]
    assert len(restored.store.load(run_id)["memory_batches"]) == 1


def test_source_invalid_without_validation_details_does_not_grant_correction(example_runtime) -> None:
    """依赖：真实来源验证与交付说明。输入：正确update但已失效DraftRef。输出：source_invalid无校验细节。实现：保持原拒绝语义并核说明不以ok:false/code授权改参。"""
    service, run_id, schema = example_runtime
    ref = service.harness_tool(run_id, "save_draft", {"text": "守灯人关闭山门。", "expected_revision": 0}, "save")
    ref["content_hash"] = "sha256:" + "0" * 64
    rejected = service.harness_tool(run_id, "remember", {
        "draft_ref": ref, "expected_memory_revision": 0, "update": deepcopy(schema["examples"][0]),
    }, "bad-source")
    assert rejected["ok"] is False and rejected["error"]["code"] == "source_invalid"
    assert "details" not in rejected["error"]
    assert "仅ok:false或source_invalid不足以判断可改参重试" in schema["description"]
    assert "保留原operation_id和完整原参数" in schema["description"]
    assert service.store.load(run_id)["memory_batches"] == []
