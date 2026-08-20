"""Private helper functions for import."""

from __future__ import annotations

import hashlib
import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from ..catalog import (
    ValidatedCorpus,
    fingerprint_paths,
    load_timeline_registry,
    resolve_module_map_path,
    resolve_timeline_registry_path,
    resolve_version_map_path,
    story_registry_roots,
)
from ..documents import RagDocument, registered_story_ids, validate_document
from ..graph import GraphBuilder, GraphKey, SharedBuilder
from ..layout import story_root
from ..mutations import ChangeSet, GraphBuildArtifact, MutationCoordinator, fingerprint_file
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


def _validate_roots(library_root: Path, index_root: Path | None) -> tuple[Path, Path]:
    library = library_root.resolve()
    index = (index_root or library / "index").resolve()
    expected = (library / "index").resolve()
    if index != expected:
        raise RagImportError("导入只允许重建当前知识库的 index 目录")
    return library, index


def _story_registry_roots(library_root: Path, story_id: str) -> tuple[Path, ...]:
    return story_registry_roots(library_root, story_id)


def _timeline_registry_path(library_root: Path, story_id: str) -> Path:
    return resolve_timeline_registry_path(library_root, story_id)


def _selected_registry_root(library_root: Path, story_id: str, timeline_id: str) -> Path:
    # This helper is retained for compatibility with migration callers.  The
    # actual version-map resolver below is common-owned and must not use this
    # timeline registry root.
    roots = story_registry_roots(library_root, story_id, timeline_id=timeline_id)
    return roots[0]


def _document_root(library_root: Path, story_id: str, timeline_id: str) -> Path:
    story = story_root(library_root.resolve(), story_id)
    timelines = story / "timelines"
    return timelines / timeline_id if timelines.is_dir() else story


def _validate_identity(library_root: Path, story_id: str, timeline_id: str) -> Path:
    try:
        root = story_root(library_root.resolve(), story_id)
    except ValueError as exc:
        raise RagImportError(str(exc)) from exc
    if story_id not in registered_story_ids(library_root):
        raise RagImportError(f"未注册 story_id: {story_id}")
    registry = _timeline_registry_path(library_root, story_id)
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


def _retrieval_cases(library_root: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted((library_root / "stories").rglob("retrieval-tests.yaml")):
        rows = _read_mapping(path).get("tests", [])
        if isinstance(rows, list):
            cases.extend(row for row in rows if isinstance(row, Mapping))
    return cases


def _retrieval_tests(library_root: Path, index_root: Path) -> int:
    """Return the number of configured gates.

    Actual assertions run against each staged ``GraphReader`` before the
    coordinator promotes it.  Keeping this helper as a count preserves the
    historical ``ImportResult.retrieval_cases`` field without re-opening a
    committed database through the legacy index façade.
    """

    del index_root
    return len(_retrieval_cases(library_root))


def _yaml_source_fingerprint(library_root: Path) -> str:
    paths: list[Path] = []
    for suffix in ("*.yaml", "*.yml"):
        paths.extend(
            path
            for path in library_root.rglob(suffix)
            if "index" not in path.relative_to(library_root).parts
            and not any(
                part.startswith(".mutation-")
                for part in path.relative_to(library_root).parts
            )
        )
    return fingerprint_paths(sorted(set(paths)), root=library_root)


def _projected_library(staged: Any, library_root: Path) -> Path:
    """Materialize a read-only source projection from staged ChangeSet files.

    The projection lives below the coordinator's private staging root.  It is
    only an input to catalog validation and graph builders; canonical YAML and
    index paths are never changed here.
    """

    projected = Path(staged.root) / "source"
    if not projected.exists():
        shutil.copytree(
            library_root,
            projected,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("index", ".mutation-*"),
        )
    for original, staged_path in staged.staged_files.items():
        target = Path(original).resolve()
        try:
            relative = target.relative_to(library_root.resolve())
        except ValueError as exc:
            raise RagImportError(f"ChangeSet 路径越出 library_root: {target}") from exc
        destination = projected / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(staged_path), destination)
    return projected


def _load_projected_corpus(
    staged: Any,
    *,
    library_root: Path,
    story_id: str,
) -> tuple[Path, ValidatedCorpus, Any]:
    projected = _projected_library(staged, library_root)
    documents, issues = load_valid_documents(
        projected,
        story_id=story_id,
        include_shared=True,
    )
    if issues:
        raise RagImportError(
            "staged YAML 校验失败: "
            + "；".join(issue.message for issue in issues[:8])
        )
    registry_path = _timeline_registry_path(projected, story_id)
    try:
        registry = load_timeline_registry(
            registry_path,
            expected_story_id=story_id,
            snapshot_root=projected / "stories" / story_id,
        )
        corpus = ValidatedCorpus.from_documents(
            documents,
            root=projected,
            timeline_registry=registry,
            strict=True,
        )
    except Exception as exc:
        raise RagImportError(f"staged catalog 校验失败: {exc}") from exc
    return projected, corpus, registry


