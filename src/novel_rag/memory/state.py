"""显式变化的唯一 reducer；不解释人物心理或批准正文。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


DOMAINS = {"World", "CharacterView", "OpenCondition"}


def reduce_state(batches: Iterable[dict], *, memory_revision: int = 0,
                 scope: dict | None = None, gaps: Iterable[str] = ()) -> dict[str, Any]:
    """依赖：规范化故事序批次。输入：批次/版本/缺口。输出：状态及结束来源回执。实现：Set/Clear/scene与失效共用回放，解除证据不携旧当前值。"""
    entries, ended, invalid, sources = {}, {}, set(), []
    reasons, recorded_through, count = list(gaps), None, 0
    for batch in batches:
        if batch.get("visibility") == "future":
            continue
        if batch.get("quarantine"):
            invalid.update(entries)
            entries.clear()
            ended.clear()
            reasons.append(f"{batch['batch_id']}: 缺少发布控制证据，基线未知")
        changes = batch.get("update", {}).get("state_changes", [])
        if any(ref.get("kind") in {"draft", "document"} for ref in batch.get("source_refs", [])):
            count += 1
        boundary = batch.get("update", {}).get("scene_boundary")
        if boundary and batch.get("boundary_visibility", batch.get("visibility", "valid")) != "future":
            if batch.get("boundary_visibility", batch.get("visibility")) == "stale":
                invalid.update(key for key, value in entries.items() if value["lifetime"] == "scene")
            else:
                for key, value in entries.items():
                    if value["lifetime"] == "scene":
                        ended[key] = {"entry_id": key, "effect": "scene_ended", "source_refs": batch["source_refs"],
                                      "narrative_position": batch.get("narrative_position")}
            entries = {key: value for key, value in entries.items() if value["lifetime"] != "scene"}
        for change in changes:
            entry_id = change["entry_id"]
            status = change.get("visibility", batch.get("visibility", "valid"))
            if status == "future":
                continue
            if status == "stale":
                entries.pop(entry_id, None)
                ended.pop(entry_id, None)
                invalid.add(entry_id)
                reasons.append(f"{entry_id}: 状态来源失效")
                continue
            if change["op"] == "clear":
                old = entries.pop(entry_id, None)
                refs = list(old.get("source_refs", [])) if old else []
                for ref in change.get("source_refs", batch.get("source_refs", [])):
                    if ref not in refs:
                        refs.append(ref)
                ended[entry_id] = {"entry_id": entry_id, "effect": "cleared", "source_refs": refs,
                                   "narrative_position": batch.get("narrative_position")}
            else:
                entries[entry_id] = deepcopy(change["entry"])
                ended.pop(entry_id, None)
            invalid.discard(entry_id)
        has_visible_change = any(change.get("visibility", batch.get("visibility", "valid")) == "valid" for change in changes)
        body_records = any(write.get("visibility", batch.get("visibility", "valid")) == "valid" and
                           any(ref.get("kind") in {"draft", "document"} for ref in write.get("record", write).get("source_refs", []))
                           for group in ("event_lines", "experiences", "hooks", "notes", "links")
                           for write in batch.get("update", {}).get(group, []))
        if (has_visible_change or body_records or boundary and batch.get("boundary_visibility", "valid") == "valid"):
            recorded_through = batch.get("narrative_position")
        for ref in batch.get("source_refs", []):
            if ref not in sources:
                sources.append(ref)
    active = list(entries.values())
    return {"state_revision": memory_revision, "scope": scope, "entries": active,
            "claims": [row for row in active if row["domain"] == "CharacterView" and row["kind"] == "claim"],
            "unknowns": sorted(invalid), "invalidated_keys": sorted(invalid),
            "ended_entries": list(ended.values()),
            "source_refs": sources, "recorded_through": recorded_through,
            "coverage": "unavailable" if not count else "partial" if reasons or invalid else "bound",
            "gaps": list(dict.fromkeys(reasons))}
