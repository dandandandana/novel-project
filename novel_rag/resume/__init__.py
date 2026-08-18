"""Safe continuation of a generation that asks the author for guidance.

The generation runtime is an immutable proposal until ``confirm`` migrates it
to canon.  A continuation therefore creates a child runtime instead of
editing the parent in place.  The child reuses :func:`novel_rag.generation.generate`
so all normal normalization, CPM/state chaining, validation and repair limits
remain in one pipeline.

The package is split by responsibility: ``types`` holds the error type,
``helpers`` holds the filesystem and validation utilities, and
``continuation`` holds the :func:`continue_generation` and
:func:`resume_generation` entry points.
"""

from __future__ import annotations

from .types import ResumeError
from .continuation import continue_generation, resume_generation

__all__ = ["ResumeError", "continue_generation", "resume_generation"]