def _affected_graph_keys(
    library_root: Path,
    *,
    story_id: str,
    timeline_id: str,
) -> tuple[GraphKey, ...]:
    keys: list[GraphKey] = [GraphKey.shared()]
    registry_path = _timeline_registry_path(library_root, story_id)
    try:
        registry = load_timeline_registry(
            registry_path,
            expected_story_id=story_id,
            snapshot_root=library_root / "stories" / story_id,
        )
        keys.extend(GraphKey(story_id, entry.timeline_id) for entry in registry.entries)
    except Exception:
        # Identity was already validated by _prepare_text.  A narrow legacy
        # fixture may not satisfy the richer timeline registry contract; still
        # rebuild the explicitly selected graph and shared projection.
        pass
    selected = GraphKey(story_id, timeline_id)
    if selected not in keys:
        keys.append(selected)
    return tuple(dict.fromkeys(keys))


def _module_references(
    projected: Path,
    *,
    story_id: str,
    timeline_id: str,
    corpus: ValidatedCorpus,
    registry: Any,
) -> tuple[dict[str, str], ...]:
    allowed = set(registry.allowed_timeline_ids(timeline_id)) if registry is not None else {timeline_id}
    by_id = {document.document_id: document for document in corpus.documents}
    references: list[dict[str, str]] = []
    # Resolve one authoritative module-map for this GraphKey.  Do not merge a
    # legacy story registry with a target timeline registry when both exist.
    registry_path = resolve_module_map_path(
        projected,
        story_id,
        timeline_id=timeline_id,
    )
    for row in _read_mapping(registry_path).get("modules", []):
        if not isinstance(row, Mapping):
            continue
        row_story = str(row.get("story_id") or story_id)
        row_timeline = str(row.get("timeline_id") or timeline_id)
        if row_story not in {"", story_id} or row_timeline not in {*allowed, "", "common"}:
            continue
        module_type = str(row.get("module_type") or "")
        active = row.get("active_versions", row.get("active_version", ()))
        active_ids = _ids(active)
        for document_id in active_ids:
            source = by_id.get(document_id)
            metadata = source.metadata if source is not None else {}
            references.append(
                {
                    "module_type": module_type,
                    "document_id": document_id,
                    "version": str(metadata.get("version") or ""),
                    "source_file": str(source.path) if source is not None else "",
                }
            )
    for document in corpus.documents:
        values = document.metadata.get("module_references", ())
        if isinstance(values, Mapping):
            values = (values,)
        for value in values if isinstance(values, (list, tuple, set)) else ():
            if isinstance(value, Mapping) and value.get("document_id"):
                references.append(
                    {
                        "module_type": str(value.get("module_type", value.get("type", ""))),
                        "document_id": str(value["document_id"]),
                        "version": str(value.get("version", "")),
                        "source_file": str(value.get("source_file", "")),
                    }
                )
    deduplicated = {
        (item["module_type"], item["document_id"], item["version"]): item
        for item in references
        if item["module_type"] and item["document_id"]
    }
    return tuple(deduplicated[key] for key in sorted(deduplicated))


def _run_retrieval_gate(reader: Any, key: GraphKey, projected: Path) -> None:
    failures: list[str] = []
    for case in _retrieval_cases(projected):
        if (str(case.get("story_id")), str(case.get("timeline_id"))) != (
            key.story_id,
            key.timeline_id,
        ):
            continue
        try:
            results = reader.search(str(case["query"]), limit=20)
        except Exception as exc:
            raise RagImportError(f"检索回归失败 {case.get('id', 'unnamed')}: {exc}") from exc
        ids = {str(item.document_id) for item in results}
        statuses = {str(item.status) for item in results}
        missing = set(case.get("expected_document_ids", [])) - ids
        forbidden = set(case.get("forbidden_document_ids", [])) & ids
        bad_statuses = set(case.get("forbidden_statuses", [])) & statuses
        if missing or forbidden or bad_statuses:
            failures.append(str(case.get("id", "unnamed")))
    if failures:
        raise RagImportError("检索回归失败: " + ", ".join(failures))


def _default_coordinator(
    *,
    library_root: Path,
    index_root: Path,
    story_id: str,
    timeline_id: str,
) -> MutationCoordinator:
    """Lazily use the application composition root for importer commits."""

    del story_id, timeline_id
    try:
        from ..composition import build_mutation_coordinator
    except (ImportError, AttributeError) as exc:
        raise RagImportError(
            "默认 MutationCoordinator composition 不可用；导入已拒绝，"
            "请提供显式 coordinator"
        ) from exc
    try:
        coordinator = build_mutation_coordinator(
            library_root=library_root,
            index_directory=index_root,
        )
    except Exception as exc:
        raise RagImportError(f"无法建立导入 MutationCoordinator: {exc}") from exc
    if not callable(getattr(coordinator, "commit", None)):
        raise RagImportError("默认 MutationCoordinator 缺少 commit()，导入已拒绝")
    if not callable(getattr(coordinator, "graph_builder", None)):
        raise RagImportError("默认 MutationCoordinator 缺少 graph_builder，导入已拒绝")
    return coordinator


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
    # Version lineage is story-wide common data.  The catalog resolver falls
    # back to legacy ``stories/<story>/registry`` only when no target common
    # map exists; it never selects a timeline-owned version-map.
    version_map_path = resolve_version_map_path(
        library_root,
        story_id,
        timeline_id=timeline_id,
    )
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

    destination = _document_root(library_root, story_id, timeline_id) / _DESTINATIONS[
        str(metadata["document_type"])
    ]
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


