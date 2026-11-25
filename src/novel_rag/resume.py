"""Compatibility shim: re-exports from the ``resume`` package."""

from __future__ import annotations

from .resume.types import ResumeError
from .resume.continuation import continue_generation, resume_generation

__all__ = ["ResumeError", "continue_generation", "resume_generation"]