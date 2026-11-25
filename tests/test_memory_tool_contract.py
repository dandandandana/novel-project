"""真实模型首轮错误形状的回归；声明和错误帮助模型正确写入，不做文学审核。"""
from __future__ import annotations

from pathlib import Path

import pytest

from novel_rag.composition import build_writer_service
from novel_rag.graph.types import GraphKey
from writer_fixtures import make_library


@pytest.mark.parametrize(("record", "message"), [
    (None, ".record需要"),
    ({"payload": {"text": "已发生"}}, "record_kind必须为小写experience"),
    ({"record_kind": "Experience", "payload": {"text": "已发生"}}, "record_kind必须为小写experience"),
    ({"record_kind": "experience"}, ".payload必须是对象"),
    ({"record_kind": "experience", "payload": {"summary": "已发生"}}, "未知字段['summary']"),
])
def test_live_model_invalid_record_shapes_report_path_without_committing(tmp_path: Path, record, message: str) -> None:
    """依赖：实际RunService/临时库/首轮模型公开调用形状。输入：缺record/payload/kind或summary的经历。输出：精确source_invalid且批次版本不变。实现：真实保存DraftRef后提交坏记录，校验原子拒绝与修正线索。"""
    root = make_library(tmp_path)
    service = build_writer_service(root, tmp_path / "workspace", tmp_path / "no-config.json")
    run_id = service.prepare(GraphKey("demo", "main"), "write", "告别", "写短篇")
    ref = service.harness_tool(run_id, "save_draft", {"text": "梁临把表修好，亲手交给苏青。", "expected_revision": 0}, "save")
    write = {"op": "create", "local_ref": "farewell"}
    if record is not None:
        write["record"] = record
    result = service.harness_tool(run_id, "remember", {"draft_ref": ref, "expected_memory_revision": 0,
        "update": {"experiences": [write]}}, "remember-bad")
    assert result["ok"] is False
    assert result["error"]["code"] == "source_invalid"
    assert "update.experiences[0]" in result["error"]["message"]
    assert message in result["error"]["message"]
    run = service.store.load(run_id)
    assert run["memory_revision"] == 0
    assert run["memory_batches"] == []
    assert "harness:remember:remember-bad" not in run["tool_commits"]
    assert run["draft_ref"] == ref


def test_remember_declares_actual_nested_experience_contract_and_roundtrips(tmp_path: Path) -> None:
    """依赖：唯一ToolDispatcher定义/实际MemoryService。输入：声明中的小写kind/text经历。输出：模型可见结构、实际批次及recall正文。实现：检查原公开合同并真实保存/写入/回读，来源仍是真DraftRef。"""
    service = build_writer_service(make_library(tmp_path), tmp_path / "workspace", tmp_path / "no-config.json")
    run_id = service.prepare(GraphKey("demo", "main"), "write", "怀表归还", "写短篇")
    definition = next(item for item in service.tool_dispatcher(run_id).definitions() if item["name"] == "remember")
    record = definition["parameters"]["properties"]["update"]["properties"]["experiences"]["items"]["properties"]["record"]
    assert record["required"] == ["record_kind", "payload"]
    assert record["properties"]["record_kind"]["enum"] == ["experience"]
    assert set(record["properties"]["payload"]["properties"]) == {"text"}
    assert "summary" not in record["properties"]["payload"]["properties"]
    ref = service.harness_tool(run_id, "save_draft", {"text": "梁临将走动的怀表交给苏青。", "expected_revision": 0}, "save")
    result = service.harness_tool(run_id, "remember", {"draft_ref": ref, "expected_memory_revision": 0,
        "update": {"experiences": [{"op": "create", "local_ref": "watch-return", "record": {
            "record_kind": "experience", "payload": {"text": "怀表已修好，梁临亲手交给苏青。"}}}]}}, "remember")
    packet = service.harness_tool(run_id, "recall", {"query": "怀表 苏青"})
    assert result["memory_revision"] == 1
    batch = service.store.load(run_id)["memory_batches"][0]
    assert batch["update"]["experiences"][0]["record"]["source_refs"] == [ref]
    assert result["accepted_record_ids"]
    assert "怀表已修好" in str(packet)


