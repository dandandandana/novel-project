"""v2兼容导出按需加载；导入v3纯类型或Store不装配旧生成管线。"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_MODULES = {
    "GenerationResult": "..generation_schema",
    **dict.fromkeys((
        "GenerationError", "PreferenceRequired", "Model", "STAGE_INSTRUCTIONS",
        "DocumentRef", "DraftRef", "AuthorInputRef", "NarrativeCursor", "RunBinding",
    ), ".types"),
    **dict.fromkeys((
        "author_preferences_path", "read_author_preferences", "build_contract",
        "retrieve_context_bundle", "retrieve_context", "build_reference_profiles",
        "load_scene_state", "execute_scene", "validate_draft", "_payload", "_safe_task_id",
    ), ".helpers"),
    **dict.fromkeys((
        "ContextItem", "LegacyRetrieverAdapter", "build_default_retriever",
        "build_legacy_retriever", "build_retrieval_request", "set_default_retriever_factory",
    ), ".retrieval"),
    "generate": ".pipeline",
}


def __getattr__(name: str) -> Any:
    """依赖：importlib和原实现。输入：兼容导出名。输出：原对象或AttributeError。实现：首次按owner导入并缓存，不复制业务函数。"""

    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """依赖：模块命名空间与导出表。输入：无。输出：可发现的兼容名称。实现：合并已加载与惰性名称，不触发业务导入。"""

    return sorted(set(globals()) | set(_EXPORT_MODULES))

__all__ = [
    "DocumentRef", "DraftRef", "AuthorInputRef", "NarrativeCursor", "RunBinding",
    "GenerationError",
    "PreferenceRequired",
    "Model",
    "GenerationResult",
    "author_preferences_path",
    "read_author_preferences",
    "build_contract",
    "retrieve_context_bundle",
    "retrieve_context",
    "build_reference_profiles",
    "load_scene_state",
    "execute_scene",
    "validate_draft",
    "_payload",
    "_safe_task_id",
    "ContextItem",
    "LegacyRetrieverAdapter",
    "build_default_retriever",
    "build_legacy_retriever",
    "build_retrieval_request",
    "set_default_retriever_factory",
    "generate",
]
