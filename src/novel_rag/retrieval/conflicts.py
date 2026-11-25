"""Conflict detection for retrieved evidence.

The guard groups candidates by fact type, timeline, and valid time, then
reports contradictory content together with status/authority/version
provenance.  It never resolves a conflict by comparing scores across
channels.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .types import ContextConflict, Evidence


def _content_key(item: Evidence) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    return item.content.strip(), item.entity_ids, item.relation_path


def _stable_evidence_key(item: Evidence) -> tuple[str, str, str, str, str]:
    return (
        item.document_id,
        item.channel.value,
        item.source_version or "",
        item.source_fingerprint or "",
        item.content.strip(),
    )


class ConflictGuard:
    """Detect unresolved contradictions without selecting a winner."""

    def detect(
        self,
        evidence: Iterable[Evidence],
        *,
        timeline_id: str | None = None,
    ) -> tuple[ContextConflict, ...]:
        groups: dict[tuple[str, str | None, str | None], list[Evidence]] = defaultdict(list)
        for item in evidence:
            # A missing fact_type is a recall item, not a claim that can be
            # safely compared with every other untyped recall item.
            if item.fact_type in (None, ""):
                continue
            effective_timeline = item.timeline_id if item.timeline_id is not None else timeline_id
            groups[(item.fact_type, effective_timeline, item.valid_at)].append(item)

        conflicts: list[ContextConflict] = []
        for (fact_type, group_timeline, valid_at), candidates in sorted(
            groups.items(), key=lambda pair: tuple(value or "" for value in pair[0])
        ):
            unique_contents = {_content_key(item) for item in candidates}
            if len(unique_contents) <= 1:
                continue
            ordered = tuple(sorted(candidates, key=_stable_evidence_key))
            differing_fields = ["content"]
            if len({item.status for item in candidates}) > 1:
                differing_fields.append("status")
            if len({item.authority for item in candidates}) > 1:
                differing_fields.append("authority")
            if len({item.source_version for item in candidates}) > 1:
                differing_fields.append("source_version")
            status_values = sorted({item.status or "<none>" for item in candidates})
            authority_values = sorted({item.authority for item in candidates})
            versions = sorted({item.source_version or "<none>" for item in candidates})
            reason = (
                "同一事实键存在内容冲突："
                f"fact_type={fact_type!r}, timeline_id={group_timeline!r}, valid_at={valid_at!r}；"
                f"status={status_values}, authority={authority_values}, "
                f"source_version={versions}。ConflictGuard 不按跨通道分数自动选边。"
            )
            conflicts.append(
                ContextConflict(
                    fact_type=fact_type,
                    timeline_id=group_timeline,
                    valid_at=valid_at,
                    evidence=ordered,
                    reason=reason,
                    differing_fields=tuple(differing_fields),
                )
            )
        return tuple(conflicts)

    # ``check`` is a readable alias for callers that use guard/check wording.
    def check(
        self,
        evidence: Iterable[Evidence],
        *,
        timeline_id: str | None = None,
    ) -> tuple[ContextConflict, ...]:
        return self.detect(evidence, timeline_id=timeline_id)


def detect_conflicts(
    evidence: Iterable[Evidence],
    *,
    timeline_id: str | None = None,
) -> tuple[ContextConflict, ...]:
    """Functional convenience wrapper around :class:`ConflictGuard`."""

    return ConflictGuard().detect(evidence, timeline_id=timeline_id)