def test_remember_operation_choices_declare_distinct_required_fields(tmp_path: Path) -> None:
    """依赖：真实工具声明/临时库。输入：remember的状态与经历Schema。输出：各操作互斥的必需字段。实现：检查模型实际收到的新建/更新/解除分支，避免只声明op而容许混用身份。"""
    service = build_writer_service(make_library(tmp_path), tmp_path / "workspace", tmp_path / "no-config.json")
    run_id = service.prepare(GraphKey("demo", "main"), "write", "归还", "写短篇")
    definition = next(item for item in service.tool_dispatcher(run_id).definitions() if item["name"] == "remember")
    groups = definition["parameters"]["properties"]["update"]["properties"]
    for name, expected in [
        ("state_changes", {("op", "local_ref", "entry"), ("op", "entry_id", "entry"), ("op", "entry_id")}),
        ("experiences", {("op", "local_ref", "record"), ("op", "ref", "record"), ("op", "ref")}),
    ]:
        item = groups[name]["items"]
        assert "oneOf" in item
        assert {tuple(branch["required"]) for branch in item["oneOf"]} == expected
        assert all(branch.get("not") for branch in item["oneOf"])


def test_rejected_batch_locates_second_write_and_correction_commits_once(tmp_path: Path) -> None:
    """依赖：真实harness/Store/记忆校验。输入：两条经历中第二条缺text。输出：下标/合法形状、整批不写及修正后一次提交。实现：按拒绝回执修正原差分并回读两个真实记录，保留原DraftRef。"""
    service = build_writer_service(make_library(tmp_path), tmp_path / "workspace", tmp_path / "no-config.json")
    run_id = service.prepare(GraphKey("demo", "main"), "write", "修表与归还", "写短篇")
    ref = service.harness_tool(run_id, "save_draft", {"text": "梁临修好怀表，又将它归还苏青。", "expected_revision": 0}, "save")
    update = {"experiences": [
        {"op": "create", "local_ref": "repair", "record": {"record_kind": "experience", "payload": {"text": "梁临修好怀表。"}}},
        {"op": "create", "local_ref": "return", "record": {"record_kind": "experience", "payload": {"summary": "归还苏青。"}}},
    ]}
    result = service.harness_tool(run_id, "remember", {"draft_ref": ref, "expected_memory_revision": 0, "update": update}, "bad-batch")
    assert result["ok"] is False
    assert "update.experiences[1].record.payload" in result["error"]["message"]
    details = result["error"].get("details", {})
    assert details.get("issues")
    assert len(details.get("operations", [])) == 1
    operation = details["operations"][0]
    assert operation["path"] == "update.experiences[1]"
    assert operation["record_kind"] == "experience"
    assert operation["payload_required"] == ["text"]
    assert operation["alternatives"] == [{"required": ["op", "local_ref", "record"], "forbidden": ["ref"]}]
    rejected = service.store.load(run_id)
    assert rejected["memory_revision"] == 0 and rejected["memory_batches"] == []
    assert "harness:remember:bad-batch" not in rejected["tool_commits"]
    update["experiences"][1]["record"]["payload"] = {"text": "梁临将怀表归还苏青。"}
    arguments = {"draft_ref": ref, "expected_memory_revision": 0, "update": update}
    accepted = service.harness_tool(run_id, "remember", arguments, "corrected-batch")
    assert accepted["memory_revision"] == 1
    assert service.harness_tool(run_id, "remember", arguments, "corrected-batch") == accepted
    run = service.store.load(run_id)
    assert len(run["memory_batches"]) == 1
    assert len(accepted["accepted_record_ids"]) == 2
    packet = service.harness_tool(run_id, "recall", {"query": "怀表"})
    assert {record["payload"]["text"] for record in packet["experiences"]} == {"梁临修好怀表。", "梁临将怀表归还苏青。"}


