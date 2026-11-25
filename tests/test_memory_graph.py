from __future__ import annotations

from pathlib import Path

from novel_rag.identity import GraphKey
from novel_rag.memory.graph import project_records
from novel_rag.memory.router import route
from novel_rag.service import load_story_sources
from writer_fixtures import make_library, put_document


def _real_source_refs(tmp_path: Path) -> dict[str, dict]:
    """依赖：writer_fixtures与load_story_sources。输入：pytest临时目录。输出：含Canon、隐藏和未来来源的真实DocumentRef。实现：写规范文档并由source-only入口读取其实际指纹。"""

    root = make_library(tmp_path)
    put_document(root, "canon-source", "稳定设定。", category="canon")
    put_document(root, "hidden-source", "隐藏桥来源。", chapter=1, scene=1)
    put_document(root, "future-source", "未来桥来源。", chapter=1, scene=2)
    corpus = load_story_sources(root, GraphKey("demo", "main"))
    return {key: ref.as_dict() for key, ref in corpus.source_refs.items()}


def _record(record_id: str, kind: str, payload: dict, source_ref: dict) -> dict:
    """依赖：project_records和route的规范Record映射。输入：稳定身份、类型、payload与真实来源引用。输出：规范记录。实现：显式绑定scope及source_refs而不伪造hash。"""

    return {
        "id": record_id,
        "record_kind": kind,
        "scope": {"story_id": "demo", "timeline_id": "main"},
        "source_refs": [source_ref],
        "narrative_position": None,
        "payload": payload,
    }


def _batch(records: list[dict]) -> dict:
    """依赖：project_records的StoredMemoryBatch投影。输入：规范事件、经历、Link记录。输出：全为create的批次。实现：按记录kind放入对应变化数组。"""

    groups = {"event_line": "event_lines", "experience": "experiences", "hook": "hooks", "note": "notes", "link": "links"}
    update = {name: [] for name in groups.values()}
    for record in records:
        group = groups[record["record_kind"]]
        update[group].append({"op": "create", "id": record["id"], "record": record})
    return {"batch_id": "normalized-source-fixture", "source_refs": [], "update": update}


def _link(record_id: str, relation: str, subject: tuple[str, str], object_: tuple[str, str], source_ref: dict) -> dict:
    """依赖：图投影Link方向合同。输入：Link身份、关系、端点(kind,id)和真实来源。输出：规范Link记录。实现：保持subject/object方向且不复制关系到节点。"""

    return _record(
        record_id,
        "link",
        {
            "relation_type": relation,
            "subject_ref": {"kind": subject[0], "id": subject[1]},
            "object_ref": {"kind": object_[0], "id": object_[1]},
        },
        source_ref,
    )


def test_projected_graph_does_not_traverse_future_or_hidden_bridges(tmp_path: Path) -> None:
    """依赖：真实DocumentRef、project_records和route。输入：两条可见种子及分别被隐藏/标未来的中间经历。输出：路径不越过不可见桥。实现：来源可见性先投影，再用词种子检查可达经历。"""

    refs = _real_source_refs(tmp_path)
    canon, hidden, future = refs["canon-source"], refs["hidden-source"], refs["future-source"]
    records = [
        _record("seed-hidden", "experience", {"text": "seed marker hidden branch"}, canon),
        _record("hidden-bridge", "experience", {"text": "不可见桥"}, hidden),
        _record("far-side-hidden", "experience", {"text": "隐藏桥之后"}, canon),
        _link("edge-hidden-in", "follows", ("experience", "seed-hidden"), ("experience", "hidden-bridge"), canon),
        _link("edge-hidden-out", "follows", ("experience", "hidden-bridge"), ("experience", "far-side-hidden"), canon),
        _record("seed-future", "experience", {"text": "seed marker future branch"}, canon),
        _record("future-bridge", "experience", {"text": "未来桥"}, future),
        _record("far-side-future", "experience", {"text": "未来桥之后"}, canon),
        _link("edge-future-in", "follows", ("experience", "seed-future"), ("experience", "future-bridge"), canon),
        _link("edge-future-out", "follows", ("experience", "future-bridge"), ("experience", "far-side-future"), canon),
    ]

    def visibility(record: dict) -> str:
        """依赖：测试构造的source-only可见性标签。输入：已有真实source_refs的记录。输出：valid/future/stale。实现：按来源文件身份隔离两种不可见桥。"""

        document_ids = {ref["document_id"] for ref in record.get("source_refs", [])}
        if "hidden-source" in document_ids:
            return "stale"
        if "future-source" in document_ids:
            return "future"
        return "valid"

    projected = project_records([_batch(records)], visible=visibility)
    packet = route(projected, [], query="seed marker", available_tokens=4096, max_hops=3)
    selected_ids = {row["id"] for row in packet["experiences"]}

    assert "hidden-bridge" not in projected
    assert "future-bridge" not in projected
    assert {"seed-hidden", "seed-future"} <= selected_ids
    assert "far-side-hidden" not in selected_ids
    assert "far-side-future" not in selected_ids


def test_one_experience_can_belong_to_two_event_lines_without_duplication(tmp_path: Path) -> None:
    """依赖：project_records派生反向索引与有限router。输入：一个经过、两条事件线及两条belongs_to Link。输出：单条Experience同时关联两线。实现：以真实来源投影图并按经过文本召回两端。"""

    refs = _real_source_refs(tmp_path)
    source_ref = refs["canon-source"]
    records = [
        _record("line-a", "event_line", {"title": "借出"}, source_ref),
        _record("line-b", "event_line", {"title": "归还"}, source_ref),
        _record("shared-exp", "experience", {"text": "shared experience marker"}, source_ref),
        _link("membership-a", "belongs_to", ("experience", "shared-exp"), ("event_line", "line-a"), source_ref),
        _link("membership-b", "belongs_to", ("experience", "shared-exp"), ("event_line", "line-b"), source_ref),
    ]
    projected = project_records([_batch(records)])

    packet = route(projected, [], query="shared experience marker", available_tokens=4096, max_hops=1)

    assert {item["id"] for item in packet["event_lines"]} == {"line-a", "line-b"}
    assert [item["id"] for item in packet["experiences"]] == ["shared-exp"]
    assert {item["id"] for item in projected["shared-exp"]["event_line_refs"]} == {"line-a", "line-b"}
