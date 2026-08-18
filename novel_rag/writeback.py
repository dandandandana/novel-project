from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .documents import load_document, read_yaml_mapping, registered_story_ids, validate_document
from .index import rebuild_isolated_indexes, search_isolated
from .layout import story_root
from .service import load_valid_documents


class WritebackError(ValueError):
    pass


@dataclass(slots=True)
class WritebackResult:
    status: str
    writeback_id: str
    document_ids: list[str] = field(default_factory=list)
    history_path: str = ""
    state_promoted: bool = False
    retrieval_cases: int = 0
    cleaned_files: int = 0
    cleanup_warnings: list[str] = field(default_factory=list)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WritebackError(f"无法读取运行时文件 {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise WritebackError(f"运行时文件不是对象: {path.name}")
    return value


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _retrieval_tests(library_root: Path, index_root: Path) -> int:
    cases: list[dict[str, Any]] = []
    for path in sorted((library_root / "stories").glob("*/retrieval-tests.yaml")):
        cases.extend((read_yaml_mapping(path).get("tests") or []))
    failures = []
    for case in cases:
        results = search_isolated(index_root, str(case["query"]), str(case["story_id"]),
                                  str(case["timeline_id"]), document_types=case.get("document_types"), limit=20)
        ids = {item.document_id for item in results}
        statuses = {item.status for item in results}
        missing = set(case.get("expected_document_ids", [])) - ids
        forbidden = set(case.get("forbidden_document_ids", [])) & ids
        bad_statuses = set(case.get("forbidden_statuses", [])) & statuses
        if missing or forbidden or bad_statuses:
            failures.append(str(case.get("id", "unnamed")))
    if failures:
        raise WritebackError(f"检索回归失败: {', '.join(failures)}")
    return len(cases)


def confirm_runtime(runtime_dir: Path, *, library_root: Path, index_root: Path | None = None,
                    confirmed: bool, volume: int, chapter: int, scene: int,
                    title: str = "", pov: str = "", character_ids: list[str] | None = None,
                    location_ids: list[str] | None = None) -> WritebackResult:
    if not confirmed:
        raise WritebackError("必须显式传入 --yes 确认正文")
    if volume < 0 or min(chapter, scene) < 1:
        raise WritebackError("volume 不得小于 0，chapter、scene 必须大于 0")
    runtime_dir = runtime_dir.resolve()
    library_root = library_root.resolve()
    expected_index = (library_root / "index").resolve()
    index_root = (index_root or expected_index).resolve()
    if index_root != expected_index:
        raise WritebackError("confirm 只允许重建当前知识库的 index 目录")
    if ".workflow" not in runtime_dir.parts:
        raise WritebackError("--runtime 必须指向 outputs/.workflow 下的生成目录")
    contract = _read_json(runtime_dir / "contract.json")
    result = _read_json(runtime_dir / "result.json")
    if result.get("status") not in {"pass", "pass_with_warnings"}:
        raise WritebackError(f"运行时状态不可确认: {result.get('status')}")
    extensions = result.get("extensions") or {}
    if not isinstance(extensions, dict):
        raise WritebackError("result.extensions 格式错误")
    if extensions.get("confirmed") not in {False, True}:
        raise WritebackError("result.extensions.confirmed 缺失或格式错误")
    request = contract.get("request") or {}
    if not isinstance(request, dict):
        raise WritebackError("contract.request 格式错误")
    story_id = str(request.get("story_id") or "")
    timeline_id = str(request.get("timeline_id") or "")
    if story_id not in registered_story_ids(library_root):
        raise WritebackError(f"未注册 story_id: {story_id}")
    try:
        current_story_root = story_root(library_root, story_id)
    except ValueError as exc:
        raise WritebackError(str(exc)) from exc
    workflow_index = runtime_dir.parts.index(".workflow")
    if len(runtime_dir.parts) <= workflow_index + 2 or runtime_dir.parts[workflow_index + 1] != story_id:
        raise WritebackError("运行时目录中的 story_id 与 contract 不一致")
    recorded_runtime = extensions.get("runtime_dir")
    if recorded_runtime and Path(str(recorded_runtime)).resolve() != runtime_dir:
        raise WritebackError("result.json 记录的运行时目录不一致")
    timelines = read_yaml_mapping(library_root / "stories" / story_id / "registry" / "timelines.yaml")
    if not any(str(item.get("story_id")) == story_id and str(item.get("timeline_id")) == timeline_id
               for item in timelines.get("timelines", [])):
        raise WritebackError(f"未注册 timeline_id: {timeline_id}")

    confirmation_path = runtime_dir / "confirmation.json"
    if extensions.get("confirmed") is True:
        if not confirmation_path.exists():
            raise WritebackError("运行时已标记确认，但缺少 confirmation.json")
        previous = _read_json(confirmation_path)
        history_path = Path(str(previous.get("history_path") or ""))
        if not history_path.exists():
            raise WritebackError("已确认的正式 History 不存在")
        metadata = load_document(history_path).metadata
        expected = (story_id, timeline_id, volume, chapter, scene)
        actual = (str(metadata.get("story_id")), str(metadata.get("timeline_id")),
                  int(metadata.get("volume")), int(metadata.get("chapter")), int(metadata.get("scene")))
        if actual != expected:
            raise WritebackError("该运行时正文已经确认到其他坐标")
        values = {key: previous[key] for key in WritebackResult.__dataclass_fields__ if key in previous}
        values["status"] = "noop"
        return WritebackResult(**values)

    final_path = runtime_dir / "final.txt"
    try:
        final_text = final_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WritebackError(f"无法读取 final.txt: {exc}") from exc
    if final_text != str(result.get("text") or ""):
        raise WritebackError("final.txt 与 result.json 正文不一致")

    final_hash = hashlib.sha256(final_text.encode("utf-8")).hexdigest()
    identity = f"{story_id}|{timeline_id}|{volume}|{chapter}|{scene}|{final_hash}"
    writeback_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    if confirmation_path.exists():
        previous = _read_json(confirmation_path)
        if previous.get("writeback_id") == writeback_id and previous.get("status") == "committed":
            values = {key: previous[key] for key in WritebackResult.__dataclass_fields__ if key in previous}
            values["status"] = "noop"
            return WritebackResult(**values)
        raise WritebackError("该运行时目录已经确认过不同正文或坐标")

    events = result.get("events") or []
    if not isinstance(events, list) or any(not isinstance(item, dict) for item in events):
        raise WritebackError("result.events 必须是对象列表")
    inferred_characters = []
    for event in events:
        for value in [event.get("actor"), *(event.get("targets") or []), *(event.get("observers") or [])]:
            if value and str(value) not in inferred_characters:
                inferred_characters.append(str(value))
    outline = contract.get("outline") or {}
    if not isinstance(outline, dict):
        raise WritebackError("contract.outline 格式错误")
    document_id = f"history-{story_id}-v{volume:02d}-c{chapter:03d}-s{scene:03d}-{final_hash[:8]}"
    target = (current_story_root / "history" / f"volume-{volume:02d}"
              / f"chapter-{chapter:03d}" / f"scene-{scene:03d}.yaml")
    history_root = current_story_root / "history"
    if history_root.exists() and history_root.is_symlink():
        raise WritebackError("History 根目录不能是符号链接")
    ancestor = target.parent
    while not ancestor.exists() and ancestor != current_story_root:
        ancestor = ancestor.parent
    if ancestor.is_symlink():
        raise WritebackError("History 目标祖先不能是符号链接")
    try:
        ancestor.resolve().relative_to(current_story_root.resolve())
    except ValueError as exc:
        raise WritebackError("History 目标祖先越出当前小说范围") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    allowed_history = history_root.resolve()
    try:
        target.resolve().relative_to(allowed_history)
    except ValueError as exc:
        raise WritebackError("History 目标路径越出当前小说范围") from exc
    history = {
        "metadata": {
            "document_id": document_id, "story_id": story_id, "timeline_id": timeline_id,
            "document_type": "history", "title": title or f"第{volume}卷 第{chapter}章 场景{scene}",
            "volume": volume, "chapter": chapter, "scene": scene, "pov_character": pov,
            "character_ids": character_ids or inferred_characters, "location_ids": location_ids or [],
            "event_tags": [str(event.get("result") or event.get("event_id") or "") for event in events],
            "start_state": [outline.get("opening_state")] if outline.get("opening_state") else [],
            "end_state": [outline.get("ending_state") or outline.get("required_result")]
            if outline.get("ending_state") or outline.get("required_result") else [],
            "previous_scene": None, "next_scene": None, "version": "1.0", "status": "canon",
            "supersedes": None, "source_file": f"runtime:{writeback_id}", "source_sha256": final_hash,
        },
        "content": final_text,
    }
    rendered = yaml.safe_dump(history, allow_unicode=True, sort_keys=False, width=120)
    staging = runtime_dir / "staging" / target.name
    staging.parent.mkdir(parents=True, exist_ok=True)
    try:
        staging.resolve().relative_to(runtime_dir)
    except ValueError as exc:
        raise WritebackError("运行时 staging 路径越界") from exc
    _atomic_text(staging, rendered)
    errors = validate_document(load_document(staging))
    if errors:
        raise WritebackError("History 模板校验失败: " + "；".join(errors))
    if target.exists():
        existing = load_document(target)
        if str(existing.body.get("content") or "") != final_text:
            raise WritebackError(f"目标场景已存在且正文不同: {target}")
        document_id = existing.document_id
        status = "noop"
    else:
        status = "committed"
    proposal = {"status": "needs_review", "writeback_id": writeback_id, "history_document_id": document_id,
                "note": "仅供人工审核；本次 confirm 未更新 character/world current。",
                "candidate_state": result.get("state"),
                "event_state_deltas": [{"event_id": item.get("event_id"), "state_deltas": item.get("state_deltas")}
                                       for item in events]}
    proposal_path = runtime_dir / "state-writeback-proposal.json"
    result_path = runtime_dir / "result.json"
    original_result = result_path.read_bytes()
    created_history = False
    confirmation = WritebackResult(status=status, writeback_id=writeback_id, document_ids=[document_id],
                                   history_path=str(target), state_promoted=False, retrieval_cases=0)
    try:
        if status == "committed":
            _atomic_text(target, rendered)
            created_history = True
        _atomic_text(proposal_path, json.dumps(proposal, ensure_ascii=False, indent=2))
        documents, issues = load_valid_documents(library_root)
        if issues:
            raise WritebackError("知识库校验失败: " + "；".join(issue.message for issue in issues[:5]))
        rebuild_isolated_indexes(index_root, documents, registered_story_ids(library_root))
        retrieval_count = _retrieval_tests(library_root, index_root)
        confirmation.retrieval_cases = retrieval_count
        result.setdefault("extensions", {})["confirmed"] = True
        result["extensions"]["writeback_id"] = writeback_id
        result["extensions"]["history_document_ids"] = [document_id]
        result["extensions"]["final_sha256"] = final_hash
        result["extensions"]["prose_migrated"] = True
        result["text"] = ""
        for event in result.get("events", []):
            event["prose"] = ""
        _atomic_text(result_path, json.dumps(result, ensure_ascii=False, indent=2))
        persisted = {name: getattr(confirmation, name) for name in WritebackResult.__dataclass_fields__}
        persisted["status"] = "committed"
        _atomic_text(confirmation_path, json.dumps(persisted, ensure_ascii=False, indent=2))
    except Exception as exc:
        if created_history and target.exists():
            target.unlink()
        result_path.write_bytes(original_result)
        proposal_path.unlink(missing_ok=True)
        confirmation_path.unlink(missing_ok=True)
        shutil.rmtree(runtime_dir / "staging", ignore_errors=True)
        try:
            documents, _ = load_valid_documents(library_root)
            rebuild_isolated_indexes(index_root, documents, registered_story_ids(library_root))
        except Exception:
            pass
        if isinstance(exc, WritebackError):
            raise
        raise WritebackError(f"回写失败并已回滚: {exc}") from exc

    cleanup_targets = list(runtime_dir.glob("*.txt")) + list(runtime_dir.glob("audit-*.json"))
    cleanup_targets += [runtime_dir / "context.json", runtime_dir / "references.json"]
    for path in cleanup_targets:
        if not path.exists():
            continue
        try:
            path.unlink()
            confirmation.cleaned_files += 1
        except OSError as exc:
            confirmation.cleanup_warnings.append(f"{path.name}: {exc}")
    shutil.rmtree(runtime_dir / "staging", ignore_errors=True)
    persisted = {name: getattr(confirmation, name) for name in WritebackResult.__dataclass_fields__}
    persisted["status"] = "committed"
    _atomic_text(confirmation_path, json.dumps(persisted, ensure_ascii=False, indent=2))

    return confirmation
