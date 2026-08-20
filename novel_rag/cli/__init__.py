"""Command-line interface for novel-rag."""

from __future__ import annotations

from .arguments import build_parser
from .commands import (
    command_validate,
    command_index,
    command_search,
    command_list_stories,
    command_create_story,
    command_generate,
    command_continue,
    command_init_preferences,
    command_confirm,
    command_state_review,
    command_state_approve,
    command_state_reject,
    command_import_rag,
    command_import_outline,
    command_feedback_create,
    command_feedback_list,
    command_feedback_resolve,
    command_api_config,
    command_tui,
    command_doctor,
    command_summary,
    command_pending,
)
from .helpers import _model_from_args, _paths, _add_model_arguments

__all__ = [
    "build_parser",
    "main",
    "_model_from_args",
    "_paths",
    "_add_model_arguments",
    "command_validate",
    "command_index",
    "command_search",
    "command_list_stories",
    "command_create_story",
    "command_generate",
    "command_continue",
    "command_init_preferences",
    "command_confirm",
    "command_state_review",
    "command_state_approve",
    "command_state_reject",
    "command_import_rag",
    "command_import_outline",
    "command_feedback_create",
    "command_feedback_list",
    "command_feedback_resolve",
    "command_api_config",
    "command_tui",
    "command_doctor",
    "command_summary",
    "command_pending",
]


def main() -> int:
    import sys
    from .arguments import build_parser
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":  # python -m novel_rag.cli
    raise SystemExit(main())
