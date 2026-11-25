"""Compatibility shim: re-exports from the ``importers`` package."""

from __future__ import annotations

from .importers.types import RagImportError, ImportPreview, ImportResult
from .importers.helpers import _ids, _import_text, _safe_name, _validate_identity, _validate_roots
from .importers.importer import (
    preview_upload,
    preview_rag_yaml,
    import_rag_yaml,
    import_outline,
    preview_outline,
    preview_import_outline,
)

__all__ = [
    "RagImportError",
    "ImportPreview",
    "ImportResult",
    "preview_upload",
    "preview_rag_yaml",
    "import_rag_yaml",
    "import_outline",
    "preview_outline",
    "preview_import_outline",
    "_ids",
    "_import_text",
    "_safe_name",
    "_validate_identity",
    "_validate_roots",
]