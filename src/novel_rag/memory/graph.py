"""事件记录与方向；Link 是拓扑唯一保存点，图仅为派生视图。"""
from __future__ import annotations

from copy import deepcopy
from typing import Callable, Iterable


ENDPOINTS = {
    "belongs_to": ({"experience"}, {"event_line"}),
    "involves": ({"event_line", "experience", "hook"}, {"entity"}),
    "follows": ({"experience"}, {"experience"}),
    "causes": ({"experience"}, {"experience"}),
    "plants": ({"experience"}, {"hook"}),
    "pays_off": ({"experience"}, {"hook"}),
    "uses_state": ({"event_line", "experience", "hook"}, {"state"}),
    "required_context": ({"event_line", "experience", "hook", "note"},
                         {"event_line", "experience", "hook", "note", "state"}),
}
RECORD_GROUPS = {"event_lines": "event_line", "experiences": "experience", "hooks": "hook", "notes": "note", "links": "link"}
RECORD_FIELDS = {"event_line": {"title"}, "experience": {"text"},
                 "hook": {"nature", "text", "explanation_candidates"}, "note": {"text"},
                 "link": {"relation_type", "subject_ref", "object_ref"}}


def project_records(batches: Iterable[dict], *, visible: Callable[[dict], str] | None = None,
                    dependency_gaps: dict[str, list[str]] | None = None) -> dict[str, dict]:
    """依赖：规范批次/来源效力。输入：有序变更及可选依赖缺口输出。输出：有效记录索引。实现：失效Link保留不可遍历义务，未来/坏节点不入图，身份由原声明派生。"""
    records, unavailable = {}, {}
    for batch in batches:
        if batch.get("visibility") == "future":
            continue
        if batch.get("quarantine"):
            records.clear()
        for entity in batch.get("update", {}).get("unresolved_entities", []):
            status = entity.get("visibility", batch.get("visibility", "valid"))
            if status == "valid":
                records[entity["id"]] = {"id": entity["id"], "record_kind": "entity", "scope": entity["scope"],
                    "source_refs": deepcopy(entity["source_refs"]), "narrative_position": entity["narrative_position"],
                    "payload": {"name": entity["name"], "entity_type": entity["entity_type"], "identity_status": "unresolved"}}
            elif status == "stale":
                records.pop(entity["id"], None)
        for name in RECORD_GROUPS:
            for write in batch.get("update", {}).get(name, []):
                record = write.get("record", {})
                status = write.get("visibility") or ("stale" if batch.get("visibility") == "stale" else
                          visible(record) if visible and record else batch.get("visibility", "valid"))
                prior = record or records.get(write["id"], {})
                if name == "links" and prior.get("payload", {}).get("relation_type") == "required_context":
                    if status in {"stale", "future"}:
                        unavailable[write["id"]] = prior["payload"]["subject_ref"]["id"]
                    else:
                        unavailable.pop(write["id"], None)
                if status == "future":
                    continue
                if status == "stale" or write["op"] == "retire":
                    records.pop(write["id"], None)
                else:
                    records[write["id"]] = deepcopy(record)
    if dependency_gaps is not None:
        for subject in unavailable.values():
            if subject in records:
                dependency_gaps.setdefault(subject, []).append("必要关系来源不可用")
    for row in records.values():
        if row["record_kind"] == "link":
            continue
        row.update(entity_refs=[], state_refs=[], event_line_refs=[])
    for row in records.values():
        if row["record_kind"] != "link":
            continue
        payload = row["payload"]
        left, right = payload["subject_ref"], payload["object_ref"]
        if left["id"] not in records:
            continue
        field = {"involves": "entity_refs", "uses_state": "state_refs", "belongs_to": "event_line_refs"}.get(payload["relation_type"])
        if field and right not in records[left["id"]][field]:
            records[left["id"]][field].append(right)
    return records


def is_author_material(record: dict) -> bool:
    """依赖：已规范的nature/SourceRef。输入：记录或状态节点。输出：是否仅作者材料。实现：识别author_plan或非空纯author_input来源，不猜空来源性质。"""
    refs = record.get("source_refs", [])
    return record.get("payload", {}).get("nature") == "author_plan" or bool(refs and all(ref["kind"] == "author_input" for ref in refs))


def visible_adjacency(records: dict[str, dict]) -> dict[str, set[str]]:
    """依赖：可见records/is_author_material。输入：来源过滤后记录。输出：有界扩展邻接。实现：仅两端存在且非作者材料的Link入图，绝不经计划桥。"""
    adjacency = {key: set() for key in records}
    for record in records.values():
        if record["record_kind"] != "link":
            continue
        if is_author_material(record):
            continue
        payload = record["payload"]
        left, right = payload["subject_ref"]["id"], payload["object_ref"]["id"]
        if left not in records or right not in records:
            continue
        if any(is_author_material(records[key]) for key in (left, right)):
            continue
        adjacency[left].add(right)
        adjacency[right].add(left)
    return adjacency