def test_state_identity_rejection_exposes_read_action_and_keeps_original_slot(tmp_path: Path) -> None:
    """依赖：真实状态/未定身份/原工具入口。输入：将已有belief误改为knowledge。输出：原身份/读取动作、拒绝不推进及合法原槽更新。实现：使用真实host ID回读并只修改value，不放宽身份或自动补知识。"""
    service = build_writer_service(make_library(tmp_path), tmp_path / "workspace", tmp_path / "no-config.json")
    run_id = service.prepare(GraphKey("demo", "main"), "write", "桥面告示", "写短篇")
    ref = service.harness_tool(run_id, "save_draft", {"text": "梁临原以为桥面封闭，随后读到桥面开放的告示。", "expected_revision": 0}, "save")
    initial = service.harness_tool(run_id, "remember", {"draft_ref": ref, "expected_memory_revision": 0, "update": {
        "unresolved_entities": [{"local_ref": "observer", "name": "梁临", "entity_type": "character"}],
        "state_changes": [{"op": "set", "local_ref": "bridge-belief", "entry": {"domain": "CharacterView", "kind": "belief", "holder": {"local_ref": "observer"}, "value": "桥面仍封闭。", "lifetime": "carry"}}],
    }}, "initial")
    entry_id = initial["local_ref_to_stable_id"]["bridge-belief"]
    holder = initial["local_ref_to_stable_id"]["observer"]
    entry = {"domain": "CharacterView", "kind": "knowledge", "holder": holder, "value": "据告示，桥面已开放。", "lifetime": "carry"}
    result = service.harness_tool(run_id, "remember", {"draft_ref": ref, "expected_memory_revision": 1,
        "update": {"state_changes": [{"op": "set", "entry_id": entry_id, "entry": entry}]}}, "wrong-kind")
    assert result["ok"] is False and result["memory_revision"] == 1
    assert "update.state_changes[0].entry" in result["error"]["message"]
    assert "belief" in result["error"]["message"]
    action = result["error"]["details"]["operations"][0]["read_before_update"]
    assert action == {"tool": "recall", "arguments": {"focus": [entry_id]}}
    previous = service.harness_tool(run_id, action["tool"], action["arguments"])
    assert any(row["entry_id"] == entry_id and row["kind"] == "belief" for row in previous["state_view"]["entries"])
    entry["kind"] = "belief"
    accepted = service.harness_tool(run_id, "remember", {"draft_ref": ref, "expected_memory_revision": 1,
        "update": {"state_changes": [{"op": "set", "entry_id": entry_id, "entry": entry}]}}, "correct-kind")
    assert accepted["memory_revision"] == 2
    current = service.harness_tool(run_id, "recall", {"focus": [entry_id]})
    assert any(row["entry_id"] == entry_id and row["value"] == "据告示，桥面已开放。" and row["kind"] == "belief" for row in current["state_view"]["entries"])


@pytest.mark.parametrize("operation", ["update", "retire"])
@pytest.mark.parametrize("identity", ["unknown", "other-kind"])
def test_record_identity_rejection_locates_item_and_preserves_atomic_retry(
    tmp_path: Path, operation: str, identity: str,
) -> None:
    """依赖：真实harness/Store。输入：第二条记录误用未知或另一类型ID。输出：下标/recall动作、整批拒绝与原键恢复。实现：先写真实经历/笔记，再修正ID并验证一次提交。"""
    service = build_writer_service(make_library(tmp_path), tmp_path / "workspace", tmp_path / "no-config.json")
    run_id = service.prepare(GraphKey("demo", "main"), "write", "归还怀表", "按原文记忆")
    ref = service.harness_tool(run_id, "save_draft", {"text": "梁临修好怀表，将它归还苏青。", "expected_revision": 0}, "save")
    record = {"record_kind": "experience", "payload": {"text": "梁临修好怀表。"}}
    seed = service.harness_tool(run_id, "remember", {"draft_ref": ref, "expected_memory_revision": 0, "update": {
        "experiences": [{"op": "create", "local_ref": "repair", "record": record}],
        "notes": [{"op": "create", "local_ref": "note", "record": {"record_kind": "note", "payload": {"text": "怀表登记。"}}}],
    }}, "seed")
    ids = seed["local_ref_to_stable_id"]
    wrong_id = "experience-missing" if identity == "unknown" else ids["note"]
    write = {"op": operation, "ref": {"kind": "experience", "id": wrong_id}}
    if operation == "update":
        write["record"] = record
    update = {"experiences": [{"op": "create", "local_ref": "return", "record": {
        "record_kind": "experience", "payload": {"text": "梁临归还怀表。"}}}, write]}
    arguments = {"draft_ref": ref, "expected_memory_revision": 1, "update": update}
    before = service.store.load(run_id)
    rejected = service.harness_tool(run_id, "remember", arguments, "bad-id")
    assert rejected["ok"] is False
    assert "update.experiences[1].ref" in rejected["error"]["message"]
    operations = rejected["error"]["details"]["operations"]
    assert len(operations) == 1 and operations[0]["path"] == "update.experiences[1]"
    assert operations[0]["read_before_update"] == {"tool": "recall", "arguments": {"focus": [wrong_id]}}
    after = service.store.load(run_id)
    assert after["memory_batches"] == before["memory_batches"] and after["tool_commits"] == before["tool_commits"]
    assert after["memory_revision"] == 1
    write["ref"]["id"] = ids["repair"]
    accepted = service.harness_tool(run_id, "remember", arguments, "correct-id")
    assert accepted["memory_revision"] == 2
    assert service.harness_tool(run_id, "remember", arguments, "correct-id") == accepted
    assert len(service.store.load(run_id)["memory_batches"]) == 2


