"""Compatibility shim: re-exports from the ``writeback`` package."""

from __future__ import annotations

from .writeback.types import WritebackError, WritebackResult
from .writeback.helpers import _atomic_text, _read_json, _retrieval_tests
from .writeback.confirm import confirm_runtime

__all__ = [
    "WritebackError",
    "WritebackResult",
    "confirm_runtime",
    "_atomic_text",
    "_read_json",
    "_retrieval_tests",
]
