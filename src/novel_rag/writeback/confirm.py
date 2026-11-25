"""Confirm a finished generation runtime into a canon History document.

``confirm_runtime`` is the only write path that migrates generated prose
into the library.  It validates the runtime and delegates formal YAML
commit, graph rebuild, and retrieval regression to an injected
``MutationCoordinator``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable

import yaml

from ..documents import load_document, read_yaml_mapping, registered_story_ids, validate_document
from ..identity import GraphKey
from ..catalog.paths import story_catalog_paths, timeline_registry_path
from ..mutations import ChangeSet, MutationCoordinator, fingerprint_file
from ..retrieval import Retriever
from ..service import load_valid_documents
from .helpers import _atomic_text, _read_json, _retrieval_tests
from .types import WritebackError, WritebackResult


def _build_default_mutation_coordinator(
    *,
    library_root: Path,
    index_root: Path,
    story_id: str,
    timeline_id: str,
) -> Any:
    """Load the application write composition root lazily for confirmation."""

    try:
        from ..composition import build_mutation_coordinator
    except (ImportError, AttributeError) as exc:
        raise WritebackError(
            "默认 MutationCoordinator composition 不可用；"
            "请注入 coordinator 或配置 novel_rag.composition.build_mutation_coordinator"
        ) from exc
    try:
        coordinator = build_mutation_coordinator(
            library_root=library_root,
            index_directory=index_root,
        )
    except TypeError as first:
        try:
            coordinator = build_mutation_coordinator(
                library_root=library_root,
                index_root=index_root,
                story_id=story_id,
                timeline_id=timeline_id,
            )
        except TypeError:
            try:
                coordinator = build_mutation_coordinator(library_root, index_root, story_id, timeline_id)
            except TypeError:
                try:
                    coordinator = build_mutation_coordinator(library_root, index_directory=index_root)
                except TypeError:
                    try:
                        coordinator = build_mutation_coordinator(library_root, index_root)
                    except TypeError:
                        raise first
    if not hasattr(coordinator, "commit"):
        raise WritebackError("build_mutation_coordinator 必须返回带 commit() 的对象")
    return coordinator


def _timeline_content_root(
    library_root: Path,
    story_id: str,
    timeline_id: str,
) -> tuple[Path, Path, bool]:
    """Return ``(content_root, story_root, is_target_layout)`` for writes.

    A target story owns timeline content below ``timelines/<id>``.  A
    legacy-only story has no target marker and keeps the old story-root
    location as an explicit compatibility path.  The distinction is made
    before any directory creation, so confirming a target story can never
    silently recreate ``stories/<story>/history``.
    """

    try:
        key = GraphKey(story_id, timeline_id)
        catalog = story_catalog_paths(
            library_root,
            story_id,
            default_timeline_id=key.timeline_id,
        )
    except (TypeError, ValueError) as exc:
        raise WritebackError(f"无法构造目标 story/timeline: {exc}") from exc
    story = catalog.story_root
    target_layout = catalog.timelines_root.exists() or catalog.common_registry_root.exists()
    if target_layout:
        return catalog.timelines_root / key.timeline_id, story, True
    return story, story, False


def confirm_runtime(runtime_dir: Path, *, library_root: Path, index_root: Path | None = None,
                    confirmed: bool, volume: int, chapter: int, scene: int,
                    title: str = "", pov: str = "", character_ids: list[str] | None = None,
                    location_ids: list[str] | None = None,
                    coordinator: MutationCoordinator | Any | None = None,
                    validator: Callable[..., Any] | None = None,
                    indexer: Callable[..., Any] | None = None,
                    retrieval: Callable[..., Any] | None = None,
                    retriever: Retriever | None = None) -> WritebackResult:
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
        current_story_root = story_catalog_paths(library_root, story_id).story_root
    except ValueError as exc:
        raise WritebackError(str(exc)) from exc
    workflow_index = runtime_dir.parts.index(".workflow")
    if len(runtime_dir.parts) <= workflow_index + 2 or runtime_dir.parts[workflow_index + 1] != story_id:
        raise WritebackError("运行时目录中的 story_id 与 contract 不一致")
    recorded_runtime = extensions.get("runtime_dir")
    if recorded_runtime and Path(str(recorded_runtime)).resolve() != runtime_dir:
        raise WritebackError("result.json 记录的运行时目录不一致")
    try:
        timeline_path = timeline_registry_path(library_root, story_id, required=True)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise WritebackError(f"未找到 story 的 timeline registry: {story_id}: {exc}") from exc
    timelines = read_yaml_mapping(timeline_path)
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
    content_root, scope_root, _target_layout = _timeline_content_root(
        library_root, story_id, timeline_id
    )
    target = (content_root / "history" / f"volume-{volume:02d}"
              / f"chapter-{chapter:03d}" / f"scene-{scene:03d}.yaml")
    history_root = content_root / "history"
    if history_root.exists() and history_root.is_symlink():
        raise WritebackError("History 根目录不能是符号链接")
    ancestor = target.parent
    while not ancestor.exists() and ancestor != scope_root:
        ancestor = ancestor.parent
    if ancestor.is_symlink():
        raise WritebackError("History 目标祖先不能是符号链接")
    try:
        ancestor.resolve().relative_to(scope_root.resolve())
    except ValueError as exc:
        raise WritebackError("History 目标祖先越出当前小说范围") from exc
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
    staging_root = runtime_dir / "staging"
    staging = staging_root / target.name
    staging_root.mkdir(parents=True, exist_ok=True)
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
    target_fingerprint = fingerprint_file(target)
    proposal = {"status": "needs_review", "writeback_id": writeback_id, "history_document_id": document_id,
                "note": "仅供人工审核；本次 confirm 未更新 character/world current。",
                "candidate_state": result.get("state"),
                "event_state_deltas": [{"event_id": item.get("event_id"), "state_deltas": item.get("state_deltas")}
                                       for item in events]}
    proposal_path = runtime_dir / "state-writeback-proposal.json"
    result_path = runtime_dir / "result.json"
    if proposal_path.is_symlink() or result_path.is_symlink() or confirmation_path.is_symlink():
        raise WritebackError("运行时确认文件不能是符号链接")
    confirmation = WritebackResult(
        status=status,
        writeback_id=writeback_id,
        document_ids=[document_id],
        history_path=str(target),
        state_promoted=False,
        retrieval_cases=0,
    )

    # Legacy callbacks remain pre-commit validation hooks.  Formal YAML
    # persistence and graph promotion are owned by MutationCoordinator.
    retrieval_count = 0
    if coordinator is None:
        _documents, corpus_issues = load_valid_documents(library_root)
        if corpus_issues:
            raise WritebackError(
                "知识库校验失败: " + "; ".join(issue.message for issue in corpus_issues[:5])
            )
        for callback, label, args in (
            (validator, "validate", (library_root,)),
            (indexer, "index/build", (library_root, index_root)),
        ):
            if callback is None:
                continue
            try:
                callback_result = callback(*args)
            except TypeError as first:
                try:
                    callback_result = callback()
                except TypeError:
                    raise first
            if callback_result is False or (
                isinstance(callback_result, (list, tuple)) and callback_result
            ):
                detail = (
                    "; ".join(str(item) for item in callback_result[:8])
                    if isinstance(callback_result, (list, tuple))
                    else "callback returned false"
                )
                raise WritebackError(f"{label} 失败: {detail}")
        if retrieval is not None:
            try:
                retrieval_result = retrieval(library_root, index_root)
            except TypeError as first:
                try:
                    retrieval_result = retrieval()
                except TypeError:
                    raise first
            if retrieval_result is False:
                raise WritebackError("retrieval 失败")
            if isinstance(retrieval_result, int) and not isinstance(retrieval_result, bool):
                retrieval_count = retrieval_result
        elif retriever is not None:
            retrieval_count = _retrieval_tests(library_root, index_root, retriever=retriever)

    result.setdefault("extensions", {})["confirmed"] = True
    result["extensions"]["writeback_id"] = writeback_id
    result["extensions"]["history_document_ids"] = [document_id]
    result["extensions"]["final_sha256"] = final_hash
    result["extensions"]["prose_migrated"] = True
    result["text"] = ""
    for event in result.get("events", []):
        event["prose"] = ""
    confirmation.retrieval_cases = retrieval_count
    persisted_confirmation = {
        name: getattr(confirmation, name) for name in WritebackResult.__dataclass_fields__
    }
    persisted_confirmation["status"] = "committed"
    proposal_stage = staging_root / proposal_path.name
    result_stage = staging_root / result_path.name
    confirmation_stage = staging_root / confirmation_path.name
    try:
        # Preflight runtime metadata before any formal YAML is committed.
        # This also preserves the old staging/symlink safety boundary.
        _atomic_text(proposal_stage, json.dumps(proposal, ensure_ascii=False, indent=2))
        _atomic_text(result_stage, json.dumps(result, ensure_ascii=False, indent=2))
        _atomic_text(confirmation_stage, json.dumps(persisted_confirmation, ensure_ascii=False, indent=2))

        if coordinator is None:
            active_coordinator = _build_default_mutation_coordinator(
                library_root=library_root,
                index_root=index_root,
                story_id=story_id,
                timeline_id=timeline_id,
            )
            graph_keys = (GraphKey(story_id, timeline_id),)
        else:
            try:
                graph_keys = (GraphKey(story_id, timeline_id),)
            except (TypeError, ValueError) as exc:
                raise WritebackError(f"无法构造目标 GraphKey: {exc}") from exc
            active_coordinator = coordinator
        try:
            change_set = ChangeSet(
                changes={target: history},
                affected_graph_keys=graph_keys,
                expected_file_fingerprints={target: target_fingerprint},
                change_id=writeback_id,
                metadata={"operation": "confirm_runtime", "story_id": story_id, "timeline_id": timeline_id},
            )
            mutation = active_coordinator.commit(change_set)
        except Exception as exc:
            raise WritebackError(f"MutationCoordinator 提交失败: {exc}") from exc
        if not hasattr(mutation, "yaml_committed"):
            raise WritebackError("MutationCoordinator.commit 未返回 MutationResult")
        mutation_status = str(getattr(mutation, "status", "promoted") or "promoted")

        def _result_items(value: Any) -> tuple[Any, ...]:
            if not value:
                return ()
            if isinstance(value, (str, bytes)):
                return (value,)
            try:
                return tuple(value)
            except TypeError:
                return (value,)

        pending_results = _result_items(getattr(mutation, "pending", ()))
        failed_results = _result_items(getattr(mutation, "failed", ()))
        if mutation_status == "failed" or not bool(mutation.yaml_committed) or failed_results:
            raise WritebackError(
                "回写失败，YAML 未提交: "
                + (getattr(mutation, "error", None) or "unknown mutation failure")
            )
        if mutation_status == "pending" or pending_results:
            proposal["status"] = "pending"
            proposal["mutation_status"] = mutation_status
            proposal["mutation_error"] = "; ".join(
                str(getattr(item, "error", "") or "") for item in pending_results
            )
            _atomic_text(proposal_stage, json.dumps(proposal, ensure_ascii=False, indent=2))
            os.replace(proposal_stage, proposal_path)
            shutil.rmtree(staging_root, ignore_errors=True)
            return WritebackResult(
                status="pending", writeback_id=writeback_id, document_ids=[document_id],
                history_path=str(target), state_promoted=False, retrieval_cases=retrieval_count,
            )

        os.replace(proposal_stage, proposal_path)
        os.replace(result_stage, result_path)
        os.replace(confirmation_stage, confirmation_path)
    except Exception as exc:
        # MutationCoordinator owns formal YAML rollback.  We only discard
        # uncommitted runtime staging; no second restore implementation exists.
        shutil.rmtree(staging_root, ignore_errors=True)
        if isinstance(exc, WritebackError):
            raise
        raise WritebackError(f"回写失败并已回滚未提交的变更: {exc}") from exc

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