def test_record_source_rejection_reports_actual_item_without_exposing_input(tmp_path: Path) -> None:
    """依赖：真实来源资格/工具指引。输入：第二项将作者大纲当经历来源。输出：准确source_refs下标、零提交且不回显原纲。实现：按原run真实AuthorInputRef触发语义拒绝，保留合法草稿。"""
    secret = "作者路线内部标记-DO-NOT-ECHO"
    service = build_writer_service(make_library(tmp_path), tmp_path / "workspace", tmp_path / "no-config.json")
    run_id = service.prepare(GraphKey("demo", "main"), "write", secret, "写短篇")
    ref = service.harness_tool(run_id, "save_draft", {"text": "梁临修好并归还怀表。", "expected_revision": 0}, "save")
    author_ref = service.store.load(run_id)["binding"]["input_snapshot_refs"][0]
    update = {"experiences": [
        {"op": "create", "local_ref": "repair", "record": {"record_kind": "experience", "payload": {"text": "怀表修好。"}}},
        {"op": "create", "local_ref": "return", "record": {"record_kind": "experience", "payload": {"text": "怀表归还。"}, "source_refs": [author_ref]}},
    ]}
    result = service.harness_tool(run_id, "remember", {"draft_ref": ref, "expected_memory_revision": 0, "update": update}, "wrong-source")
    assert result["ok"] is False and "update.experiences[1].record.source_refs" in result["error"]["message"]
    assert [row["path"] for row in result["error"]["details"]["operations"]] == ["update.experiences[1]"]
    assert secret not in str(result)
    assert service.store.load(run_id)["memory_batches"] == []


@pytest.mark.parametrize("update", [
    {"state_changes": [{"op": "clear", "entry_id": "existing", "local_ref": "new"}]},
    {"experiences": [{"op": "retire", "ref": {"kind": "experience", "id": "existing"}, "local_ref": "new"}]},
])
def test_memory_operations_reject_identity_fields_from_another_branch(update: dict) -> None:
    """依赖：公共整批校验。输入：解除操作混入新建local_ref。输出：带下标的形状错误。实现：在语义提交前拒绝互斥分支，旧落盘兼容由stored路径继续处理。"""
    from novel_rag.memory.schema import validate_memory_update

    errors = validate_memory_update(update)
    assert errors
    assert "[0]" in "; ".join(errors)


def test_update_validator_preserves_stored_identity_and_input_error_order() -> None:
    """依赖：共同操作结构校验。输入：已绑定身份的退役记录及混用字段的模型解除。输出：落盘形状通过、模型错误先分支再身份和值。实现：用原来源Ref和有序错误断言区分两份合同。"""
    from novel_rag.memory.schema import validate_memory_update

    draft_ref = {"kind": "draft", "draft_document_id": "draft-run-demo", "draft_revision": 1,
                 "content_hash": "sha256:" + "1" * 64, "checkpoint_id": "checkpoint-demo"}
    stored = {"experiences": [{"op": "retire", "id": "experience-demo",
                              "ref": {"kind": "experience", "id": "experience-demo"},
                              "source_refs": [draft_ref]}]}
    assert validate_memory_update(stored, stored=True) == []
    assert validate_memory_update(stored) == ["update.experiences[0]: 未知操作字段"]

    update = {"state_changes": [{"op": "clear", "entry_id": "", "record": {}, "entry": {}}]}
    path = "update.state_changes[0]"
    assert validate_memory_update(update) == [
        path + ": 操作必需字段缺失或混用新建/更新/解除字段，请按声明选择一个分支",
        path + ": 未知操作字段",
        path + ".entry_id缺失",
        path + ": 解除操作不能携带新值",
    ]
