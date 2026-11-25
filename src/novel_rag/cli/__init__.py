"""Command-line interface for novel-rag."""

from __future__ import annotations

from importlib import import_module as _import_module

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


_EXPORT_MODULES = {
    "build_parser": ".arguments",
    **dict.fromkeys(("_model_from_args", "_paths", "_add_model_arguments"), ".helpers"),
    **dict.fromkeys((name for name in __all__ if name.startswith("command_")), ".commands"),
}


def __getattr__(name: str):
    """依赖：importlib与原CLI模块。输入：兼容导出名。输出：原函数或AttributeError。实现：首次按需加载并缓存，保留命令函数身份。"""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(_import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """依赖：命名空间与原导出表。输入：无。输出：可发现的CLI名称。实现：合并已加载和惰性名字，不提前装配命令。"""
    return sorted(set(globals()) | set(_EXPORT_MODULES))


def main() -> int:
    """依赖：原parser与命令函数。输入：进程argv。输出：命令退出码。实现：设置UTF-8后解析并调用已登记原函数。"""
    import sys
    from .arguments import build_parser
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":  # python -m novel_rag.cli
    raise SystemExit(main())