def _deprecated_text(path: Path) -> str:
    data = _read_mapping(path)
    metadata = data.get("metadata")
    if isinstance(metadata, dict) and metadata.get("status") in {"active", "canon"}:
        metadata["status"] = "deprecated"
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)


def _commit_prepared(
    prepared: _PreparedImport,
    *,
    library_root: Path,
    index_root: Path,
    story_id: str,
    timeline_id: str,
    coordinator: Any | None = None,
) -> ImportResult:
    preview = prepared.preview
    if preview.conflicts:
        raise RagImportError("上传冲突: " + "；".join(preview.conflicts))
    if preview.status == "noop":
        return ImportResult("noop", preview.path, preview.document_id, preview.document_family,
                            preview.version, preview.supersedes, (), 0)
    changes: dict[Path, str] = {
        prepared.target: prepared.text,
        prepared.version_map_path: yaml.safe_dump(
            {"versions": prepared.version_rows},
            allow_unicode=True,
            sort_keys=False,
            width=120,
        ),
    }
    for path in prepared.old_paths:
        changes[path] = _deprecated_text(path)
    expected_files = {path: fingerprint_file(path) for path in changes}
    try:
        active_coordinator = coordinator or _default_coordinator(
            library_root=library_root,
            index_root=index_root,
            story_id=story_id,
            timeline_id=timeline_id,
        )
        if callable(active_coordinator) and not hasattr(active_coordinator, "commit"):
            try:
                active_coordinator = active_coordinator(
                    library_root=library_root,
                    index_root=index_root,
                    story_id=story_id,
                    timeline_id=timeline_id,
                )
            except TypeError:
                active_coordinator = active_coordinator(
                    library_root=library_root,
                    index_root=index_root,
                )
        change_set = ChangeSet(
            changes=changes,
            affected_graph_keys=_affected_graph_keys(
                library_root,
                story_id=story_id,
                timeline_id=timeline_id,
            ),
            expected_fingerprint=_yaml_source_fingerprint(library_root),
            expected_file_fingerprints=expected_files,
            change_id=f"import:{story_id}:{timeline_id}:{preview.document_id}",
            metadata={
                "operation": "import",
                "story_id": story_id,
                "timeline_id": timeline_id,
                "document_id": preview.document_id,
                "document_type": preview.document_type,
            },
        )
        result = active_coordinator.commit(change_set)
        status = str(getattr(result, "status", "promoted") or "promoted")
        graph_results = tuple(getattr(result, "graph_results", ()) or ())
        failed_graphs = tuple(
            item for item in graph_results if str(getattr(item, "status", "")).lower() == "failed"
        )
        pending_graphs = tuple(
            item for item in graph_results if str(getattr(item, "status", "")).lower() == "pending"
        )
        if (
            status.lower() == "failed"
            or failed_graphs
            or getattr(result, "yaml_committed", True) is False
        ):
            detail = str(getattr(result, "error", "") or "") or "; ".join(
                f"{getattr(item, 'key', '<unknown>')}: {getattr(item, 'error', '') or 'failed'}"
                for item in failed_graphs
            ) or status
            raise RagImportError(f"导入事务未完成: {detail}")
        retrieval_count = _retrieval_tests(library_root, index_root)
        return ImportResult(
            "pending" if status.lower() == "pending" or pending_graphs else "imported",
            prepared.target,
            preview.document_id,
            preview.document_family,
            preview.version,
            preview.supersedes,
            tuple(dict.fromkeys([prepared.target, prepared.version_map_path, *prepared.old_paths])),
            retrieval_count,
        )
    except Exception as exc:
        if isinstance(exc, RagImportError):
            raise
        raise RagImportError(f"导入事务失败: {exc}") from exc


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
    coordinator: Any | None = None,
) -> ImportResult:
    library, index = _validate_roots(library_root, index_root)
    prepared = _prepare_text(
        text, source_path=source_path, library_root=library, index_root=index,
        story_id=story_id, timeline_id=timeline_id, expected_type=expected_type,
        version=version, supersedes=supersedes, document_family=document_family,
    )
    return _commit_prepared(
        prepared,
        library_root=library,
        index_root=index,
        story_id=story_id,
        timeline_id=timeline_id,
        coordinator=coordinator,
    )
