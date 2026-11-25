"""Errors shared by catalog and corpus validation."""

from __future__ import annotations

from collections.abc import Iterable


class CatalogError(ValueError):
    """Base error for invalid source-catalog data."""


class CatalogValidationError(CatalogError):
    """A validation error containing every discovered issue."""

    def __init__(self, issues: Iterable[str] | str):
        if isinstance(issues, str):
            values = (issues,)
        else:
            values = tuple(str(issue) for issue in issues if str(issue))
        self.issues = values
        super().__init__("；".join(values) if values else "catalog validation failed")


class CorpusValidationError(CatalogValidationError):
    """Raised when a corpus cannot be promoted to a validated corpus."""


class LayoutMappingError(CatalogError):
    """Raised when a source path is outside a supported layout."""


__all__ = [
    "CatalogError",
    "CatalogValidationError",
    "CorpusValidationError",
    "LayoutMappingError",
]
