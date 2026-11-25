"""状态出口：顶行 / 输入前缀 / hint 行 segments（F1 事件驱动，无常驻 footer）。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..helpers import display_width, truncate_display
from .state import UiState


@dataclass(frozen=True)
class StatusSegment:
    id: str
    priority: int
    render: Callable[[UiState], str | None]
    min_width: int = 0


def top_line_segments(state: UiState) -> tuple[StatusSegment, ...]:
    workspace = state.workspace

    def _identity(_state: UiState) -> str:
        return "/".join(part for part in (workspace.story_id, workspace.timeline_id)
                        if part) or "未选择作品"

    def _badge(current: UiState) -> str | None:
        return f"[{current.unread}]" if current.unread else None

    return (
        StatusSegment(id="workspace", priority=0, min_width=8, render=_identity),
        StatusSegment(id="notifications", priority=1, render=_badge),
    )


def render_top_line(state: UiState, width: int) -> str:
    parts = [text for segment in top_line_segments(state)
             if (text := segment.render(state))]
    if not parts:
        return ""
    tail_text = "  ".join(parts[1:])
    head_budget = width - display_width(tail_text) - (2 if tail_text else 0)
    head = truncate_display(parts[0], max(1, head_budget))
    return head + ("  " + tail_text if tail_text else "")


def input_prefix(state: UiState) -> str:
    jobs = state.active_jobs
    if not jobs:
        return ": "
    job = jobs[-1]
    if len(jobs) > 1:
        return f"[●×{len(jobs)}]: "
    return f"[●{job.kind} {job.elapsed_s:.0f}s]: "


_HINT_KEYS = ("gen cont confirm review upload rebuild search summary pending "
              "stories api feedback info procs tasks help :q")


def hint_segments() -> tuple[StatusSegment, ...]:
    def _keys(_state: UiState) -> str:
        return _HINT_KEYS

    def _profile(state: UiState) -> str | None:
        profile = state.workspace.model_profile
        return f"profile:{profile}" if profile else None

    def _jobs(state: UiState) -> str | None:
        count = len(state.active_jobs)
        return f"后台 {count}" if count else None

    return (
        StatusSegment(id="jobs", priority=0, min_width=60, render=_jobs),
        StatusSegment(id="profile", priority=2, min_width=100, render=_profile),
        StatusSegment(id="keys", priority=1, render=_keys),
    )


def render_hint(state: UiState, width: int) -> str:
    ordered = sorted(hint_segments(), key=lambda segment: segment.priority)
    chosen: list[str] = []
    used = 0
    for segment in ordered:
        text = segment.render(state)
        if not text or width < segment.min_width:
            continue
        cost = display_width(text) + (2 if chosen else 0)
        if used + cost <= width:
            chosen.append(text)
            used += cost
    if not chosen and width >= 8:
        keys = _HINT_KEYS[: max(8, width - 1)].rstrip()
        return keys
    return "  ".join(chosen)
