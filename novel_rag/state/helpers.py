"""Private helper functions for state review and promotion."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import yaml

from ..documents import load_document, read_yaml_mapping, registered_story_ids
from ..index import rebuild_isolated_indexes, search_isolated
from ..layout import story_root
from ..service import load_valid_documents
from .types import (
    StateReviewError,
    _CHARACTER_FIELDS,
    _CHARACTER_SUBFIELDS,
    _WORLD_FIELDS,
    StatePromotionResult,
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StateReviewError(f"无法读取 {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise StateReviewError(f"{path.name} 必须是对象")
    return value


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _atomic_yaml(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_text(path, yaml.safe_dump(dict(value), allow_unicode=True, sort_keys=False, width=120))


def _safe_id(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text or Path(text).name != text or text in {".", ".."}:
        raise StateReviewError(f"{field_name} 不是安全标识: {text!r}")
    return text


def _assert_path_scope(path: Path, root: Path, *, label: str, allow_missing: bool = True) -> Path:
    root = root.resolve()
    path = path.resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise StateReviewError(f"{label} 越出允许目录") from exc
    current = path
    while True:
        if current.exists() and current.is_symlink():
            raise StateReviewError(f"{label} 不能经过符号链接: {current}")
        if current == root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    if not allow_missing and not path.exists():
        raise StateReviewError(f"{label} 不存在: {path}")
    return path


def _runtime_paths(runtime_dir: Path, *, require_confirmed: bool = True) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    runtime = _assert_path_scope(runtime_dir, runtime_dir.anchor and Path(runtime_dir.anchor) or Path("."), label="runtime")
    runtime = runtime.resolve()
    if runtime.is_symlink() or not runtime.is_dir():
        raise StateReviewError("runtime 必须是目录且不能是符号链接")
    parts = runtime.parts
    try:
        marker = max(i for i, item in enumerate(parts) if item == ".workflow")
    except ValueError as exc:
        raise StateReviewError("runtime 必须位于 outputs/.workflow 下") from exc
    if len(parts) < marker + 3:
        raise StateReviewError("runtime 必须包含 story/task 两级目录")
    contract = _read_json(runtime / "contract.json")
    result = _read_json(runtime / "result.json")
    proposal_path = runtime / "state-writeback-proposal.json"
    proposal = _read_json(proposal_path)
    request = contract.get("request")
    if not isinstance(request, dict):
        raise StateReviewError("contract.request 格式错误")
    story_id = str(request.get("story_id") or "")
    if not story_id or parts[marker + 1] != story_id:
        raise StateReviewError("runtime story_id 与 contract 不一致")
    if require_confirmed and (result.get("extensions") or {}).get("confirmed") is not True:
        raise StateReviewError("只能审核已经 confirm 的 runtime")
    if not proposal.get("writeback_id"):
        raise StateReviewError("提案缺少 writeback_id")
    if proposal.get("status") not in {"needs_review", "promoted", "rejected"}:
        raise StateReviewError(f"无法审核提案状态: {proposal.get('status')!r}")
    return runtime, contract, result, proposal


def _find_history(library_root: Path, story_id: str, history_document_id: str, timeline_id: str) -> tuple[Path, Any]:
    if not history_document_id:
        raise StateReviewError("提案缺少 confirmed History document_id")
    root = _assert_path_scope(story_root(library_root, story_id) / "history", library_root, label="History")
    if not root.exists():
        raise StateReviewError("confirmed History 不存在")
    for path in sorted(root.rglob("*.yaml")):
        if path.is_symlink():
            raise StateReviewError(f"History 不能包含符号链接: {path}")
        try:
            document = load_document(path)
        except Exception:
            continue
        metadata = document.metadata
        if document.document_id != str(history_document_id):
            continue
        if str(metadata.get("story_id")) != story_id or str(metadata.get("timeline_id")) != timeline_id:
            raise StateReviewError("History 的 story/timeline 与提案不一致")
        if metadata.get("status") != "canon":
            raise StateReviewError("只有 canon History 可以作为状态证据")
        if not str(document.body.get("content") or "").strip():
            raise StateReviewError("confirmed History 没有正文内容")
        return path, document
    raise StateReviewError(f"找不到 confirmed History: {history_document_id}")


def _candidate_characters(proposal: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    candidate = proposal.get("candidate_state")
    if isinstance(candidate, Mapping):
        characters = candidate.get("characters")
        if isinstance(characters, Mapping):
            for key, value in characters.items():
                if isinstance(value, Mapping):
                    result[str(key)] = copy.deepcopy(dict(value))
    deltas = proposal.get("event_state_deltas")
    if isinstance(deltas, list):
        for item in deltas:
            if not isinstance(item, Mapping):
                continue
            state_deltas = item.get("state_deltas")
            if not isinstance(state_deltas, Mapping):
                continue
            for key, value in state_deltas.items():
                if not isinstance(value, Mapping):
                    continue
                existing = result.setdefault(str(key), {})
                _deep_merge(existing, value)
    return result


def _candidate_world(proposal: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for source in (proposal.get("world_state"),):
        if isinstance(source, Mapping):
            values.update(copy.deepcopy(dict(source)))
    candidate = proposal.get("candidate_state")
    if isinstance(candidate, Mapping):
        shared = candidate.get("shared_context")
        if isinstance(shared, Mapping):
            source = shared.get("world_state", shared.get("world"))
            if isinstance(source, Mapping):
                values.update(copy.deepcopy(dict(source)))
    return values


def _deep_merge(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), Mapping):
            child = dict(target[key])
            _deep_merge(child, value)
            target[key] = child
        elif value not in (None, "", [], {}):
            target[str(key)] = copy.deepcopy(value)


def _nonempty(value: Any) -> bool:
    return value not in (None, "", [], {})


def _scope_values(field_scopes: Mapping[str, Any] | None, key: str) -> set[str] | None:
    if not field_scopes:
        return None
    values = field_scopes.get(key)
    if values is None and key == "world_state":
        values = field_scopes.get("world")
    if values is None:
        values = field_scopes.get("*")
    if values is None:
        return None
    if isinstance(values, str):
        return {values}
    if isinstance(values, Iterable):
        return {str(item) for item in values}
    return None


def _canonical_character_patch(candidate: Mapping[str, Any], allowed: set[str] | None) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for key, value in candidate.items():
        key = str(key)
        if key in {"character_id", "intent", "extensions"}:
            continue
        if key == "emotion":
            key = "mental"
            if not isinstance(value, Mapping):
                value = {"dominant_emotions": value if isinstance(value, list) else [value]}
        elif key == "knowledge":
            if not isinstance(value, Mapping):
                value = {"known": value if isinstance(value, list) else [value]}
        elif key == "relationships":
            pass
        elif key == "constraints":
            if not isinstance(value, Mapping):
                continue
            value = {str(k): v for k, v in value.items() if str(k) in _CHARACTER_FIELDS}
        if key not in _CHARACTER_FIELDS or not _nonempty(value):
            continue
        if allowed is not None and key not in allowed:
            continue
        if isinstance(value, Mapping):
            sub_allowed = _CHARACTER_SUBFIELDS.get(key)
            filtered = {
                str(subkey): copy.deepcopy(subvalue)
                for subkey, subvalue in value.items()
                if str(subkey) in (sub_allowed or set()) and _nonempty(subvalue)
            }
            if filtered:
                patch[key] = filtered
        elif key == "relationships" and isinstance(value, list):
            cleaned = [item for item in value if isinstance(item, Mapping) and _nonempty(item)]
            if cleaned:
                patch[key] = copy.deepcopy(cleaned)
        elif _nonempty(value):
            patch[key] = copy.deepcopy(value)
    return patch


def _canonical_world_patch(candidate: Mapping[str, Any], allowed: set[str] | None) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for key, value in candidate.items():
        key = str(key)
        if key not in _WORLD_FIELDS or not _nonempty(value):
            continue
        if allowed is not None and key not in allowed:
            continue
        patch[key] = copy.deepcopy(value)
    return patch


def _template(library_root: Path, name: str) -> dict[str, Any]:
    candidates = [
        library_root / "shared" / "templates" / name,
        library_root / "templates" / name,
        Path(__file__).resolve().parents[2] / "novel-rag" / "shared" / "templates" / name,
    ]
    for path in candidates:
        if path.exists():
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(value, dict):
                return value
    raise StateReviewError(f"缺少状态模板: {name}")


def _version_number(value: Any) -> tuple[int, int]:
    match = re.search(r"(\d+)(?:\.(\d+))?", str(value or ""))
    if not match:
        return 1, 0
    return int(match.group(1)), int(match.group(2) or 0)


def _next_version(value: Any) -> str:
    major, minor = _version_number(value)
    return f"{major}.{minor + 1}"


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return value or "review"


def _effective_at(history: Any) -> str:
    metadata = history.metadata
    try:
        volume, chapter, scene = int(metadata.get("volume", 0)), int(metadata.get("chapter", 0)), int(metadata.get("scene", 0))
    except (TypeError, ValueError):
        volume = chapter = scene = 0
    if volume and chapter:
        return f"volume-{volume:02d}-chapter-{chapter:03d}"
    return _slug(str(metadata.get("effective_at") or "confirmed"))


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _version_map_path(library_root: Path, story_id: str) -> Path:
    return story_root(library_root, story_id) / "registry" / "version-map.yaml"


def _update_version_map(source: Path | Mapping[str, Any], family: str, current: str,
                        previous: str | None, reason: str) -> dict[str, Any]:
    if isinstance(source, Path):
        value = read_yaml_mapping(source) if source.exists() else {}
        source_label = str(source)
    else:
        value = copy.deepcopy(dict(source))
        source_label = "version-map"
    rows = value.get("versions", [])
    if not isinstance(rows, list):
        raise StateReviewError(f"version-map 格式错误: {source_label}")
    matches = [row for row in rows if isinstance(row, dict) and str(row.get("document_family")) == family]
    if len(matches) > 1:
        raise StateReviewError(f"version-map 存在重复 family: {family}")
    previous_ids: list[str] = []
    if matches:
        old = matches[0]
        current_old = str(old.get("current") or "")
        if current_old:
            previous_ids.append(current_old)
        supersedes = old.get("supersedes")
        if isinstance(supersedes, list):
            previous_ids.extend(str(item) for item in supersedes if item)
        old["current"] = current
        old["supersedes"] = list(dict.fromkeys(([previous] if previous else []) + previous_ids))
        old["reason"] = reason
    else:
        rows.append({
            "document_family": family,
            "current": current,
            "supersedes": [previous] if previous else [],
            "reason": reason,
        })
    value["versions"] = rows
    return value


def _check_callback(callback: Callable[..., Any] | None, *args: Any) -> Any:
    if callback is None:
        return None
    try:
        return callback(*args)
    except TypeError as first:
        try:
            return callback()
        except TypeError:
            raise first


def _default_checks(library_root: Path, index_root: Path) -> int:
    documents, issues = load_valid_documents(library_root)
    if issues:
        joined = "; ".join(issue.message for issue in issues[:8])
        raise StateReviewError(f"状态晋升后 validate 失败: {joined}")
    rebuild_isolated_indexes(index_root, documents, registered_story_ids(library_root))
    cases: list[dict[str, Any]] = []
    for path in sorted((library_root / "stories").glob("*/retrieval-tests.yaml")):
        data = read_yaml_mapping(path)
        values = data.get("tests", [])
        if isinstance(values, list):
            cases.extend(item for item in values if isinstance(item, dict))
    failures: list[str] = []
    for case in cases:
        try:
            results = search_isolated(
                index_root,
                str(case.get("query") or ""),
                str(case.get("story_id") or ""),
                str(case.get("timeline_id") or ""),
                document_types=case.get("document_types"),
                limit=20,
            )
        except Exception as exc:
            failures.append(f"{case.get('id', 'unnamed')}: {exc}")
            continue
        ids = {item.document_id for item in results}
        if set(case.get("expected_document_ids", [])) - ids:
            failures.append(str(case.get("id", "unnamed")))
    if failures:
        raise StateReviewError("状态晋升后 retrieval 失败: " + ", ".join(failures))
    return len(cases)


def _load_current(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink():
        raise StateReviewError(f"current 不能是符号链接: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise StateReviewError(f"无法读取 current: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StateReviewError(f"current 必须是映射: {path}")
    return value


def _history_coordinates(history: Any) -> tuple[int, int, int]:
    metadata = history.metadata
    try:
        return int(metadata.get("volume", 0)), int(metadata.get("chapter", 0)), int(metadata.get("scene", 0))
    except (TypeError, ValueError):
        return 0, 0, 0


def _make_character_documents(
    library_root: Path,
    story_id: str,
    timeline_id: str,
    character_id: str,
    patch: Mapping[str, Any],
    history: Any,
    writeback_id: str,
    reason: str,
) -> tuple[dict[str, Any], dict[str, Any] | None, Path, Path | None, Path, dict[str, Any]]:
    root = story_root(library_root, story_id)
    current_path = _assert_path_scope(root / "character-state" / "current" / f"{character_id}.yaml", root, label="character current")
    old = _load_current(current_path)
    if old is None:
        document = _template(library_root, "character-current.yaml")
        metadata = dict(document.setdefault("metadata", {}))
        body = document.setdefault("character_state", {})
        old_id = None
        version = "1.0"
        variant_id = f"{character_id}-main"
    else:
        document = copy.deepcopy(old)
        metadata = dict(document.setdefault("metadata", {}))
        body = document.setdefault("character_state", {})
        old_id = str(metadata.get("document_id") or "") or None
        version = _next_version(metadata.get("version"))
        variant_id = str(metadata.get("variant_id") or f"{character_id}-main")
    merged = copy.deepcopy(body)
    _deep_merge(merged, patch)
    if merged == body:
        raise StateReviewError(f"{character_id}: 没有可晋升的明确字段")
    volume, chapter, scene = _history_coordinates(history)
    effective = _effective_at(history)
    new_id = f"state-current-{character_id}-v{version}"
    metadata.update({
        "document_id": new_id,
        "story_id": story_id,
        "timeline_id": timeline_id,
        "document_type": "character_state",
        "title": metadata.get("title") or f"当前状态 {character_id}",
        "character_id": character_id,
        "variant_id": variant_id,
        "snapshot_type": "current",
        "effective_at": effective,
        "last_updated": _today(),
        "version": version,
        "status": "active",
        "supersedes": old_id,
        "source_file": f"history:{history.document_id}",
        "source_sha256": hashlib.sha256(str(history.body.get("content") or "").encode("utf-8")).hexdigest(),
    })
    document["metadata"] = metadata
    document["character_state"] = merged
    snapshot_path: Path | None = None
    snapshot: dict[str, Any] | None = None
    if old is not None and old_id:
        snapshot = copy.deepcopy(old)
        snapshot_metadata = dict(snapshot.setdefault("metadata", {}))
        snapshot_metadata.update({
            "document_id": old_id,
            "snapshot_type": "snapshot",
            "status": "canon",
            "supersedes": snapshot_metadata.get("supersedes"),
        })
        snapshot["metadata"] = snapshot_metadata
        snapshot_path = _assert_path_scope(
            root / "character-state" / "snapshots" / effective / f"{character_id}-v{snapshot_metadata.get('version', '1.0')}.yaml",
            root,
            label="character snapshot",
        )
    change_path = _assert_path_scope(
        root / "character-state" / "change-logs" / effective / f"{character_id}.yaml",
        root,
        label="character change-log",
    )
    change_id = f"state-change-{character_id}-{_slug(effective)}-{writeback_id[:8]}"
    change = {
        "metadata": {
            "document_id": change_id,
            "story_id": story_id,
            "timeline_id": timeline_id,
            "document_type": "character_state",
            "title": f"{effective} 状态变化 {character_id}",
            "character_id": character_id,
            "variant_id": variant_id,
            "snapshot_type": "change_log",
            "effective_at": effective,
            "last_updated": _today(),
            "version": "1.0",
            "status": "canon",
            "supersedes": None,
            "source_file": f"history:{history.document_id}",
        },
        "changes": [{
            "category": "confirmed_state_proposal",
            "before": old_id,
            "after": new_id,
            "cause": reason,
            "evidence": history.document_id,
            "fields": sorted(patch),
        }],
    }
    return document, snapshot, current_path, snapshot_path, change_path, change


def _make_world_documents(
    library_root: Path,
    story_id: str,
    timeline_id: str,
    patch: Mapping[str, Any],
    history: Any,
    writeback_id: str,
    reason: str,
) -> tuple[dict[str, Any], dict[str, Any] | None, Path, Path | None, Path, dict[str, Any], str]:
    root = story_root(library_root, story_id)
    current_path = _assert_path_scope(root / "world-state" / "current" / "current.yaml", root, label="world current")
    old = _load_current(current_path)
    if old is None:
        document = _template(library_root, "world-current.yaml")
        metadata = dict(document.setdefault("metadata", {}))
        body = document.setdefault("world_state", {})
        old_id = None
        version = "1.0"
    else:
        document = copy.deepcopy(old)
        metadata = dict(document.setdefault("metadata", {}))
        body = document.setdefault("world_state", {})
        old_id = str(metadata.get("document_id") or "") or None
        version = _next_version(metadata.get("version"))
    merged = copy.deepcopy(body)
    _deep_merge(merged, patch)
    if merged == body:
        raise StateReviewError("world_state: 没有可晋升的明确字段")
    effective = _effective_at(history)
    new_id = f"world-state-current-v{version}"
    metadata.update({
        "document_id": new_id,
        "story_id": story_id,
        "timeline_id": timeline_id,
        "document_type": "world_state",
        "title": metadata.get("title") or f"{effective} 世界状态",
        "version": version,
        "status": "active",
        "effective_at": effective,
        "supersedes": old_id,
        "source_file": f"history:{history.document_id}",
        "updated_at": _today(),
    })
    document["metadata"] = metadata
    document["world_state"] = merged
    snapshot_path: Path | None = None
    snapshot: dict[str, Any] | None = None
    if old is not None and old_id:
        snapshot = copy.deepcopy(old)
        snapshot_metadata = dict(snapshot.setdefault("metadata", {}))
        snapshot_metadata.update({"document_id": old_id, "status": "canon", "snapshot_type": "snapshot"})
        snapshot["metadata"] = snapshot_metadata
        snapshot_path = _assert_path_scope(
            root / "world-state" / "snapshots" / effective / f"world-state-v{snapshot_metadata.get('version', '1.0')}.yaml",
            root,
            label="world snapshot",
        )
    change_path = _assert_path_scope(
        root / "world-state" / "change-logs" / effective / "world.yaml",
        root,
        label="world change-log",
    )
    change_id = f"world-change-{_slug(effective)}-{writeback_id[:8]}"
    change = {
        "metadata": {
            "document_id": change_id,
            "story_id": story_id,
            "timeline_id": timeline_id,
            "document_type": "world_state",
            "title": f"{effective} 世界状态变化",
            "version": "1.0",
            "status": "canon",
            "effective_at": effective,
            "snapshot_type": "change_log",
            "supersedes": None,
            "source_file": f"history:{history.document_id}",
        },
        "changes": [{
            "category": "confirmed_state_proposal",
            "before": old_id,
            "after": new_id,
            "cause": reason,
            "evidence": history.document_id,
            "fields": sorted(patch),
        }],
    }
    return document, snapshot, current_path, snapshot_path, change_path, change, new_id


def _restore_files(backups: Mapping[Path, bytes | None]) -> None:
    for path, content in reversed(list(backups.items())):
        try:
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        except OSError:
            pass


def _backup_path(path: Path, backups: dict[Path, bytes | None]) -> None:
    if path in backups:
        return
    if path.exists():
        if path.is_symlink():
            raise StateReviewError(f"不能覆盖符号链接: {path}")
        backups[path] = path.read_bytes()
    else:
        backups[path] = None


def _reject_conflicting_history_file(path: Path, value: Mapping[str, Any]) -> None:
    if not path.exists():
        return
    if path.is_symlink():
        raise StateReviewError(f"状态历史目标不能是符号链接: {path}")
    try:
        existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise StateReviewError(f"无法读取已有状态历史目标: {path}: {exc}") from exc
    if existing != dict(value):
        raise StateReviewError(f"状态历史目标已存在且内容不同: {path}")


def _persist_decision(
    proposal_path: Path,
    proposal: dict[str, Any],
    decision: str,
    writeback_id: str,
    *,
    document_ids: list[str],
    skipped: dict[str, str],
    retrieval_cases: int,
    status: str,
) -> StatePromotionResult:
    if proposal.get("status") == "promoted" and proposal.get("decision") == decision:
        return StatePromotionResult(status="noop", decision=decision, writeback_id=writeback_id,
                                    document_ids=[str(item) for item in proposal.get("promoted_document_ids", []) if item],
                                    skipped={str(k): str(v) for k, v in (proposal.get("skipped") or {}).items()})
    proposal.update({
        "status": status,
        "decision": decision,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "promoted_document_ids": document_ids,
        "skipped": skipped,
        "retrieval_cases": retrieval_cases,
    })
    _atomic_text(proposal_path, json.dumps(proposal, ensure_ascii=False, indent=2))
    return StatePromotionResult(status=status, decision=decision, writeback_id=writeback_id,
                                document_ids=document_ids, skipped=skipped, retrieval_cases=retrieval_cases)