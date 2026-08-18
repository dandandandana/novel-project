"""Public API functions for importing documents into the RAG library."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .types import RagImportError, ImportPreview, ImportResult
from .helpers import (
    _ids,
    _import_text,
    _prepare_text,
    _validate_roots,
    _version,
)


def preview_upload(
    source: Path,
    *,
    library_root: Path,
    index_root: Path,
    story_id: str,
    timeline_id: str,
    expected_type: str | None = None,
    version: str | None = None,
    supersedes: str | Sequence[str] | None = None,
    document_family: str | None = None,
) -> ImportPreview:
    source = Path(source)
    if not source.is_file() or source.suffix.lower() not in {".yaml", ".yml"}:
        raise RagImportError("RAG 上传文件必须是现有的 YAML/YML 文件")
    try:
        text = source.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise RagImportError(f"无法读取上传文件: {exc}") from exc
    library, index = _validate_roots(library_root, index_root)
    return _prepare_text(
        text, source_path=source.resolve(), library_root=library, index_root=index,
        story_id=story_id, timeline_id=timeline_id, expected_type=expected_type,
        version=version, supersedes=supersedes, document_family=document_family,
    ).preview


def preview_rag_yaml(source: Path, **kwargs: Any) -> ImportPreview:
    return preview_upload(source, **kwargs)


def import_rag_yaml(
    source: Path,
    *,
    library_root: Path,
    index_root: Path,
    story_id: str,
    timeline_id: str,
    version: str | None = None,
    supersedes: str | Sequence[str] | None = None,
    document_family: str | None = None,
) -> ImportResult:
    source = Path(source)
    if not source.is_file() or source.suffix.lower() not in {".yaml", ".yml"}:
        raise RagImportError("RAG 上传文件必须是现有的 YAML/YML 文件")
    try:
        text = source.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise RagImportError(f"无法读取上传文件: {exc}") from exc
    return _import_text(
        text, source_path=source.resolve(), library_root=library_root, index_root=index_root,
        story_id=story_id, timeline_id=timeline_id, version=version,
        supersedes=supersedes, document_family=document_family,
    )


def import_outline(
    source: Path,
    *,
    library_root: Path,
    index_root: Path,
    story_id: str,
    timeline_id: str,
    title: str,
    volume: int,
    chapter: int,
    version: str | None = None,
    supersedes: str | Sequence[str] | None = None,
    document_family: str | None = None,
) -> ImportResult:
    source = Path(source)
    if not source.is_file():
        raise RagImportError(f"大纲文件不存在: {source}")
    try:
        text = source.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError) as exc:
        raise RagImportError(f"无法读取大纲: {exc}") from exc
    if not text:
        raise RagImportError("大纲文件为空")
    if source.suffix.lower() in {".yaml", ".yml"}:
        try:
            value = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise RagImportError(f"无法读取大纲 YAML: {exc}") from exc
        if isinstance(value, Mapping) and isinstance(value.get("metadata"), Mapping):
            return _import_text(
                text, source_path=source.resolve(), library_root=library_root, index_root=index_root,
                story_id=story_id, timeline_id=timeline_id, expected_type="outline",
                version=version, supersedes=supersedes, document_family=document_family,
            )
    if volume < 0 or chapter < 1:
        raise RagImportError("volume 不得小于 0，chapter 必须大于 0")
    selected_version = _version(version or "1.0")
    family = document_family or f"outline-{story_id}-{timeline_id}-v{volume:02d}-c{chapter:03d}"
    document_id = f"{family}-v{selected_version}"
    data: dict[str, Any] = {
        "metadata": {
            "document_id": document_id, "document_family": family,
            "story_id": story_id, "timeline_id": timeline_id, "document_type": "outline",
            "title": title, "outline_level": "chapter", "volume": volume, "chapter": chapter,
            "version": selected_version, "status": "active", "supersedes": None,
            "source_file": str(source.resolve()),
        },
        "outline": {
            "opening_state": "", "required_events": [text], "required_order": [],
            "required_dialogue": [], "required_images": [], "forbidden_reveals": [],
            "required_result": "", "ending_state": "", "future_hooks": [],
        },
    }
    if supersedes is not None:
        previous = _ids(supersedes)
        data["metadata"]["supersedes"] = previous[0] if len(previous) == 1 else (previous or None)
    serialized = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)
    return _import_text(
        serialized, source_path=source.resolve(), library_root=library_root, index_root=index_root,
        story_id=story_id, timeline_id=timeline_id, expected_type="outline",
        version=selected_version, supersedes=supersedes, document_family=family,
    )


def preview_outline(
    source: Path,
    *,
    library_root: Path,
    index_root: Path,
    story_id: str,
    timeline_id: str,
    title: str,
    volume: int,
    chapter: int,
    version: str | None = None,
    supersedes: str | Sequence[str] | None = None,
    document_family: str | None = None,
) -> ImportPreview:
    """预览文本或 YAML 大纲，不写入文库、不重建索引。"""
    source = Path(source)
    if not source.is_file():
        raise RagImportError(f"大纲文件不存在: {source}")
    try:
        text = source.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError) as exc:
        raise RagImportError(f"无法读取大纲: {exc}") from exc
    if not text:
        raise RagImportError("大纲文件为空")
    if volume < 0 or chapter < 1:
        raise RagImportError("volume 不得小于 0，chapter 必须大于 0")
    if source.suffix.lower() in {".yaml", ".yml"}:
        try:
            value = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise RagImportError(f"无法读取大纲 YAML: {exc}") from exc
        if isinstance(value, Mapping) and isinstance(value.get("metadata"), Mapping):
            return preview_upload(
                source, library_root=library_root, index_root=index_root,
                story_id=story_id, timeline_id=timeline_id, expected_type="outline",
                version=version, supersedes=supersedes, document_family=document_family,
            )
    selected_version = _version(version or "1.0")
    family = document_family or f"outline-{story_id}-{timeline_id}-v{volume:02d}-c{chapter:03d}"
    data: dict[str, Any] = {
        "metadata": {
            "document_id": f"{family}-v{selected_version}", "document_family": family,
            "story_id": story_id, "timeline_id": timeline_id, "document_type": "outline",
            "title": title, "outline_level": "chapter", "volume": volume, "chapter": chapter,
            "version": selected_version, "status": "active", "supersedes": None,
            "source_file": str(source.resolve()),
        },
        "outline": {
            "opening_state": "", "required_events": [text], "required_order": [],
            "required_dialogue": [], "required_images": [], "forbidden_reveals": [],
            "required_result": "", "ending_state": "", "future_hooks": [],
        },
    }
    previous = _ids(supersedes)
    data["metadata"]["supersedes"] = previous[0] if len(previous) == 1 else (previous or None)
    serialized = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)
    library, index = _validate_roots(library_root, index_root)
    return _prepare_text(
        serialized, source_path=source.resolve(), library_root=library, index_root=index,
        story_id=story_id, timeline_id=timeline_id, expected_type="outline",
        version=selected_version, supersedes=previous, document_family=family,
    ).preview


preview_import_outline = preview_outline