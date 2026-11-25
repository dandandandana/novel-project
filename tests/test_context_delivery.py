"""模型交付、精确来源续读与原结果冻结；不改变记忆选择或正式作品。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_rag.composition import build_writer_service
from novel_rag.generation.context import build_context, context_binding, text_page
from novel_rag.identity import GraphKey
from novel_rag.mutations.types import fingerprint_bytes
from novel_rag.onboarding import author_preferences_path
from writer_fixtures import make_library, put_document, write_yaml


@pytest.fixture
def delivery_runtime(tmp_path: Path):
    """依赖：真实Writer/既有作品夹具。输入：临时目录。输出：库/writer/实际run。实现：长单段正文与短任务，不调用模型或改正式库。"""
    root = make_library(tmp_path)
    put_document(root, "long-source", "bridge-marker: " + "雨\\\"🙂\r\n" * 2400, chapter=1, scene=1)
    writer = build_writer_service(root, tmp_path / "workspace", tmp_path / "no-model.json")
    run_id = writer.prepare(GraphKey("demo", "main"), "write", "bridge-marker：两人在桥头交谈。", "只写新章。")
    return root, writer, run_id


def read_pages(writer, run_id: str, arguments: dict) -> tuple[str, list[dict]]:
    """依赖：真实harness_tool。输入：首读取参数。输出：拼接全文/每页实际回执。实现：只转发返回next_arguments，校验连续字符区间，不猜引用。"""
    fragments, pages, expected_start = [], [], 0
    while arguments is not None:
        result = writer.harness_tool(run_id, "read_document", arguments, delivery="model")
        assert result.get("ok") is not False, result
        assert result["character_range"][0] == expected_start
        expected_start = result["character_range"][1]
        fragments.append(result["text"])
        pages.append(result)
        arguments = result["next_arguments"]
    return "".join(fragments), pages


def test_context_uses_the_preference_text_captured_for_this_request(delivery_runtime, monkeypatch) -> None:
    """依赖：实际材料绑定和读取工具。输入：绑定后修改的作者偏好。输出：原请求只读一次，新读取拒绝旧hash。实现：观察偏好文件读取并核对交付正文与续读回执。"""
    root, writer, run_id = delivery_runtime
    path = author_preferences_path(root, "demo")
    path.write_text("雨天慢叙。", encoding="utf-8-sig")
    run = writer.store.load(run_id)
    definitions = writer.harness_tools(run_id)["tools"]
    reads = []
    read_text = Path.read_text

    def counted_read(file, *args, **kwargs):
        """依赖：Path.read_text。输入：原读取参数。输出：实际文本。实现：只计本次偏好文件，其余读取原样转发。"""
        if file == path:
            reads.append(file)
        return read_text(file, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted_read)
    captured = context_binding(run, writer.memory, writer.store, definitions)
    path.write_text("雪天快叙。", encoding="utf-8-sig")
    messages = build_context(run, writer.memory, writer.store, definitions, view="model", context_state=captured)
    content = json.loads(messages[1]["content"])
    assert content["author_preferences"] == "雨天慢叙。"
    assert reads == [path]
    stale = writer.harness_tool(run_id, "read_document", content["preference_source"]["read_arguments"])
    assert stale["error"]["code"] == "revision_conflict"


def test_model_core_omits_history_payload_but_keeps_task_and_full_export(delivery_runtime) -> None:
    """依赖：实际两视图上下文。输入：巨型单段及短任务。输出：小core/可读Ref与full完整原文。实现：检查首包JSON、重复引用和所有延后内容真实可达。"""
    root, writer, run_id = delivery_runtime
    context = writer.harness_context(run_id, view="model")
    payload = json.loads(context["messages"][1]["content"])
    assert context["context_view"] == payload["context_view"] == "model"
    assert payload["outline_original"] == "bridge-marker：两人在桥头交谈。"
    assert payload["request"] == "只写新章。"
    assert payload["body_context"] is None and not payload["baseline"]["inline"]
    assert "state_view" not in payload["memory"]
    assert len(json.dumps(context, ensure_ascii=False)) < 16000
    assert "雨\\\"🙂" not in json.dumps(context, ensure_ascii=False)
    actual, pages = read_pages(writer, run_id, payload["baseline"]["read_arguments"])
    assert actual == writer.memory.corpus(writer.store.load(run_id)).read("long-source")[0].searchable_text()
    assert len(pages) > 1 and all(len(page["text"]) <= 4096 for page in pages)
    full = writer.harness_context(run_id)
    exported = json.loads(full["messages"][1]["content"])
    assert exported["body_context"] == actual
    assert "references" not in exported["memory"]
    assert not any(row.get("text") == actual for row in exported["references"])


def test_long_author_inputs_and_preferences_are_exactly_readable(delivery_runtime) -> None:
    """依赖：实际InputRef/偏好owner/读取工具。输入：超长原纲、要求与偏好。输出：三者逐字回读、hash稳定。实现：使用model描述符，不把预览标成完整输入。"""
    root, writer, _ = delivery_runtime
    outline, request, preference = "原纲🙂\r\n" * 1400, "要求\\\"" * 1300, "文风🙂" * 1500
    preference_path = author_preferences_path(root, "demo")
    preference_path.parent.mkdir(parents=True, exist_ok=True)
    preference_path.write_bytes(preference.encode("utf-8"))
    run_id = writer.prepare(GraphKey("demo", "main"), "write", outline, request)
    payload = json.loads(writer.harness_context(run_id, view="model")["messages"][1]["content"])
    assert payload["outline_original"] is payload["request"] is payload["author_preferences"] is None
    for descriptor, expected in ((payload["author_inputs"]["outline"], outline), (payload["author_inputs"]["request"], request), (payload["preference_source"], preference)):
        actual, pages = read_pages(writer, run_id, descriptor["read_arguments"])
        assert actual == expected and descriptor["content_hash"] == fingerprint_bytes(actual.encode("utf-8"))
        assert all(page["content_hash"] == descriptor["content_hash"] for page in pages)


def test_document_continuation_rejects_changed_version_and_core_marks_stale(delivery_runtime) -> None:
    """依赖：实际SourceCorpus/字节修改。输入：首字符页后改源。输出：旧续读拒绝、固定基线stale。实现：复用原Ref/hash，不拼V1与V2。"""
    root, writer, run_id = delivery_runtime
    page = writer.harness_tool(run_id, "read_document", {"document_id": "long-source", "max_characters": 50})
    document = writer.memory.corpus(writer.store.load(run_id)).read("long-source")[0]
    value = {"metadata": document.metadata, "text": "NEW_VERSION" + "乙" * 1000}
    write_yaml(document.path, value)
    rejected = writer.harness_tool(run_id, "read_document", page["next_arguments"])
    assert rejected["error"]["code"] == "revision_conflict"
    payload = json.loads(writer.harness_context(run_id, view="model")["messages"][1]["content"])
    assert payload["baseline_status"] == "stale" and payload["body_context"] is None
    fresh = writer.harness_tool(run_id, "read_document", {"document_id": "long-source"})
    assert "NEW_VERSION" in fresh["text"] and fresh["source_ref"] != page["source_ref"]


def test_selected_parent_and_current_drafts_read_but_other_inputs_and_siblings_reject(delivery_runtime) -> None:
    """依赖：真实父绑定/Store权限。输入：当前稿、父稿、兄弟稿与外书引用。输出：合法内容完整、越权无文本。实现：真实prepare/save后只按已返回Ref读取。"""
    root, writer, parent_id = delivery_runtime
    parent_ref = writer.harness_tool(parent_id, "save_draft", {"text": "父稿" * 3000, "expected_revision": 0}, "parent-save")
    child_id = writer.prepare(GraphKey("demo", "main"), "write", "继续父稿", "只加新后缀", base_ref=parent_ref)
    actual, _ = read_pages(writer, child_id, {"source_ref": parent_ref, "max_characters": 1000})
    assert actual == "父稿" * 3000
    current_ref = writer.store.load(child_id)["draft_ref"]
    actual, _ = read_pages(writer, child_id, {"source_ref": current_ref, "max_characters": 1000})
    assert actual == "父稿" * 3000
    sibling_id = writer.prepare(GraphKey("demo", "main"), "write", "旁支", "旁支")
    sibling = writer.harness_tool(sibling_id, "save_draft", {"text": "PRIVATE_SIBLING", "expected_revision": 0}, "sibling-save")
    other_id = writer.prepare(GraphKey("other", "main"), "write", "PRIVATE_OTHER", "other")
    other_input = writer.store.load(other_id)["binding"]["input_snapshot_refs"][0]
    for reference in (sibling, other_input):
        rejected = writer.harness_tool(child_id, "read_document", {"source_ref": reference})
        assert rejected["error"]["code"] == "scope_denied" and "text" not in rejected


def test_recall_pages_freeze_one_result_and_survive_store_restart(delivery_runtime) -> None:
    """依赖：完整recall/原tool_results/新Store。输入：大型查询与小交付页。输出：续页重组等于原包且只选择一次。实现：重启Store后从本run原结果续读，页不是新route。"""
    root, writer, run_id = delivery_runtime
    page = writer.harness_tool(run_id, "recall", {"query": "bridge-marker", "page_characters": 1600}, delivery="model")
    assert page["delivery"] == "frozen_json_page"
    original = next(row["result"] for row in writer.store.load(run_id)["tool_results"] if row["call_id"] == page["result_ref"]["call_id"])
    fragments = [page["text"]]
    restarted = build_writer_service(root, writer.store.root, root / "no-model.json")
    while page["next_arguments"] is not None:
        page = restarted.harness_tool(run_id, "recall", page["next_arguments"], delivery="model")
        assert page.get("ok") is not False, page
        fragments.append(page["text"])
    assert json.loads("".join(fragments)) == original
    rows = restarted.store.load(run_id)["tool_results"]
    assert sum(row["name"] == "recall" and "delivery" not in row["result"] for row in rows) == 1


def test_frozen_recall_rejects_memory_change_foreign_cursor_and_bad_hash(delivery_runtime) -> None:
    """依赖：真实remember/CAS/冻结页。输入：页后记忆增量及伪造来源。输出：过期/越域/hash错误而无旧内容。实现：保留原页引用，不能自动换新版本继续切片。"""
    root, writer, run_id = delivery_runtime
    page = writer.harness_tool(run_id, "recall", {"query": "bridge-marker", "page_characters": 300}, delivery="model")
    sibling_id = writer.prepare(GraphKey("demo", "main"), "write", "旁支", "查记忆")
    foreign = writer.harness_tool(sibling_id, "recall", page["next_arguments"], delivery="model")
    assert foreign["error"]["code"] == "scope_denied"
    bad = {**page["next_arguments"], "continuation": {**page["next_arguments"]["continuation"], "content_hash": "bad"}}
    assert writer.harness_tool(run_id, "recall", bad)["error"]["code"] == "source_invalid"
    draft = writer.harness_tool(run_id, "save_draft", {"text": "甲把灯放在门边。", "expected_revision": 0}, "save-lamp")
    written = writer.harness_tool(run_id, "remember", {"draft_ref": draft, "expected_memory_revision": page["memory_revision"],
        "update": {"state_changes": [{"op": "set", "local_ref": "lamp", "entry": {"domain": "World", "kind": "location", "value": "灯在门边。", "lifetime": "carry"}}]}}, "remember-lamp")
    assert written["memory_revision"] == 1
    stale = writer.harness_tool(run_id, "recall", page["next_arguments"], delivery="model")
    assert stale["error"]["code"] == "snapshot_stale"


@pytest.mark.parametrize("value", [True, -1, 999999])
def test_character_range_rejects_invalid_start(value: object) -> None:
    """依赖：共同text_page。输入：布尔/负数/越界起点。输出：范围错误。实现：不把布尔当整数，不静默返回空页。"""
    with pytest.raises(ValueError, match="字符起点"):
        text_page("🙂甲", start_character=value)


def test_empty_text_has_complete_zero_length_page() -> None:
    """依赖：共同text_page。输入：空文本。输出：完整零区间无续读。实现：避免空源被误判丢失或无限分页。"""
    page = text_page("", max_characters=10)
    assert page["delivery_complete"] is True and page["character_range"] == [0, 0]
    assert page["next_start_character"] is None


@pytest.mark.parametrize("change", ["rewrite", "delete"])
def test_frozen_query_source_added_after_prepare_rejects_change(delivery_runtime, change: str) -> None:
    """依赖：真实晚加入来源/原快照。输入：prepare后新Canon，再改写或删除。输出：版本不误升但旧页stale。实现：核冻结结果实际Ref，不能只依赖memory_revision。"""
    root, writer, run_id = delivery_runtime
    path = put_document(root, "late-source", "late-unique-marker " + "ORIGINAL_SOURCE " * 300, category="canon")
    page = writer.harness_tool(run_id, "recall", {"query": "late-unique-marker", "page_characters": 80}, delivery="model")
    if change == "delete":
        path.unlink()
    else:
        document = writer.memory.corpus(writer.store.load(run_id)).read("late-source")[0]
        metadata = {**document.metadata, "source_revision": 2}
        write_yaml(path, {"metadata": metadata, "text": "late-unique-marker NEW_SOURCE"})
    rejected = writer.harness_tool(run_id, "recall", page["next_arguments"], delivery="model")
    assert rejected["error"]["code"] == "snapshot_stale"
    assert "text" not in rejected
    assert writer.store.load(run_id)["memory_revision"] == page["memory_revision"]


def test_changed_parent_prefix_has_no_unavailable_baseline_read_entry(delivery_runtime) -> None:
    """依赖：实际父稿/作者修订/模型描述符。输入：选定父稿后父作者改写。输出：基线stale且不可读入口为None，选中子稿仍可读。实现：来源用途分开，不宣称失效前缀可恢复。"""
    root, writer, parent_id = delivery_runtime
    parent_ref = writer.harness_tool(parent_id, "save_draft", {"text": "旧父稿", "expected_revision": 0}, "old-parent")
    child_id = writer.prepare(GraphKey("demo", "main"), "write", "继续", "继续父稿", base_ref=parent_ref)
    writer.store.save(parent_id, 1, "完全改写", origin="author")
    payload = json.loads(writer.harness_context(child_id, view="model")["messages"][1]["content"])
    assert payload["baseline"]["status"] == "stale"
    assert payload["baseline"]["available"] is False and payload["baseline"]["read_arguments"] is None
    actual, _ = read_pages(writer, child_id, payload["selected_draft"]["read_arguments"])
    assert actual == "旧父稿"
