"""Private helper functions for import."""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from ..documents import RagDocument, registered_story_ids, validate_document
from ..index import rebuild_isolated_indexes, search_isolated
from ..layout import story_root
from ..service import load_valid_documents
from .types import (
    RagImportError,
    _DESTINATIONS,
    _SAFE_ID_RE,
    _VERSION_RE,
    _VERSION_SUFFIX_RE,
    ImportPreview,
    ImportResult,
    _PreparedImport,
)


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value)).strip(".-")
    if not cleaned:
        raise RagImportError("document_id 不能转换为安全文件名")
    return cleaned


def _version(value: Any, *, required: bool = True) -> str:
    text = str(value or "").strip()
    if not text and not required:
        return ""
    if not _VERSION_RE.fullmatch(text):
        raise RagImportError("version 必须是显式数字版本，例如 1.0 或 1.2.1")
    return text


def _ids(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    output: list[str] = []
    for item in values:
        text = str(item).strip()
        if text and text not in output:
            output.append(text)
    return output


def _family_from_id(document_id: str) -> str:
    family = _VERSION_SUFFIX_RE.sub("", document_id)
    return family or document_id


def _read_mapping(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return deepcopy(default or {})
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RagImportError(f"无法读取 YAML: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RagImportError(f"YAML 根节点必须是映射: {path}")
    return value


def _atomic_write(path: Path, text: str) -> None:
    if path.exists() and path.is_symlink():
        raise RagImportError(f"拒绝写入符号链接: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if temporary.exists() and temporary.is_symlink():
        raise RagImportError("refuse writing symlink temporary file")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _validate_roots(library_root: Path, index_root: Path | None) -> tuple[Path, Path]:
    library = library_root.resolve()
    index = (index_root or library / "index").resolve()
    expected = (library / "index").resolve()
    if index != expected:
        raise RagImportError("导入只允许重建当前知识库的 index 目录")
    return library, index


def _validate_identity(library_root: Path, story_id: str, timeline_id: str) -> Path:
    try:
        root = story_root(library_root.resolve(), story_id)
    except ValueError as exc:
        raise RagImportError(str(exc)) from exc
    if story_id not in registered_story_ids(library_root):
        raise RagImportError(f"未注册 story_id: {story_id}")
    registry = root / "registry" / "timelines.yaml"
    rows = _read_mapping(registry).get("timelines", [])
    if not isinstance(rows, list) or not any(
        isinstance(row, Mapping)
        and str(row.get("story_id")) == story_id
        and str(row.get("timeline_id")) == timeline_id
        for row in rows
    ):
        raise RagImportError(f"未注册 timeline_id: {story_id}/{timeline_id}")
    return root


def _parse_document(text: str, path: Path) -> tuple[dict[str, Any], RagDocument]:
    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RagImportError(f"无法读取 YAML: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("metadata"), dict):
        raise RagImportError("上传文档必须包含 metadata 映射")
    data = deepcopy(value)
    metadata = data["metadata"]
    body = {key: child for key, child in data.items() if key != "metadata"}
    document = RagDocument(path=path, metadata=metadata, body=body)
    errors = validate_document(document)
    if errors:
        raise RagImportError("；".join(errors))
    return data, document


def _version_rows(version_map_path: Path) -> list[dict[str, Any]]:
    value = _read_mapping(version_map_path, {"versions": []})
    rows = value.get("versions", [])
    if not isinstance(rows, list):
        raise RagImportError(f"versions 必须是列表: {version_map_path}")
    if any(not isinstance(row, Mapping) for row in rows):
        raise RagImportError(f"version-map entries must be mappings: {version_map_path}")
    return [dict(row) for row in rows]


def _row_ids(row: Mapping[str, Any]) -> list[str]:
    return list(dict.fromkeys(_ids(row.get("current")) + _ids(row.get("supersedes"))))


def _find_family_row(rows: Sequence[Mapping[str, Any]], family: str, ids: Sequence[str]) -> dict[str, Any] | None:
    wanted = set(ids)
    for row in rows:
        if str(row.get("document_family") or "") == family:
            return dict(row)
        if wanted.intersection(_row_ids(row)):
            return dict(row)
    return None


def _replace_version(document_id: str, version: str) -> str:
    if _VERSION_SUFFIX_RE.search(document_id):
        return _VERSION_SUFFIX_RE.sub(f"-v{version}", document_id)
    return f"{document_id}-v{version}"


def _normalise_candidate(
    text: str,
    *,
    source_path: Path,
    story_id: str,
    timeline_id: str,
    expected_type: str | None,
    version: str | None,
    supersedes: str | Sequence[str] | None,
    document_family: str | None,
) -> tuple[str, RagDocument, str, str, tuple[str, ...]]:
    data, _ = _parse_document(text, source_path)
    metadata = data["metadata"]
    if str(metadata.get("story_id")) != story_id or str(metadata.get("timeline_id")) != timeline_id:
        raise RagImportError("文档 story_id/timeline_id 与当前选择不一致")
    document_type = str(metadata.get("document_type") or "")
    if document_type not in _DESTINATIONS:
        raise RagImportError(f"暂不导入该 document_type: {document_type}")
    if expected_type and document_type != expected_type:
        raise RagImportError(f"预期 {expected_type}，实际为 {document_type}")

    candidate_status = str(metadata.get("status") or "")
    if candidate_status not in {"active", "canon"}:
        raise RagImportError("uploaded current version must have active or canon status")
    selected_version = _version(version or metadata.get("version"))
    selected_supersedes = _ids(supersedes if supersedes is not None else metadata.get("supersedes"))
    if version is not None:
        metadata["version"] = selected_version
        current_id = str(metadata.get("document_id") or "")
        if current_id:
            metadata["document_id"] = _replace_version(current_id, selected_version)
    if supersedes is not None:
        metadata["supersedes"] = selected_supersedes[0] if len(selected_supersedes) == 1 else (selected_supersedes or None)
    if document_family:
        metadata["document_family"] = str(document_family).strip()
    raw_id = str(metadata.get("document_id") or "")
    if not raw_id:
        base = str(document_family or metadata.get("document_family") or "").strip()
        if not base:
            title = str(metadata.get("title") or document_type)
            digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:10]
            base = f"{document_type}-{story_id}-{digest}"
        metadata["document_id"] = _replace_version(_safe_name(base), selected_version)
    document_id = str(metadata["document_id"])
    if not _SAFE_ID_RE.fullmatch(document_id):
        raise RagImportError("document_id 只能使用字母、数字、点、下划线和连字符")
    suffix = _VERSION_SUFFIX_RE.search(document_id)
    if suffix and suffix.group(0)[2:] != selected_version:
        raise RagImportError("document_id version suffix does not match metadata version")
    family = str(metadata.get("document_family") or document_family or _family_from_id(document_id)).strip()
    if not family or not _SAFE_ID_RE.fullmatch(family):
        raise RagImportError("document_family 不能为空且必须是安全 ID")
    metadata["document_family"] = family
    serialized = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)
    _, document = _parse_document(serialized, source_path)
    return serialized, document, family, selected_version, tuple(selected_supersedes)


def _retrieval_tests(library_root: Path, index_root: Path) -> int:
    cases: list[dict[str, Any]] = []
    for path in sorted((library_root / "stories").glob("*/retrieval-tests.yaml")):
        rows = _read_mapping(path).get("tests", [])
        if isinstance(rows, list):
            cases.extend(row for row in rows if isinstance(row, Mapping))
    failures: list[str] = []
    for case in cases:
        try:
            results = search_isolated(index_root, str(case["query"]), str(case["story_id"]),
                                      str(case["timeline_id"]), document_types=case.get("document_types"), limit=20)
        except Exception as exc:
            raise RagImportError(f"检索回归失败 {case.get('id', 'unnamed')}: {exc}") from exc
        ids = {item.document_id for item in results}
        statuses = {item.status for item in results}
        missing = set(case.get("expected_document_ids", [])) - ids
        forbidden = set(case.get("forbidden_document_ids", [])) & ids
        bad_statuses = set(case.get("forbidden_statuses", [])) & statuses
        if missing or forbidden or bad_statuses:
            failures.append(str(case.get("id", "unnamed")))
    if failures:
        raise RagImportError("检索回归失败: " + ", ".join(failures))
    return len(cases)


def _prepare_text(
    text: str,
    *,
    source_path: Path,
    library_root: Path,
    index_root: Path,
    story_id: str,
    timeline_id: str,
    expected_type: str | None = None,
    version: str | None = None,
    supersedes: str | Sequence[str] | None = None,
    document_family: str | None = None,
    require_clean_library: bool = True,
) -> _PreparedImport:
    root = _validate_identity(library_root, story_id, timeline_id)
    if require_clean_library:
        _, issues = load_valid_documents(library_root, story_id=story_id, include_shared=False)
        if issues:
            raise RagImportError(f"导入前知识库已有 {len(issues)} 个校验问题")
    serialized, document, family, selected_version, selected_supersedes = _normalise_candidate(
        text, source_path=source_path, story_id=story_id, timeline_id=timeline_id,
        expected_type=expected_type, version=version, supersedes=supersedes,
        document_family=document_family,
    )
    metadata = document.metadata
    document_id = document.document_id
    version_map_path = root / "registry" / "version-map.yaml"
    rows = _version_rows(version_map_path)
    row = _find_family_row(rows, family, [document_id, *selected_supersedes])
    current, issues = load_valid_documents(library_root, story_id=story_id, include_shared=False)
    if issues:
        raise RagImportError(f"知识库校验失败: {issues[0].message}")
    by_id = {item.document_id: item for item in current}
    conflicts: list[str] = []
    if row and str(row.get("document_family") or "") not in {"", family}:
        conflicts.append(
            f"document_family must match existing superseded family: "
            f"{row.get('document_family')} != {family}"
        )
    existing = by_id.get(document_id)
    if existing:
        try:
            old_data = yaml.safe_load(existing.path.read_text(encoding="utf-8"))
            new_data = yaml.safe_load(serialized)
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise RagImportError(f"无法比较现有文档: {exc}") from exc
        if old_data == new_data:
            preview_status = "noop" if row and str(row.get("current") or "") == document_id else "ready"
        else:
            conflicts.append(f"document_id 已存在且内容不同: {document_id}")
            preview_status = "conflict"
    else:
        preview_status = "ready"

    if document_id in selected_supersedes:
        conflicts.append("supersedes cannot contain the new document_id itself")

    if row:
        row_current = str(row.get("current") or "")
        row_ids = _row_ids(row)
        if document_id != row_current and not selected_supersedes:
            conflicts.append(f"版本族 {family} 已有 current={row_current}，必须显式提供 supersedes")
        if selected_supersedes:
            unknown = [item for item in selected_supersedes if item not in by_id]
            if unknown:
                conflicts.append("supersedes 未找到: " + ", ".join(unknown))
            outside = [item for item in selected_supersedes if item not in row_ids]
            if outside:
                conflicts.append("supersedes 不属于当前版本族: " + ", ".join(outside))
            if row_current and row_current != document_id and row_current not in selected_supersedes:
                conflicts.append(f"新版本必须 supersedes 当前版本 {row_current}")
        elif document_id != row_current and preview_status != "noop":
            conflicts.append(f"版本族 {family} 的新版本必须显式 supersedes={row_current}")
    elif selected_supersedes:
        unknown = [item for item in selected_supersedes if item not in by_id]
        if unknown:
            conflicts.append("supersedes 未找到: " + ", ".join(unknown))

    destination = root / _DESTINATIONS[str(metadata["document_type"])]
    target = destination / f"{_safe_name(document_id)}.yaml"
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise RagImportError("导入目标路径越出当前小说目录") from exc
    if target.exists() and target.is_symlink():
        raise RagImportError(f"拒绝写入符号链接: {target}")

    if row:
        updated_rows = [dict(item) for item in rows]
        for item in updated_rows:
            if str(item.get("document_family") or "") != family:
                continue
            previous = _ids(item.get("supersedes"))
            previous.extend(_ids(item.get("current")))
            merged = list(dict.fromkeys(previous + list(selected_supersedes)))
            item["document_family"] = family
            item["current"] = document_id
            item["supersedes"] = [value for value in merged if value != document_id]
            item["reason"] = str(item.get("reason") or "导入新版本")
            break
    else:
        updated_rows = [{"document_family": family, "current": document_id,
                         "supersedes": list(selected_supersedes), "reason": "导入初始版本"}]
        updated_rows = [*rows, *updated_rows]

    old_ids = set(_ids(row.get("current")) if row else [])
    if row:
        old_ids.update(_ids(row.get("supersedes")))
    old_ids.update(selected_supersedes)
    old_paths = tuple(item.path for item in current if item.document_id in old_ids and item.document_id != document_id)
    preview = ImportPreview(
        status="conflict" if conflicts else preview_status,
        path=target,
        document_id=document_id,
        document_type=str(metadata["document_type"]),
        version=selected_version,
        document_family=family,
        supersedes=tuple(selected_supersedes),
        conflicts=tuple(dict.fromkeys(conflicts)),
        source_sha256=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    )
    return _PreparedImport(preview, serialized, document, target,
                           updated_rows, version_map_path, old_paths)


def _rollback_files(backups: Mapping[Path, bytes | None]) -> None:
    for path, data in backups.items():
        try:
            if data is None:
                path.unlink(missing_ok=True)
            else:
                _atomic_write(path, data.decode("utf-8"))
        except Exception:
            pass


def _commit_prepared(prepared: _PreparedImport, *, library_root: Path, index_root: Path) -> ImportResult:
    preview = prepared.preview
    if preview.conflicts:
        raise RagImportError("上传冲突: " + "；".join(preview.conflicts))
    if preview.status == "noop":
        return ImportResult("noop", preview.path, preview.document_id, preview.document_family,
                            preview.version, preview.supersedes, (), 0)
    backup_files: dict[Path, bytes | None] = {}
    paths = [prepared.target, prepared.version_map_path, *prepared.old_paths]
    for path in paths:
        if path in backup_files:
            continue
        backup_files[path] = path.read_bytes() if path.exists() else None
    index_backup = Path(tempfile.mkdtemp(prefix="novel-rag-index-backup-"))
    try:
        if index_root.exists():
            shutil.copytree(index_root, index_backup / "index", dirs_exist_ok=True)
        for path in prepared.old_paths:
            data = _read_mapping(path)
            metadata = data.get("metadata")
            if isinstance(metadata, dict) and metadata.get("status") in {"active", "canon"}:
                metadata["status"] = "deprecated"
                _atomic_write(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120))
        _atomic_write(prepared.target, prepared.text)
        _atomic_write(prepared.version_map_path, yaml.safe_dump(
            {"versions": prepared.version_rows}, allow_unicode=True, sort_keys=False, width=120
        ))
        documents, issues = load_valid_documents(library_root)
        if issues:
            raise RagImportError("导入后校验失败: " + "；".join(issue.message for issue in issues[:5]))
        rebuild_isolated_indexes(index_root, documents, registered_story_ids(library_root))
        retrieval_count = _retrieval_tests(library_root, index_root)
        return ImportResult("imported", prepared.target, preview.document_id, preview.document_family,
                            preview.version, preview.supersedes,
                            tuple(dict.fromkeys([prepared.target, prepared.version_map_path, *prepared.old_paths])),
                            retrieval_count)
    except Exception as exc:
        _rollback_files(backup_files)
        try:
            if index_root.exists():
                shutil.rmtree(index_root)
            if (index_backup / "index").exists():
                shutil.copytree(index_backup / "index", index_root, dirs_exist_ok=True)
        except Exception:
            pass
        if isinstance(exc, RagImportError):
            raise
        raise RagImportError(f"导入事务失败并已回滚: {exc}") from exc
    finally:
        shutil.rmtree(index_backup, ignore_errors=True)


def _import_text(
    text: str,
    *,
    source_path: Path,
    library_root: Path,
    index_root: Path,
    story_id: str,
    timeline_id: str,
    expected_type: str | None = None,
    version: str | None = None,
    supersedes: str | Sequence[str] | None = None,
    document_family: str | None = None,
) -> ImportResult:
    library, index = _validate_roots(library_root, index_root)
    prepared = _prepare_text(
        text, source_path=source_path, library_root=library, index_root=index,
        story_id=story_id, timeline_id=timeline_id, expected_type=expected_type,
        version=version, supersedes=supersedes, document_family=document_family,
    )
    return _commit_prepared(prepared, library_root=library, index_root=index)