"""Versioned import of YAML documents (canon, outline, feedback) into the novel RAG library.

This package provides preview-then-commit import for YAML documents with
version tracking, conflict detection, and automatic index rebuild.
"""

from __future__ import annotations

from .types import RagImportError, ImportPreview, ImportResult
from .helpers import _ids, _import_text, _safe_name, _validate_identity, _validate_roots
from .importer import (
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