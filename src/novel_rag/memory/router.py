"""有界图展开与完整参考包；默认无 token 上限，无模型或通道配额。"""
from __future__ import annotations

from collections import deque
from typing import Iterable

from ..std.serialization import json_text
from ..std.hashing import fingerprint_bytes
from ..retrieval.assembler import estimate_tokens
from ..retrieval.service import safe_query_terms
from .graph import is_author_material, visible_adjacency


def route(records: dict[str, dict], state_entries: Iterable[dict], *, focus: Iterable[str] = (),
          query: str = "", available_tokens: int | None = None, max_hops: int = 2,
          max_nodes: int = 64, max_dependency_nodes: int = 16,
          blocked_dependencies: dict[str, list[str]] | None = None,
          ended_entries: Iterable[dict] = (), candidate_search: dict | None = None, browse_all: bool = False) -> dict:
    """依赖：可见图、候选与依赖策略。输入：焦点/词项、搜索游标、容量及浏览标志。输出：完整包、理由、缺口和进度。实现：准备可见记录后依次分页、收集依赖包、按显式容量选择。"""
    nodes, links = {}, {}
    for key, row in records.items():
        if row["record_kind"] == "link":
            links[key] = row
        else:
            nodes[key] = row
    states = {row["entry_id"]: row for row in state_entries}
    nodes.update((key, {"id": key, "record_kind": "state", "payload": row, "source_refs": row.get("source_refs", [])})
                 for key, row in states.items())
    for receipt in ended_entries:
        nodes.setdefault(receipt["entry_id"], {"id": receipt["entry_id"], "record_kind": "state_receipt",
                         "payload": receipt, "source_refs": receipt.get("source_refs", [])})
    targets = set(focus)
    authors = {key for key, row in nodes.items() if is_author_material(row)}
    open_conditions = {key for key, row in states.items() if row.get("domain") == "OpenCondition"}
    clues = ({key for key, row in nodes.items() if row["record_kind"] == "hook"} | open_conditions) - authors
    involved, required, author_dependencies = set(), {}, {}
    for row in links.values():
        payload = row["payload"]
        left, right = payload["subject_ref"]["id"], payload["object_ref"]["id"]
        relation = payload["relation_type"]
        if (relation == "involves" and right in targets and left in nodes and
                left not in authors and not is_author_material(row)):
            involved.add(left)
        elif relation == "required_context":
            dependencies = author_dependencies if is_author_material(row) else required
            dependencies.setdefault(left, set()).add(right)
    roots = _candidate_roots(nodes, targets, query, involved, clues, authors, browse_all)
    search_scope = {"focus": sorted(targets), "query": query}
    search_hash = None
    if len(nodes) > max_nodes or candidate_search is not None:
        search_input = {"nodes": nodes, "node_order": list(nodes), "links": links, **search_scope,
                        "limits": [max_nodes, max_hops, max_dependency_nodes],
                        "blocked_dependencies": blocked_dependencies}
        if browse_all:
            search_input["browse_all"] = True
        search_hash = fingerprint_bytes(json_text(search_input).encode("utf-8"))
    candidates, navigation, gaps = _candidate_page(
        nodes, visible_adjacency(records | nodes), roots, search_scope, search_hash,
        max_nodes=max_nodes, max_hops=max_hops, cursor=candidate_search, browse_all=browse_all,
    )
    packs = _complete_packs(nodes, candidates, authors, required, author_dependencies,
                            blocked_dependencies or {}, max_dependency_nodes, gaps)
    pending_roots = open_conditions & roots.keys()
    if available_tokens is None:
        result = _unbounded_selection(nodes, packs, candidates, roots, pending_roots, gaps)
    else:
        result = _budgeted_selection(nodes, packs, candidates, roots, pending_roots, gaps,
                                     max_hops, available_tokens)
    result.update(navigation)
    return result


def _candidate_roots(nodes: dict[str, dict], targets: set[str], query: str, involved: set[str],
                     clues: set[str], authors: set[str], browse_all: bool) -> dict[str, str]:
    """依赖：原查询词项与有效线索。输入：可见节点、焦点、关联与作者浏览边界。输出：按访问优先级排列的根及选择理由。实现：每个待匹配payload只序列化一次，保留原发现和兜底。"""
    direct = set(involved)
    lexical = set()
    terms = safe_query_terms(query.casefold())
    for key, row in nodes.items():
        payload = row.get("payload", {})
        if key in direct or key in targets or payload.get("holder") in targets or payload.get("target") in targets:
            direct.add(key)
        elif terms:
            searchable = json_text(payload).casefold()
            if any(term in searchable for term in terms):
                lexical.add(key)
    seeds = direct | lexical
    discovery = clues - seeds if not targets else set()
    seeds.update(discovery)
    if browse_all:
        seeds.update(nodes)
    fallback = not seeds
    if fallback and not targets:
        seeds.update([key for key in nodes if key not in authors][-8:])
    priority = sorted((key for key in nodes if key in seeds),
                      key=lambda key: (key not in direct, key not in clues, key in discovery))
    match_reason = "兜底入口" if fallback else "直接匹配"
    return {key: "线索候选（未确认对应）" if key in discovery else match_reason for key in priority}


