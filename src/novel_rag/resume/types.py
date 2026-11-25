"""Error type for the resume/continuation step."""

from __future__ import annotations

from ..generation import GenerationError


class ResumeError(GenerationError):
    """Raised when a runtime cannot safely be continued."""