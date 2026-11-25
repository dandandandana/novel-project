"""Confirm a finished generation runtime into a canon History document.

The writeback step is the only path that migrates generated prose into the
library.  ``types`` holds the result/error dataclasses, ``helpers`` holds the
small filesystem and retrieval-regression utilities, and ``confirm`` holds
the validating, rollback-safe :func:`confirm_runtime` entry point.
"""

from __future__ import annotations

from importlib import import_module as _import_module

_EXPORT_MODULES = {
    **dict.fromkeys(("WritebackError", "WritebackResult"), ".types"),
    **dict.fromkeys(("_atomic_text", "_read_json", "_retrieval_tests"), ".helpers"),
    "confirm_runtime": ".confirm",
}


def __getattr__(name: str):
    """依赖：importlib与原采用owner。输入：兼容导出名。输出：原对象或AttributeError。实现：按需加载旧入口并缓存，v3 adopt不加载旧confirm。"""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(_import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """依赖：原命名空间与导出表。输入：无。输出：可发现名称。实现：合并已加载及惰性名称，不触发旧采用。"""
    return sorted(set(globals()) | set(_EXPORT_MODULES))

__all__ = [
    "WritebackError",
    "WritebackResult",
    "confirm_runtime",
    "_atomic_text",
    "_read_json",
    "_retrieval_tests",
]