def _candidate_page(nodes: dict[str, dict], adjacency: dict[str, set[str]], roots: dict[str, str],
                    search_scope: dict, search_hash: str | None, *, max_nodes: int, max_hops: int,
                    cursor: dict | None, browse_all: bool) -> tuple[dict[str, int], dict, list[str]]:
    """依赖：可见邻接与旧候选游标。输入：有序根、查询身份及访问上限。输出：本批距离、原形状进度和遍历缺口。实现：校验或初始化frontier后有界BFS并保留未访问顺序。"""
    candidates = {}
    if cursor is None:
        queue = deque((key, 0) for key in roots)
        hop_omissions, visited = set(), set()
    else:
        if cursor.get("search_hash") != search_hash:
            raise ValueError("snapshot_stale: 候选图/查询输入已改变，请重新recall")
        frontier, previous = cursor.get("frontier"), cursor.get("visited_ids")
        if (not isinstance(frontier, list) or not isinstance(previous, list) or
                any(type(key) is not str or key not in nodes for key in previous) or
                any(not isinstance(row, list) or len(row) != 2 or type(row[0]) is not str or row[0] not in nodes or
                    type(row[1]) is not int or not 0 <= row[1] <= max_hops for row in frontier)):
            raise ValueError("source_invalid: 原候选frontier形状错误")
        queue, visited = deque((key, distance) for key, distance in frontier), set(previous)
        hop_omissions = set(cursor.get("hop_omissions", []))
    while queue and len(candidates) < max_nodes:
        key, distance = queue.popleft()
        if key in visited or key not in nodes:
            continue
        visited.add(key)
        candidates[key] = distance
        if distance < max_hops:
            queue.extend((neighbor, distance + 1) for neighbor in sorted(adjacency.get(key, ())))
        else:
            hop_omissions.update(adjacency.get(key, ()))
    frontier = {}
    for key, distance in queue:
        if key not in visited and key in nodes:
            frontier.setdefault(key, distance)
    navigation, gaps = {}, []
    if frontier or cursor is not None or browse_all:
        navigation = {"candidate_search_state": {"search_hash": search_hash, **search_scope,
            "visited_ids": sorted(visited), "frontier": [[key, distance] for key, distance in frontier.items()],
            "hop_omissions": sorted(hop_omissions)},
            "candidate_search": {"visited_count": len(visited), "page_visited_count": len(candidates),
            "remaining_frontier_count": len(frontier), "complete": not frontier,
            "scope": "本次查询和跳数边界内的候选；依赖/容量缺口另列，不代表全图语义穷尽"}}
    if frontier:
        gaps.append(f"候选访问上限{max_nodes}：还有{len(frontier)}项未访问，不表示没有记录")
    if hop_omissions - visited:
        gaps.append(f"关联跳数上限{max_hops}：有相关入口未展开")
    return candidates, navigation, gaps


def _complete_packs(nodes: dict[str, dict], candidates: dict[str, int], authors: set[str],
                    required: dict[str, set[str]], author_dependencies: dict[str, set[str]],
                    blocked: dict[str, list[str]], max_nodes: int, gaps: list[str]) -> dict[str, set[str]]:
    """依赖：必要边、来源缺口及作者材料判定。输入：候选距离、依赖节点上限与缺口列表。输出：完整包ID集合并追加拒绝原因。实现：按候选距离沿必要边有界收集。"""
    packs = {}
    for key in sorted(candidates, key=lambda item: (candidates[item], item)):
        pack, pending, missing = set(), [key], []
        while pending:
            node = pending.pop()
            if node in pack:
                continue
            if node not in nodes:
                missing.append(node)
                continue
            if node != key and node in authors:
                missing.append("必要上下文属于作者材料，不构成事实前提")
                continue
            pack.add(node)
            missing.extend(blocked.get(node, []))
            if len(pack) > max_nodes:
                missing.append("必要依赖过长")
                break
            if node in authors:
                if required.get(node) or author_dependencies.get(node):
                    gaps.append(f"{key}: 作者材料仅作孤立参考，必要关系不扩展事实")
                continue
            if author_dependencies.get(node):
                missing.append("必要关系属于作者材料，不构成事实前提")
            pending.extend(sorted(required.get(node, ()), reverse=True))
        if missing:
            gaps.append(f"{key}: 必要上下文缺失 {', '.join(missing)}")
            continue
        packs[key] = pack
    return packs


def _project_pack(key: str, pack: set[str], nodes: dict[str, dict],
                  roots: dict[str, str]) -> tuple[dict[str, dict], dict]:
    """依赖：完整依赖集合与根理由。输入：候选ID、包、可见节点及查询根。输出：有序记录和原格式理由。实现：按ID一次投影，记录与理由共用顺序。"""
    ordered = sorted(pack)
    return ({node: nodes[node] for node in ordered},
            {"record_id": key, "reason": roots.get(key, "可见关联"), "pack_ids": ordered})


