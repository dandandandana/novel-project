"""Compatibility shim: re-exports from the ``cli`` package."""

from __future__ import annotations

import sys

from .cli.arguments import build_parser
from .cli.commands import (
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
)
from .cli.helpers import _model_from_args, _paths, _add_model_arguments


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args()
    return args.func(args)


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
]