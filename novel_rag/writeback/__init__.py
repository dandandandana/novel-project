"""Confirm a finished generation runtime into a canon History document.

The writeback step is the only path that migrates generated prose into the
library.  ``types`` holds the result/error dataclasses, ``helpers`` holds the
small filesystem and retrieval-regression utilities, and ``confirm`` holds
the validating, rollback-safe :func:`confirm_runtime` entry point.
"""

from __future__ import annotations

from .types import WritebackError, WritebackResult
from .helpers import _atomic_text, _read_json, _retrieval_tests
from .confirm import confirm_runtime

__all__ = [
    "WritebackError",
    "WritebackResult",
    "confirm_runtime",
    "_atomic_text",
    "_read_json",
    "_retrieval_tests",
]