def _unbounded_selection(nodes: dict[str, dict], packs: dict[str, set[str]], candidates: dict[str, int],
                         roots: dict[str, str], pending_roots: set[str], gaps: list[str]) -> dict:
    """依赖：完整包与候选顺序。输入：包、候选距离、根与缺口。输出：默认无显式预算的参考包。实现：Pending根优先，按原距离和ID合并新包，去重共享依赖。"""
    selected, reasons = {}, []
    ordered = sorted(packs, key=lambda key: (key not in pending_roots, candidates[key], key not in roots, key))
    for key in ordered:
        pack = packs[key]
        if pack <= selected.keys():
            continue
        rows, reason = _project_pack(key, pack, nodes, roots)
        selected.update(rows)
        reasons.append(reason)
    return _reference_packet(selected, gaps + _query_gaps(len(nodes), selected), reasons)


def _budgeted_selection(nodes: dict[str, dict], packs: dict[str, set[str]], candidates: dict[str, int],
                        roots: dict[str, str], pending_roots: set[str], gaps: list[str],
                        max_hops: int, available_tokens: int) -> dict:
    """依赖：原token估算与完整包。输入：包、访问优先级、缺口及显式容量。输出：预算内参考内容及省略计数。实现：按新增收益/完整序列化成本贪心，缺口超出容量时沿原规则整包回退。"""
    selected, reasons = {}, []
    projections = {key: _project_pack(key, pack, nodes, roots) for key, pack in packs.items()}
    while packs:
        options = []
        baseline = estimate_tokens(json_text(_reference_packet(selected, gaps, reasons)))
        for key, pack in packs.items():
            fresh = pack - selected.keys()
            if not fresh:
                continue
            rows, reason = projections[key]
            proposed = selected | rows
            cost = estimate_tokens(json_text(_reference_packet(proposed, gaps, reasons + [reason])))
            if cost > available_tokens:
                continue
            # 保留旧集合差的累加顺序，避免浮点尾差改变同成本候选排序。
            benefit = sum(2 if node in roots else 1 / (candidates.get(node, max_hops) + 1) for node in fresh)
            priority = not pending_roots.isdisjoint(fresh)
            options.append((-int(priority), -benefit / max(1, cost - baseline), key, proposed, reason))
        if not options:
            gaps.extend(f"{key}: 整包超过参考预算，可读取原文来源"
                        for key, pack in packs.items() if not pack <= selected.keys())
            break
        _, _, key, selected, reason = min(options, key=lambda option: option[:3])
        reasons.append(reason)
        packs.pop(key)
    result = _reference_packet(selected, gaps + _query_gaps(len(nodes), selected), reasons)
    # 缺口说明也计入预算；退最后整个包并保留有界缺口，不截正文条件。
    while reasons and estimate_tokens(json_text(result)) > available_tokens:
        reasons.pop()
        keep = {node for reason in reasons for node in reason["pack_ids"]}
        selected = {key: value for key, value in selected.items() if key in keep}
        result = _reference_packet(selected, gaps + _query_gaps(len(nodes), selected), reasons)
    omitted = 0
    while result["gaps"] and estimate_tokens(json_text(result)) > available_tokens:
        result["gaps"].pop()
        omitted += 1
    if omitted:
        result["omitted_gap_count"] = omitted
    return result


def _query_gaps(node_count: int, selected: dict[str, dict]) -> list[str]:
    """依赖：选择仅包含可见节点。输入：可见节点总数和最终选择。输出：查询未选缺口。实现：只报告数量，未选不等于无记录。"""
    omitted = node_count - len(selected)
    return [f"{omitted}项可见记录未被本次查询选入；不相关或访问/依赖/容量限制，不表示没有记录"] if omitted else []


def _reference_packet(selected: dict[str, dict], gaps: list[str], reasons: list[dict]) -> dict:
    """依赖：有序选中节点与原公开字段。输入：去重ID映射、缺口与理由。输出：可序列化参考包。实现：按原类别投影记录并统一收集来源，供交付与预算比较使用。"""
    result = {"event_lines": [], "experiences": [], "hooks": [], "notes": [], "state_entries": [], "source_refs": []}
    names = {"event_line": "event_lines", "experience": "experiences", "hook": "hooks", "note": "notes"}
    for value in selected.values():
        kind = value.get("record_kind")
        if kind == "entity":
            result.setdefault("entity_refs", []).append(dict(value["payload"], entity_id=value["id"]))
        elif kind == "state_receipt":
            result.setdefault("state_receipts", []).append(value["payload"])
        else:
            result[names.get(kind, "state_entries")].append(value["payload"] if kind == "state" else value)
        for ref in value.get("source_refs", []):
            if ref not in result["source_refs"]:
                result["source_refs"].append(ref)
    result.update(gaps=gaps, selection_reasons=reasons)
    return result
