"""Stable retrieval contracts and framework-independent assembly logic.

The package deliberately has no SQLite, model, or application-layer imports.
Storage adapters and channel implementations can depend on these contracts,
while generation only needs the :class:`Retriever` protocol.
"""

from importlib import import_module as _import_module

_EXPORT_MODULES = {
    **dict.fromkeys(("BudgetExceeded", "ContextAssembler", "DEFAULT_CHANNEL_QUOTAS",
                     "DEFAULT_TOKEN_BUDGET", "estimate_tokens"), ".assembler"),
    **dict.fromkeys(("ConflictGuard", "detect_conflicts"), ".conflicts"),
    **dict.fromkeys(("GraphReader", "Retriever"), ".protocols"),
    **dict.fromkeys(("EvidenceNormalizer", "HybridRetriever", "RetrievalAmbiguityError",
                     "RetrievalConfigurationError", "RetrievalError", "RetrievalService",
                     "RetrieverService", "ServiceRetriever"), ".service"),
    **dict.fromkeys(("ChannelStats", "ContextBundle", "ContextConflict", "Evidence",
                     "EvidenceChannel", "RetrievalReceipt", "RetrievalRequest"), ".types"),
}


def __getattr__(name: str):
    """依赖：importlib与原检索owner。输入：兼容导出名。输出：原对象或AttributeError。实现：按名称首次导入并缓存，纯类型/assembler不加载服务。"""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(_import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """依赖：原命名空间与导出表。输入：无。输出：可发现名称。实现：合并已加载及惰性名称，不导入业务。"""
    return sorted(set(globals()) | set(_EXPORT_MODULES))

__all__ = [
    "BudgetExceeded",
    "ChannelStats",
    "ConflictGuard",
    "ContextAssembler",
    "ContextBundle",
    "ContextConflict",
    "detect_conflicts",
    "DEFAULT_CHANNEL_QUOTAS",
    "DEFAULT_TOKEN_BUDGET",
    "Evidence",
    "EvidenceChannel",
    "EvidenceNormalizer",
    "GraphReader",
    "HybridRetriever",
    "RetrievalAmbiguityError",
    "RetrievalConfigurationError",
    "RetrievalError",
    "RetrievalService",
    "Retriever",
    "RetrieverService",
    "RetrievalReceipt",
    "RetrievalRequest",
    "ServiceRetriever",
    "estimate_tokens",
]
