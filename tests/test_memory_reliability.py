"""可靠性反例沿真实工具、采用与重新读取验证；仅使用隔离库。"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest

from novel_rag.config import validate_memory_metadata
from novel_rag.documents import read_yaml_mapping
from novel_rag.generation.store import DraftStore, StoreConflict
from novel_rag.generation.types import NarrativeCursor, RunBinding
from novel_rag.graph.corpus import json_text
from novel_rag.identity import GraphKey, StoryCoordinate
from novel_rag.memory.router import route
from novel_rag.memory.schema import validate_memory_update, validate_position, validate_source_refs
from novel_rag.memory.service import MemoryService
from novel_rag.mutations.summary import SummaryWriter
from novel_rag.mutations.types import fingerprint_bytes
from novel_rag.service import load_story_sources
from test_adoption_v3 import _adopt, _environment, _new_run, _remember_state
from test_harness_v3 import _service
from test_memory_router import _record, _required_link, _source_ref
from writer_fixtures import make_library, put_document, write_yaml


def test_recall_retries_stale_snapshot_without_overwriting_concurrent_remember(tmp_path, monkeypatch):
    """依赖：实际harness/Event/Store。输入：暂停旧recall后提交新remember。输出：最新值与稳定revision。实现：在快照和reconcile之间用barrier控制真实双线程窗口。"""
    root = make_library(tmp_path)
    writer, store, memory = _service(root, tmp_path / "workspace")
    run_id = writer.prepare(GraphKey("demo", "main"), "write", "路线", "继续")
    first = writer.harness_tool(run_id, "save_draft", {"text": "早期正文", "expected_revision": 0}, "save1")
    entry = {"domain": "World", "kind": "custody", "value": "early", "lifetime": "carry"}
    receipt = writer.harness_tool(run_id, "remember", {"draft_ref": first, "expected_memory_revision": 0,
        "update": {"state_changes": [{"op": "set", "local_ref": "custody", "entry": entry}]}}, "remember1")
    second = writer.harness_tool(run_id, "save_draft", {"text": "早期正文，后续正文", "expected_revision": 1}, "save2")
    ready, release = threading.Event(), threading.Event()
    original = memory._reconcile

    def paused(run, corpus, full, batches, **kwargs):
        """依赖：原reconcile/Event。输入：同次读取参数。输出：原结果。实现：仅暂停reader首个快照，重试不再暂停。"""
        if threading.current_thread().name.startswith("reader") and not ready.is_set():
            ready.set()
            assert release.wait(8)
        return original(run, corpus, full, batches, **kwargs)

    monkeypatch.setattr(memory, "_reconcile", paused)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="reader") as pool:
        reading = pool.submit(memory.recall, run_id)
        try:
            assert ready.wait(8)
            late = writer.harness_tool(run_id, "remember", {"draft_ref": second, "expected_memory_revision": 1,
                "update": {"state_changes": [{"op": "set", "entry_id": receipt["accepted_record_ids"][0],
                    "entry": dict(entry, value="late")}]}}, "remember2")
            assert late["memory_revision"] == 2
        finally:
            release.set()
        packet = reading.result(timeout=8)
    assert packet["memory_revision"] == memory.recall(run_id)["memory_revision"] == store.load(run_id)["memory_revision"] == 2
    assert [row["value"] for row in packet["state_view"]["entries"]] == ["late"]


@pytest.mark.parametrize("damage", ["entity-scope", "entity-position", "record-scope", "mixed-keys", "infinite-coordinate", "list-kind", "host-flag"])
def test_bad_stored_shapes_become_reader_gaps(tmp_path, damage):
    """依赖：真实remember、共同validator及SourceCorpus。输入：损坏的正式容器字段。输出：详细错误和可读取gap。实现：保存合法原批次，逐种损坏后从新run回读，不捕获并掩饰validator崩溃。"""
    root, _, store, memory, run, ref = _environment(tmp_path)
    memory.remember(run["run_id"], "valid", draft_ref=ref, expected_memory_revision=0, update={
        "unresolved_entities": [{"local_ref": "a", "name": "同名", "entity_type": "person"}],
        "notes": [{"op": "create", "local_ref": "note", "record": {"record_kind": "note", "payload": {"text": "marker"}}}]})
    batch = deepcopy(store.load(run["run_id"])["memory_batches"][0])
    metadata = {"memory_kind": "memory_projection", "memory_schema_version": 3, "memory_batches": [batch]}
    if damage == "entity-scope":
        del batch["update"]["unresolved_entities"][0]["scope"]
    elif damage == "entity-position":
        del batch["update"]["unresolved_entities"][0]["narrative_position"]
    elif damage == "record-scope":
        del batch["update"]["notes"][0]["record"]["scope"]
    elif damage == "mixed-keys":
        batch["update"]["notes"][0]["record"]["payload"].update({0: "bad", "unexpected": "bad"})
    elif damage == "infinite-coordinate":
        batch["narrative_position"] = {"kind": "document", "coordinate": {"volume": float("inf")}}
    elif damage == "list-kind":
        metadata["memory_kind"] = []
    else:
        batch["quarantine"] = True
    errors = validate_memory_metadata(metadata)
    assert errors
    put_document(root, "broken-memory", "展示", category="summary", extra_metadata=metadata)
    reader, _ = _new_run(store, "新读者")
    packet = memory.recall(reader["run_id"], query="marker")
    assert not packet["notes"]
    assert any("broken-memory.yaml" in gap for gap in packet["gaps"])


def test_position_ref_and_internal_journal_boundaries_do_not_crash(tmp_path):
    """依赖：共同位置/Ref校验和采用journal reader。输入：空位置、无效Ref扩展、坏内部路径/采用来源。输出：拒绝或来源缺口。实现：实际写坏journal并调用recall，路径越域走唯一Store。"""
    root, _, store, memory, run, ref = _environment(tmp_path)
    assert validate_position({"kind": "draft", "checkpoint_id": ""})
    assert validate_position({"kind": "document", "coordinate": {}})
    assert validate_source_refs([dict(ref, coordinate={"volume": 1})])
    assert validate_memory_update({"notes": [{"op": "create", "local_ref": "n", "record": {
        "record_kind": "note", "payload": {"text": "good", 0: "bad", "unexpected": "bad"}}}]})
    bad = {"scope": {"story_id": "demo", "timeline_id": "main"}, "operation_id": "bad",
           "result": {"source_ref": {"kind": "document", "document_id": []}},
           "memory_publication": {"projection_id": [], "batch_count": 1}}
    path = store.adoption_path(GraphKey("demo", "main"), "bad")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bad), encoding="utf-8")
    assert any("发布证据不可读" in gap for gap in memory.recall(run["run_id"])["gaps"])
    bad["result"]["source_ref"] = ref
    bad.pop("memory_publication")
    path.write_text(json.dumps(bad), encoding="utf-8")
    assert any("DocumentRef" in gap for gap in memory.recall(run["run_id"])["gaps"])
    for invalid in ({"key": [], "hash": ref["content_hash"]}, {"key": "../elsewhere", "hash": ref["content_hash"]}):
        with pytest.raises(StoreConflict, match="source_invalid"):
            store.protected_memory(invalid, GraphKey("demo", "main"))


@pytest.mark.parametrize("kind", ["experience", "state", "boundary", "identity"])
def test_formal_canon_only_experience_is_not_an_occurred_fact(tmp_path, kind):
    """依赖：真实Canon/summary reader与来源资格owner。输入：合法结构但Canon单独支持的动态记录。输出：不进入发生记录且报告来源缺口。实现：来源角色覆盖Experience、状态、边界与未定身份。"""
    root = make_library(tmp_path)
    put_document(root, "canon", "规则", category="canon")
    source = load_story_sources(root, GraphKey("demo", "main")).source_refs["canon"].as_dict()
    record = _record("wrong", "experience", {"text": "marker 尚未发生"}, source)
    batch = {"batch_id": "wrong-batch", "memory_revision": 1, "source_refs": [source], "narrative_position": None,
             "update": {"experiences": [{"op": "create", "id": "wrong", "record": record}]}}
    if kind == "state":
        batch["update"] = {"state_changes": [{"op": "set", "entry_id": "wrong", "entry": {
            "entry_id": "wrong", "domain": "World", "kind": "condition", "value": "marker不存在的当前值", "lifetime": "carry",
            "source_refs": [source], "narrative_position": None}}]}
    elif kind == "boundary":
        batch["update"] = {"scene_boundary": {"kind": "begin_scene", "scene_id": "wrong"}}
    elif kind == "identity":
        batch["update"] = {"unresolved_entities": [{"local_ref": "wrong", "id": "wrong", "name": "marker陌生人", "entity_type": "person",
            "scope": source["scope"], "source_refs": [source], "narrative_position": None}]}
    assert not validate_memory_metadata({"memory_kind": "memory_projection", "memory_schema_version": 3, "memory_batches": [batch]})
    put_document(root, "formal", "展示", category="summary", extra_metadata={
        "memory_kind": "memory_projection", "memory_schema_version": 3, "memory_batches": [batch]})
    store = DraftStore(tmp_path / "workspace")
    run, _ = _new_run(store, "reader")
    packet = MemoryService(root, store).recall(run["run_id"], query="marker")
    assert not packet["experiences"] and not packet["state_view"]["entries"] and not packet.get("entity_refs")
    assert packet["state_view"]["recorded_through"] is None
    assert any("wrong" in gap or "来源资格" in gap for gap in packet["gaps"])


def test_same_raw_batch_has_multiple_bindings_and_conflicting_raw_is_quarantined(tmp_path, monkeypatch):
    """依赖：实际采用/原保护证据/发布reader。输入：同批次两次合法修订发布及同ID异内容。输出：选有效绑定且冲突不任选。实现：真实双采用，反转journal扫描，并按完整新证据模拟坏身份复用。"""
    root, _, store, memory, run, ref = _environment(tmp_path)
    _remember_state(store, memory, run, ref)
    first = _adopt(root, store, memory, run, ref, "binding-a")
    second = _adopt(root, store, memory, run, ref, "binding-b", expected_source_hash=first["source_hash"])
    assert second["source_revision"] == 2
    real_journals = store.memory_publications

    def reversed_journals(scopes):
        """依赖：原journal reader。输入：scope。输出：反序发布数组。实现：仅交换输入顺序，不改来源或绑定。"""
        rows, gaps = real_journals(scopes)
        return list(reversed(rows)), gaps

    reader, _ = _new_run(store, "读信物")
    normal = memory.recall(reader["run_id"], query="信物")
    monkeypatch.setattr(store, "memory_publications", reversed_journals)
    reverse = memory.recall(reader["run_id"], query="信物")
    assert normal["state_view"]["entries"] == reverse["state_view"]["entries"]
    assert len(reverse["state_view"]["entries"]) == 1
    assert reverse["state_view"]["entries"][0]["source_refs"] == [second["source_ref"]]
    journal_path = store.adoption_path(GraphKey("demo", "main"), "binding-a")
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    publication = journal["memory_publication"]
    raw = store.protected_memory(publication["raw_snapshot"], GraphKey("demo", "main"))
    raw["batches"][0]["update"]["state_changes"][0]["entry"]["value"] = "冲突内容"
    raw["canonical_hashes"] = [fingerprint_bytes(json_text(batch).encode("utf-8")) for batch in raw["batches"]]
    publication.update(raw_snapshot=store.protect_memory(GraphKey("demo", "main"), raw), canonical_hashes=raw["canonical_hashes"],
        mapped_snapshot=store.protect_memory(GraphKey("demo", "main"), {"batches": memory.map_publication(raw["batches"], first["source_ref"])}))
    journal_path.write_text(json.dumps(journal, ensure_ascii=False), encoding="utf-8")
    conflicted = memory.recall(reader["run_id"], query="信物")
    assert not conflicted["state_view"]["entries"]
    assert any("规范原始内容冲突" in gap for gap in conflicted["gaps"])
    assert conflicted["memory_revision"] == reverse["memory_revision"] + 1
    assert memory.recall(reader["run_id"])["memory_revision"] == conflicted["memory_revision"]


def test_lost_required_link_container_blocks_surviving_result(tmp_path):
    """依赖：实际分章remember/采用/失效控制/依赖包。输入：结果和必要关系分别采用后仅删除Link摘要。输出：存活结果不被独立选入，隐藏内容不泄漏。实现：新run完整reader验证容器外依赖义务。"""
    root, _, store, memory, run, ref = _environment(tmp_path)
    receipt = memory.remember(run["run_id"], "experiences", draft_ref=ref, expected_memory_revision=0, update={
        "experiences": [{"op": "create", "local_ref": local, "record": {"record_kind": "experience", "payload": {"text": text}}}
            for local, text in (("result", "marker-result结论"), ("cause", "未供当前查询展示的原因"))]})
    ids = receipt["local_ref_to_stable_id"]
    _adopt(root, store, memory, run, ref, "body")
    second, second_ref = _new_run(store, "第二章说明因果", coordinate=StoryCoordinate(1, 2, 1))
    memory.remember(second["run_id"], "relation", draft_ref=second_ref, expected_memory_revision=0, update={
        "links": [{"op": "create", "local_ref": "requires", "record": {"record_kind": "link", "payload": {
            "relation_type": "required_context", "subject_ref": {"kind": "experience", "id": ids["result"]},
            "object_ref": {"kind": "experience", "id": ids["cause"]}}}}]})
    _adopt(root, store, memory, second, second_ref, "relation", coordinate=StoryCoordinate(1, 2, 1))
    reader, _ = _new_run(store, "third")
    assert len(memory.recall(reader["run_id"], focus=[ids["result"]])["experiences"]) == 2
    projection = next(doc.path for doc in load_story_sources(root, GraphKey("demo", "main")).documents if doc.document_id == "memory-relation")
    projection.unlink()
    packet = memory.recall(reader["run_id"], focus=[ids["result"]])
    assert not packet["experiences"]
    assert any("必要关系来源不可用" in gap for gap in packet["gaps"])


def test_ended_state_reference_returns_receipt_without_current_value(tmp_path):
    """依赖：实际状态/Experience/Link/解除与router。输入：经历引用随后Clear的状态。输出：结束来源可见且无旧当前值。实现：同ID真实Set与Clear后按经历ID查询。"""
    _, _, store, memory, run, ref = _environment(tmp_path)
    receipt = _remember_state(store, memory, run, ref)
    state_id = receipt["accepted_record_ids"][0]
    exp = memory.remember(run["run_id"], "event", draft_ref=ref, expected_memory_revision=1, update={
        "experiences": [{"op": "create", "local_ref": "exp", "record": {"record_kind": "experience", "payload": {"text": "交出信物"}}}],
        "links": [{"op": "create", "local_ref": "use", "record": {"record_kind": "link", "payload": {
            "relation_type": "uses_state", "subject_ref": {"local_ref": "exp"}, "object_ref": {"kind": "state", "id": state_id}}}}]})
    later = store.save(run["run_id"], 1, "正文：甲交出刻有雾灯的信物。\n乙归还。").as_dict()
    memory.remember(run["run_id"], "clear", draft_ref=later, expected_memory_revision=2,
                    update={"state_changes": [{"op": "clear", "entry_id": state_id}]})
    packet = memory.recall(run["run_id"], focus=[exp["local_ref_to_stable_id"]["exp"]])
    assert not packet["state_view"]["entries"]
    ended = packet["state_view"]["ended_entries"]
    assert ended[0]["entry_id"] == state_id and ended[0]["effect"] == "cleared"
    assert "value" not in ended[0] and later in ended[0]["source_refs"]


def test_direct_hook_pending_precede_65_ordinary_seeds_and_caps_are_receipted(tmp_path):
    """依赖：实际来源Ref/route。输入：65普通seed、焦点Hook和Pending及长文本。输出：直接项先选、访问缺口可见、不按token裁长。实现：默认容量与必要依赖上限分别检验。"""
    source = _source_ref(tmp_path)
    long_text = "marker完整长参考" * 3000
    records = {f"a-note-{index:02d}": _record(f"a-note-{index:02d}", "note", {"text": "marker ordinary"}, source) for index in range(65)}
    records["z-hook"] = _record("z-hook", "hook", {"nature": "unresolved", "text": long_text}, source)
    pending = {"entry_id": "z-pending", "domain": "OpenCondition", "kind": "pending", "value": "marker欠款未付",
               "lifetime": "carry", "source_refs": [source]}
    packet = route(records, [pending], focus=["z-hook", "z-pending"], query="marker")
    assert packet["hooks"][0]["payload"]["text"] == long_text
    assert packet["state_entries"][0]["entry_id"] == "z-pending"
    assert any("候选访问上限64" in gap for gap in packet["gaps"])
    assert sum(len(packet[group]) for group in ("hooks", "notes", "state_entries")) == 64
    chain = {str(index): _record(str(index), "experience", {"text": str(index)}, source) for index in range(18)}
    chain.update({f"link{index}": _required_link(f"link{index}", ("experience", str(index)), ("experience", str(index + 1)), source) for index in range(17)})
    limited = route(chain, [], focus=["0"], max_nodes=1)
    assert not limited["experiences"] and any("必要依赖过长" in gap for gap in limited["gaps"])


def test_coverage_distinguishes_unrecorded_suffix_unknown_scene_and_plan(tmp_path):
    """依赖：真实Store/记忆覆盖。输入：scene状态无边界、carry及仅输入计划再追加。输出：carry保留、不同缺口与覆盖位置保持。实现：保存可继续，不以计划推进正文覆盖。"""
    _, _, store, memory, run, ref = _environment(tmp_path)
    memory.remember(run["run_id"], "state", draft_ref=ref, expected_memory_revision=0, update={"state_changes": [
        {"op": "set", "local_ref": "carry", "entry": {"domain": "World", "kind": "condition", "value": "marker继承", "lifetime": "carry"}},
        {"op": "set", "local_ref": "scene", "entry": {"domain": "World", "kind": "condition", "value": "marker现场", "lifetime": "scene"}}]})
    before = memory.recall(run["run_id"], query="marker")
    store.save(run["run_id"], 1, store.load(run["run_id"])["draft_text"] + "未记录后缀")
    input_ref = store.load(run["run_id"])["binding"]["input_snapshot_refs"][0]
    memory.remember(run["run_id"], "plan", draft_ref=None, expected_memory_revision=1, update={"hooks": [
        {"op": "create", "local_ref": "plan", "record": {"record_kind": "hook", "payload": {
            "nature": "author_plan", "text": "marker未来计划"}, "source_refs": [input_ref]}}]})
    after = memory.recall(run["run_id"], query="marker")
    assert after["state_view"]["recorded_through"] == before["state_view"]["recorded_through"]
    assert len(after["state_view"]["entries"]) == 2
    assert any("边界未知" in gap for gap in after["gaps"])
    assert any("尚未记录的正文后缀" in gap for gap in after["gaps"])


def test_same_named_identity_media_belief_roundtrip_and_future_id_rejected(tmp_path):
    """依赖：实际声明/remember/采用/游标reader。输入：同名两人、失实校园广播、World真相与晚身份。输出：各持不同ID、私有信念不传播、未来ID拒绝。实现：同批局部引用往返且重试ID稳定。"""
    root, _, store, memory, run, first = _environment(tmp_path, "两名小林在学校。第一人听到旧广播桥已断，桥其实已修复，另一人未听到。")
    info = {"channel": "学校课堂/校园广播/报刊/电视节目", "source": "校园广播站转引上周报刊", "certainty": "听闻未核实",
            "basis": "只收听早间节目概要；本期电视更正未看，另一人不在教室；没有内部权限。"}
    update = {"unresolved_entities": [{"local_ref": key, "name": "小林", "entity_type": "person"} for key in ("one", "two")],
              "state_changes": [{"op": "set", "local_ref": "news", "entry": {"domain": "CharacterView", "kind": "belief", "holder": {"local_ref": "one"},
                  "value": "桥可能仍断", "lifetime": "carry", "information": info}},
                  {"op": "set", "local_ref": "truth", "entry": {"domain": "World", "kind": "bridge", "value": "桥已修复", "lifetime": "carry"}}]}
    receipt = memory.remember(run["run_id"], "media", draft_ref=first, expected_memory_revision=0, update=update)
    assert receipt == memory.remember(run["run_id"], "media", draft_ref=first, expected_memory_revision=0, update=update)
    ids = receipt["local_ref_to_stable_id"]
    assert ids["one"] != ids["two"]
    second = store.save(run["run_id"], 1, store.load(run["run_id"])["draft_text"] + "后来新人到场。").as_dict()
    newer = memory.remember(run["run_id"], "later-person", draft_ref=second, expected_memory_revision=1,
        update={"unresolved_entities": [{"local_ref": "late", "name": "晚到", "entity_type": "person"}]})
    with pytest.raises(ValueError, match="端点未知|越域"):
        memory.remember(run["run_id"], "future-id", draft_ref=first, expected_memory_revision=2, update={
            "experiences": [{"op": "create", "local_ref": "exp", "record": {"record_kind": "experience", "payload": {"text": "误引用后来的人"}}}],
            "links": [{"op": "create", "local_ref": "involves", "record": {"record_kind": "link", "payload": {
                "relation_type": "involves", "subject_ref": {"local_ref": "exp"}, "object_ref": {"kind": "entity", "id": newer["local_ref_to_stable_id"]["late"]}}}}]})
    adopted = _adopt(root, store, memory, run, second, "media-adopt")
    assert adopted["memory_state"] == "complete"
    fresh = DraftStore(store.root)
    for endpoint in ("before", "after"):
        reader = fresh.create(RunBinding(scope=GraphKey("demo", "main"), task_kind="scene", narrative_cursor=NarrativeCursor(endpoint, StoryCoordinate(1, 1, 1)),
            base_ref=None, draft_branch="reader"), "", "")
        packet = MemoryService(root, fresh).recall(reader["run_id"], focus=[ids["one"], ids["two"]], query="小林 桥")
        if endpoint == "before":
            assert not packet["state_view"]["entries"]
        else:
            assert {row["entity_id"] for row in packet["entity_refs"] if row["name"] == "小林"} == {ids["one"], ids["two"]}
            beliefs = [row for row in packet["state_view"]["entries"] if row["domain"] == "CharacterView"]
            assert len(beliefs) == 1 and beliefs[0]["holder"] == ids["one"]
            assert beliefs[0]["information"] == info and beliefs[0]["value"] == "桥可能仍断"


def test_frozen_publication_recovery_after_workspace_and_library_move(tmp_path, monkeypatch):
    """依赖：原采用intent/保护快照/逻辑键。输入：summary保存故障后新增记忆并搬迁。输出：原ID只恢复原集合，不覆盖正文或重采样。实现：实际rename隔离库与Store，使旧绝对路径不存在。"""
    root, workspace, store, memory, run, ref = _environment(tmp_path)
    _remember_state(store, memory, run, ref)
    original = SummaryWriter.write_ai

    def fail(*args, **kwargs):
        """依赖：SummaryWriter保存点。输入：真实保存参数。输出：一次明确失败。实现：不改变已采用正文，仅阻断派生投影。"""
        raise OSError("fixture summary failure")

    monkeypatch.setattr(SummaryWriter, "write_ai", fail)
    first = _adopt(root, store, memory, run, ref, "move")
    assert first["adopted"] and first["memory_state"] == "memory_pending"
    input_ref = store.load(run["run_id"])["binding"]["input_snapshot_refs"][0]
    revision = memory.recall(run["run_id"])["memory_revision"]
    memory.remember(run["run_id"], "late-note", draft_ref=None, expected_memory_revision=revision, update={"notes": [
        {"op": "create", "local_ref": "late", "record": {"record_kind": "note", "payload": {"text": "未冻结新笔记"}, "source_refs": [input_ref]}}]})
    moved_root, moved_workspace = tmp_path / "moved-library", tmp_path / "moved-workspace"
    assert all(path.resolve().is_relative_to(tmp_path.resolve()) for path in (root, workspace, moved_root, moved_workspace))
    root.rename(moved_root)
    workspace.rename(moved_workspace)
    assert not root.exists() and not workspace.exists()
    monkeypatch.setattr(SummaryWriter, "write_ai", original)
    fresh = DraftStore(moved_workspace)
    result = _adopt(moved_root, fresh, MemoryService(moved_root, fresh), run, ref, "move")
    assert result["memory_state"] == "complete" and result["source_hash"] == first["source_hash"]
    projection = next((moved_root / "stories/demo/timelines/main/summaries").glob("*.yaml"))
    batches = read_yaml_mapping(projection)["metadata"]["memory_batches"]
    assert len(batches) == 1 and not batches[0]["update"].get("notes")


def test_uncooperative_source_edit_at_commit_is_rejected_without_lock_leak(tmp_path, monkeypatch):
    """依赖：真实remember/源锁/Store锁/Event。输入：校验后由外部线程改写Canon。输出：不提交混合批次，锁释放且后续读写可用。实现：barrier暂停规范化返回前，复核检测源字节变化。"""
    root, _, store, memory, run, ref = _environment(tmp_path)
    source = put_document(root, "canon", "旧来源", category="canon")
    ready, release = threading.Event(), threading.Event()
    original = memory._normalize

    def paused(*args, **kwargs):
        """依赖：原规范化器/Event。输入：实际差分。输出：完整规范化候选。实现：在提交复核前暂停，不释放持有的源锁和Store锁。"""
        result = original(*args, **kwargs)
        ready.set()
        assert release.wait(8)
        return result

    monkeypatch.setattr(memory, "_normalize", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        writing = pool.submit(memory.remember, run["run_id"], "mixed", draft_ref=ref, expected_memory_revision=0,
            update={"notes": [{"op": "create", "local_ref": "note", "record": {"record_kind": "note", "payload": {"text": "candidate"}}}]})
        try:
            assert ready.wait(8)
            payload = read_yaml_mapping(source)
            payload["content"] = "外部新来源"
            write_yaml(source, payload)
        finally:
            release.set()
        with pytest.raises(StoreConflict, match="快照已改变"):
            writing.result(timeout=8)
    assert not store.load(run["run_id"])["memory_batches"]
    monkeypatch.setattr(memory, "_normalize", original)
    packet = memory.recall(run["run_id"])
    memory.remember(
        run["run_id"], "after-edit", draft_ref=ref, expected_memory_revision=packet["memory_revision"], update={"notes": [
            {"op": "create", "local_ref": "note", "record": {"record_kind": "note", "payload": {"text": "fresh"}}}]})
    assert len(store.load(run["run_id"])["memory_batches"]) == 1


def test_lost_retirement_container_does_not_resurrect_experience(tmp_path):
    """依赖：实际create/retire/两次采用与新Store。输入：已退役记录的投影被删除。输出：旧记录不复活且来源缺口可见。实现：删除原run后只用正式发布证据回读。"""
    import shutil

    root, workspace, store, memory, first, ref = _environment(tmp_path)
    receipt = memory.remember(first["run_id"], "create", draft_ref=ref, expected_memory_revision=0, update={
        "experiences": [{"op": "create", "local_ref": "exp", "record": {"record_kind": "experience", "payload": {"text": "marker obsolete"}}}]})
    _adopt(root, store, memory, first, ref, "first")
    second, second_ref = _new_run(store, "记录被撤销", coordinate=StoryCoordinate(1, 2, 1))
    memory.remember(second["run_id"], "retire", draft_ref=second_ref, expected_memory_revision=0, update={
        "experiences": [{"op": "retire", "ref": {"kind": "experience", "id": receipt["accepted_record_ids"][0]}}]})
    _adopt(root, store, memory, second, second_ref, "second", coordinate=StoryCoordinate(1, 2, 1))
    projection = next(doc.path for doc in load_story_sources(root, GraphKey("demo", "main")).documents if doc.document_id == "memory-second")
    projection.unlink()
    for run in (first, second):
        directory = workspace / "demo/main/runs" / run["run_id"]
        assert directory.resolve().is_relative_to(workspace.resolve())
        shutil.rmtree(directory)
    fresh = DraftStore(workspace)
    reader, _ = _new_run(fresh, "reader")
    packet = MemoryService(root, fresh).recall(reader["run_id"], query="marker")
    assert not packet["experiences"] and packet["gaps"]


def test_scene_boundary_without_legacy_draft_ref_uses_actual_history(tmp_path):
    """依赖：合法旧StoredBatch/正式来源/scene reader。输入：仅History来源的边界而无draft_ref。输出：不崩溃且边界可回读。实现：保留旧合法容器形状，不制造草稿引用。"""
    root = make_library(tmp_path)
    put_document(root, "history", "场景变化")
    source = load_story_sources(root, GraphKey("demo", "main")).source_refs["history"].as_dict()
    batch = {"batch_id": "boundary", "memory_revision": 1, "source_refs": [source],
        "narrative_position": {"kind": "document", "coordinate": source["coordinate"]},
        "update": {"scene_boundary": {"kind": "begin_scene", "scene_id": "scene1"}}}
    assert not validate_memory_metadata({"memory_kind": "memory_projection", "memory_schema_version": 3, "memory_batches": [batch]})
    put_document(root, "summary", "展示", category="summary", extra_metadata={
        "memory_kind": "memory_projection", "memory_schema_version": 3, "memory_batches": [batch]})
    store = DraftStore(tmp_path / "workspace")
    reader, _ = _new_run(store, "")
    packet = MemoryService(root, store).recall(reader["run_id"])
    assert packet["state_view"]["recorded_through"] == batch["narrative_position"]


def test_real_http_unknown_receipt_sends_once_and_restores_original_operation(tmp_path, monkeypatch):
    """依赖：实际loopback HTTP/BackendClient/提交表。输入：POST真正提交后丢失回执。输出：unknown不自动重发，显式原ID恢复同结果。实现：读取服务器回执后在客户端边界模拟IncompleteRead，终态仍能恢复。"""
    from http.client import IncompleteRead

    from native_http_fixture import workspace_server
    from novel_rag.harness import BackendClient, BackendError
    from novel_rag.web.app import create_app

    root = make_library(tmp_path)
    app = create_app(root, tmp_path / "workspace", tmp_path / "missing-model.json")
    attempts, committed = [], {}
    with workspace_server(app) as backend:
        client = BackendClient(backend, timeout=8)
        run_id = client.request("/api/v1/runs", {"driver": "harness", "story_id": "demo", "timeline_id": "main", "outline": "路线", "request": "继续"})["run_id"]
        path = f"/api/v1/runs/{run_id}/harness-tool"
        ref = client.request(path, {"name": "save_draft", "operation_id": "save", "arguments": {"text": "正文", "expected_revision": 0}})
        arguments = {"name": "remember", "operation_id": "original", "arguments": {"draft_ref": ref, "expected_memory_revision": 0,
            "update": {"state_changes": [{"op": "set", "local_ref": "state", "entry": {"domain": "World", "kind": "custody", "value": "一次", "lifetime": "carry"}}]}}}
        original = client._opener.open

        def lost(request, **kwargs):
            """依赖：原urllib真实请求。输入：POST对象。输出：传输异常。实现：发送一次、读完真实已提交回执后丢弃，不重试请求。"""
            attempts.append(1)
            with original(request, **kwargs) as response:
                raw = response.read()
            committed["receipt"] = json.loads(raw)
            raise IncompleteRead(b"", len(raw))

        monkeypatch.setattr(client._opener, "open", lost)
        with pytest.raises(BackendError) as error:
            client.request(path, arguments)
        assert error.value.error["effects_known"] is False and len(attempts) == 1
        monkeypatch.setattr(client._opener, "open", original)
        client.request(f"/api/v1/runs/{run_id}/harness-finish", {"status": "completed"})
        assert client.request(path, arguments) == committed["receipt"]
        run = app.state.service.store.load(run_id)
        assert run["memory_revision"] == 1 and len(run["memory_batches"]) == 1
    assert not (tmp_path / "workspace/.writer.lock").exists()


def test_invalid_future_record_does_not_invalidate_earlier_visible_version(tmp_path):
    """依赖：实际History/容器/游标/record效力。输入：同ID未来更新来源损坏。输出：较早游标仍保留旧合法版本。实现：未来位置先过滤，不能把来源失效控制施加到过去。"""
    root = make_library(tmp_path)
    put_document(root, "early", "早章", chapter=1)
    future_path = put_document(root, "future", "晚章", chapter=3)
    corpus = load_story_sources(root, GraphKey("demo", "main"))
    for index, source_id in enumerate(("early", "future")):
        source = corpus.source_refs[source_id].as_dict()
        position = {"kind": "document", "coordinate": source["coordinate"]}
        record = dict(_record("shared-exp", "experience", {"text": "早期版本" if index == 0 else "未来秘密"}, source), narrative_position=position)
        batch = {"batch_id": source_id, "memory_revision": index + 1, "source_refs": [source], "narrative_position": position,
            "update": {"experiences": [{"op": "create" if index == 0 else "update", "id": "shared-exp", "record": record}]}}
        put_document(root, "memory-" + source_id, "展示", category="summary", chapter=1, extra_metadata={
            "memory_kind": "memory_projection", "memory_schema_version": 3, "memory_batches": [batch]})
    payload = read_yaml_mapping(future_path)
    payload["content"] = "未来被改写"
    write_yaml(future_path, payload)
    store = DraftStore(tmp_path / "workspace")
    reader = store.create(RunBinding(scope=GraphKey("demo", "main"), task_kind="scene", narrative_cursor=NarrativeCursor("after", StoryCoordinate(1, 2, 1)),
        base_ref=None, draft_branch="reader"), "", "")
    packet = MemoryService(root, store).recall(reader["run_id"], focus=["shared-exp"])
    assert [row["payload"]["text"] for row in packet["experiences"]] == ["早期版本"]
    assert "未来秘密" not in json_text(packet)


def test_unselected_query_records_are_reported_without_erasing_them(tmp_path):
    """依赖：route/实际来源Ref。输入：一个命中和一个未相关的可见笔记。输出：选择说明与未选缺口，原记录仍保留。实现：两次交换focus后都能读原完整项。"""
    source = _source_ref(tmp_path)
    records = {key: _record(key, "note", {"text": key}, source) for key in ("one", "two")}
    first = route(records, [], focus=["one"])
    second = route(records, [], focus=["two"])
    assert [row["id"] for row in first["notes"]] == ["one"]
    assert [row["id"] for row in second["notes"]] == ["two"]
    assert any("未被本次查询选入" in gap for gap in first["gaps"])
