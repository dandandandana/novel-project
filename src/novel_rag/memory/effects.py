"""记忆来源失效的纯策略；原子提交与版本落盘仍由唯一DraftStore负责。"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass

from ..contracts.references import DocumentRef


@dataclass(frozen=True)
class DraftMemoryEffect:
    """依赖：纯dataclass。输入：失效检查点及可选签名。输出：保存草稿的记忆影响。实现：只传递决策，不修改运行或推进版本。"""

    invalidated_checkpoints: tuple[str, ...]
    effect_signature: dict | None


def draft_selection_effect(previous_text: str, selected_text: str, drafts: dict,
                           batches: list[dict], previous_signature: dict | None) -> DraftMemoryEffect:
    """依赖：原草稿前缀/批次合同。输入：新旧正文、检查点、批次与签名。输出：独立失效决策。实现：只失效原先覆盖且新稿不再覆盖的本run前缀，不改输入。"""
    invalidating = {source["checkpoint_id"] for batch in batches for source in batch["source_refs"]
                    if source.get("kind") == "draft" and source["checkpoint_id"] in drafts and
                    previous_text.startswith(drafts[source["checkpoint_id"]]["text"]) and
                    not selected_text.startswith(drafts[source["checkpoint_id"]]["text"])}
    signature = deepcopy(previous_signature) if isinstance(previous_signature, dict) else None
    if signature is not None:
        for checkpoint in invalidating:
            signature["draft:" + checkpoint] = "stale"
    return DraftMemoryEffect(tuple(sorted(invalidating)), signature)


def initial_memory_effect_invalid(baseline_source_refs: list[dict], source_refs: Mapping[str, DocumentRef],
                                  signature: dict, local_invalidations: list[str]) -> bool:
    """依赖：同次来源Ref/原本地失效标记。输入：基线、实际来源、签名和已计数检查点。输出：首次协调是否推进版本。实现：核来源hash及尚未计数的失效前缀，不修改输入。"""
    return any(source_refs.get(ref["document_id"]) is None or
               source_refs[ref["document_id"]].source_hash != ref["source_hash"]
               for ref in baseline_source_refs) or any(
        value == "stale" for key, value in signature.items()
        if key.startswith("draft:") and key[6:] not in local_invalidations
    )
