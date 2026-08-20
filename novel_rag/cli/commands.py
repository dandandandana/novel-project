"""CLI command implementations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..documents import read_yaml_mapping, registered_story_ids
from ..catalog.paths import timeline_registry_path
from ..graph import GraphError
from ..composition import (
    build_graph_retriever,
    build_mutation_coordinator,
    rebuild_graph_projections,
    search_graph,
    timeline_summary_root,
)
from ..identity import GraphKey
from ..generation import (
    GenerationError,
    LegacyRetrieverAdapter,
    PreferenceRequired,
    generate,
)
from ..model_api import ModelAPIError
from ..model_config import ModelConfigError
from ..resume import ResumeError, continue_generation
from ..writeback import WritebackError, confirm_runtime
from ..scaffold import create_story
from ..service import load_valid_documents
from ..state import StateReviewError, approve_state_proposal, inspect_state_proposal, reject_state_proposal
from ..importers import RagImportError, import_outline, import_rag_yaml, preview_outline, preview_rag_yaml
from ..feedback import FeedbackError, create_feedback, list_feedback, resolve_feedback
from ..doctor import run_doctor
from ..mutations import (
    SummaryDocument,
    SummaryEditor,
    SummaryError,
    SummaryStore,
    SummaryUpdate,
    SummaryWriter,
    MutationError,
)
from .helpers import _paths, _model_from_args


def command_validate(args: argparse.Namespace) -> int:
    documents, issues = load_valid_documents(
        Path(args.library).resolve(),
        story_id=getattr(args, "story", None),
    )
    for issue in issues:
        print(f"ERROR {issue.path}: {issue.message}")
    print(f"校验完成: {len(documents)} 个有效文档, {len(issues)} 个问题")
    return 1 if issues else 0


def command_doctor(args: argparse.Namespace) -> int:
    """Report installation capabilities required by graph projections."""

    del args  # The preflight intentionally has no filesystem or user options.
    report = run_doctor()
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


def command_index(args: argparse.Namespace) -> int:
    library, index_path = _paths(args)
    selected_story = getattr(args, "story", None)
    selected_timeline = getattr(args, "timeline", None)
    shared_only = bool(getattr(args, "shared", False))
    if shared_only and (selected_story or selected_timeline):
        print("ERROR --shared 不能与 --story/--timeline 同时使用")
        return 1
    if selected_timeline and not selected_story:
        print("ERROR --timeline 必须与 --story 一起使用")
        return 1
    documents, issues = load_valid_documents(
        library,
        story_id=selected_story if selected_story else None,
    )
    if issues:
        for issue in issues:
            print(f"ERROR {issue.path}: {issue.message}")
        print("存在校验错误，索引未更新。")
        return 1
    try:
        results = rebuild_graph_projections(
            index_path,
            documents,
            [selected_story] if selected_story else registered_story_ids(library),
            story_id=selected_story,
            timeline_id=selected_timeline,
            shared_only=shared_only,
            library_root=library,
            prune_stale=not bool(selected_story or shared_only),
        )
    except (GraphError, OSError, ValueError) as exc:
        print(f"ERROR {exc}")
        return 1
    total_documents = sum(result.document_count for result in results)
    total_chunks = sum(result.chunk_count for result in results)
    for result in results:
        print(
            f"索引分区: {result.scope} -> {result.document_count} 个文档, "
            f"{result.chunk_count} 个分块 -> {result.path}"
        )
    print(f"索引完成: {len(results)} 个隔离分区, {total_documents} 个文档, {total_chunks} 个分块")
    return 0


def command_search(args: argparse.Namespace) -> int:
    library, index_path = _paths(args)
    if args.story not in registered_story_ids(library):
        print(f"ERROR 未注册 story_id: {args.story}")
        return 1
    timeline_rows = read_yaml_mapping(
        timeline_registry_path(library, args.story)
    ).get("timelines", [])
    if not any(
        isinstance(row, dict)
        and row.get("story_id") == args.story
        and row.get("timeline_id") == args.timeline
        for row in timeline_rows if isinstance(timeline_rows, list)
    ):
        print(f"ERROR 未注册 timeline_id: {args.story}/{args.timeline}")
        return 1
    try:
        if bool(getattr(args, "legacy", False)):
            # The compatibility façade is reachable only through this
            # explicit migration switch. Canonical searches use the
            # composition root below.
            results = search_graph(
                index_path,
                args.query,
                GraphKey(args.story, args.timeline),
                document_types=args.type,
                statuses=args.status,
                limit=args.limit,
                include_shared=not args.no_shared,
                library_root=library,
                legacy=True,
            )
        else:
            results = search_graph(
                index_path,
                args.query,
                GraphKey(args.story, args.timeline),
                document_types=args.type,
                statuses=args.status,
                limit=args.limit,
                include_shared=not args.no_shared,
                library_root=library,
            )
    except (GraphError, OSError, ValueError) as exc:
        # The CLI turns a failed command into a diagnostic exit status, while
        # the Python compatibility function above deliberately propagates the
        # identity/stale/trigram error to its caller.
        print(f"ERROR {exc}")
        return 1
    output = [{
        "document_id": item.document_id, "title": item.title, "document_type": item.document_type,
        "status": item.status, "score": item.score, "source_file": item.source_file,
        "content": item.content, "metadata": item.metadata,
    } for item in results]
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def _summary_content(args: argparse.Namespace) -> str:
    content = getattr(args, "content", None)
    content_file = getattr(args, "content_file", None)
    if content is not None and content_file is not None:
        raise ValueError("--content 与 --content-file 只能提供一个")
    if content_file is not None:
        return Path(content_file).read_text(encoding="utf-8-sig")
    if content is None:
        raise ValueError("必须提供 --content 或 --content-file")
    return str(content)


def _summary_target(root: Path, value: str) -> Path:
    target = Path(value)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise SummaryError(f"摘要路径必须位于目标 timeline summaries 目录: {target}") from exc
    return target


def _summary_payload(document: SummaryDocument) -> dict[str, object]:
    metadata = dict(document.metadata)
    metadata.update(
        {
            "document_id": document.document_id,
            "ownership": document.ownership,
            "revision": document.revision,
            "stale": document.stale,
        }
    )
    if document.source_fingerprint is not None:
        metadata["source_fingerprint"] = document.source_fingerprint
    return {
        "path": str(document.path),
        "document_id": document.document_id,
        "content": document.content,
        "ownership": document.ownership,
        "source_fingerprint": document.source_fingerprint,
        "revision": document.revision,
        "stale": document.stale,
        "metadata": metadata,
    }


def _summary_documents(root: Path) -> list[SummaryDocument]:
    if not root.is_dir():
        return []
    documents: list[SummaryDocument] = []
    for path in sorted((*root.rglob("*.yaml"), *root.rglob("*.yml"))):
        try:
            documents.append(SummaryDocument.from_yaml(path))
        except SummaryError:
            # Listing remains useful when one unrelated YAML is malformed;
            # show/edit still surface an exact error for the requested ID.
            continue
    return documents


def command_summary(args: argparse.Namespace) -> int:
    """List, inspect, or edit timeline summaries through MutationCoordinator."""

    library, index_path = _paths(args)
    try:
        key = GraphKey(args.story, args.timeline)
        root = timeline_summary_root(library, key)
        action = args.summary_action
        if action == "list":
            print(json.dumps(
                [_summary_payload(document) for document in _summary_documents(root)],
                ensure_ascii=False,
                indent=2,
            ))
            return 0

        coordinator = build_mutation_coordinator(library, index_directory=index_path)
        store = SummaryStore(root)
        if action == "show":
            print(json.dumps(
                _summary_payload(store.find(args.document_id)),
                ensure_ascii=False,
                indent=2,
                default=str,
            ))
            return 0
        if action == "edit":
            updated = SummaryEditor(root, coordinator=coordinator).update(
                SummaryUpdate(
                    args.document_id,
                    expected_revision=args.expected_revision,
                    content=_summary_content(args),
                )
            )
            print(json.dumps(_summary_payload(updated), ensure_ascii=False, indent=2, default=str))
            return 0
        if action == "write-ai":
            target = _summary_target(root, args.path)
            metadata = {
                "story_id": key.story_id,
                "timeline_id": key.timeline_id,
                "document_type": args.document_type,
                "generated_by": args.generated_by,
            }
            written = SummaryWriter(root, coordinator=coordinator).write_ai(
                target,
                _summary_content(args),
                document_id=args.document_id,
                source_fingerprint=args.source_fingerprint,
                metadata=metadata,
            )
            print(json.dumps(_summary_payload(written), ensure_ascii=False, indent=2, default=str))
            return 0
        raise SummaryError(f"未知 summary 操作: {action}")
    except (SummaryError, GraphError, OSError, ValueError) as exc:
        print(f"ERROR {exc}")
        return 1


def _mutation_result_payload(result: object) -> dict[str, object]:
    rows = []
    for item in getattr(result, "graph_results", ()):
        key = getattr(item, "key", None)
        key_value = key.as_dict() if hasattr(key, "as_dict") else str(key)
        rows.append({
            "key": key_value,
            "status": getattr(item, "status", None),
            "target_path": str(getattr(item, "target_path", "")) if getattr(item, "target_path", None) else None,
            "staged_path": str(getattr(item, "staged_path", "")) if getattr(item, "staged_path", None) else None,
            "error": getattr(item, "error", None),
        })
    return {
        "status": getattr(result, "status", None),
        "change_id": getattr(result, "change_id", None),
        "yaml_committed": getattr(result, "yaml_committed", False),
        "staging_root": str(getattr(result, "staging_root", "")) if getattr(result, "staging_root", None) else None,
        "error": getattr(result, "error", None),
        "graphs": rows,
    }


def command_pending(args: argparse.Namespace) -> int:
    """List or retry durable graph-promotion pending manifests."""

    library, index_path = _paths(args)
    try:
        coordinator = build_mutation_coordinator(library, index_directory=index_path)
        if args.pending_action == "list":
            print(json.dumps(coordinator.list_pending(), ensure_ascii=False, indent=2, default=str))
            return 0
        results = coordinator.retry_persisted_pending()
        payload = [_mutation_result_payload(result) for result in results]
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0 if all(item["status"] in {"promoted", "noop"} for item in payload) else 1
    except (MutationError, GraphError, OSError, ValueError) as exc:
        print(f"ERROR {exc}")
        return 1


def command_list_stories(args: argparse.Namespace) -> int:
    library = Path(args.library).resolve()
    rows = read_yaml_mapping(library / "registry" / "stories.yaml").get("stories", [])
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def command_create_story(args: argparse.Namespace) -> int:
    root = create_story(
        Path(args.library).resolve(),
        story_id=args.story_id,
        title=args.title,
        timeline_id=args.timeline,
        timeline_name=args.timeline_name,
        language=args.language,
        inherit_shared=not args.no_shared,
    )
    print(f"小说隔离目录已创建: {root}")
    return 0


def command_generate(args: argparse.Namespace) -> int:
    outline_path = Path(args.outline)
    outline = outline_path.read_text(encoding="utf-8-sig") if outline_path.is_file() else args.outline
    request = {"story_id": args.story, "timeline_id": args.timeline, "outline": outline,
               "current_request": args.request or "", "references": [],
               "length": {"target": args.length_target, "min": args.length_min, "max": args.length_max,
                          "expansion_points": args.expand_at}}
    for reference in args.reference or []:
        path = Path(reference)
        request["references"].append(path.read_text(encoding="utf-8-sig") if path.is_file() else reference)
    library_root = Path(args.library).resolve()
    index_root = Path(args.index).resolve() if args.index else library_root / "index"
    retriever = None
    try:
        model = _model_from_args(args)
        if getattr(args, "legacy", False):
            # ``--legacy`` is an explicit migration mode.  Inject the
            # generation package's adapter so generate() cannot silently pick
            # the default graph composition root.
            retriever = LegacyRetrieverAdapter(library_root, index_root)
        else:
            retriever = build_graph_retriever(
                library_root,
                GraphKey(args.story, args.timeline),
                index_directory=index_root,
            )
        result = generate(request, model, library_root=library_root,
                          index_root=index_root,
                          output_root=Path(args.output_root).resolve() if args.output_root else None,
                          task_id=args.task_id, retriever=retriever)
    except PreferenceRequired as exc:
        print(f"AUTHOR_PREFERENCES_REQUIRED {exc.path}")
        return 2
    except (GenerationError, ModelAPIError, ModelConfigError, GraphError, OSError, ValueError) as exc:
        print(f"ERROR {exc}")
        return 1
    finally:
        close = getattr(retriever, "close", None)
        if callable(close):
            close()
    print(result.text)
    for warning in result.warnings:
        print(f"WARNING {warning}", file=sys.stderr)
    if result.status == "user_guidance_required":
        print("WARNING 自动修复三次后仍有问题，请提供进一步写作指导。", file=sys.stderr)
        return 3
    return 0


def command_continue(args: argparse.Namespace) -> int:
    guidance_path = Path(args.guidance)
    guidance = guidance_path.read_text(encoding="utf-8-sig") if guidance_path.is_file() else args.guidance
    try:
        model = _model_from_args(args)
        result = continue_generation(
            Path(args.runtime), guidance, model, library_root=Path(args.library).resolve(),
            index_root=Path(args.index).resolve() if args.index else None,
            output_root=Path(args.output_root).resolve() if args.output_root else None,
            task_id=args.task_id,
        )
    except (GenerationError, ResumeError, ModelAPIError, ModelConfigError, OSError) as exc:
        print(f"ERROR {exc}")
        return 1
    print(result.text)
    print(f"RUNTIME {result.extensions.get('runtime_dir', '')}", file=sys.stderr)
    for warning in result.warnings:
        print(f"WARNING {warning}", file=sys.stderr)
    return 3 if result.status == "user_guidance_required" else 0


def command_init_preferences(args: argparse.Namespace) -> int:
    library = Path(args.library).resolve()
    path = library / "stories" / args.story / "author-preferences.txt"
    if args.story not in registered_story_ids(library):
        print(f"ERROR 未注册 story_id: {args.story}")
        return 1
    if path.exists() and path.read_text(encoding="utf-8-sig").strip() and not args.force:
        print(f"作者偏好已存在: {path}")
        return 1
    template = library / "templates" / "author-preferences.txt"
    text = template.read_text(encoding="utf-8-sig") if template.exists() else "【未指定】\n按当前任务要求和系统默认执行。\n"
    path.write_text(text, encoding="utf-8")
    print(f"作者偏好模板已创建，请填写后再生成: {path}")
    return 0


def command_confirm(args: argparse.Namespace) -> int:
    try:
        result = confirm_runtime(
            Path(args.runtime), library_root=Path(args.library),
            index_root=Path(args.index) if args.index else None, confirmed=args.yes,
            volume=args.volume, chapter=args.chapter, scene=args.scene,
            title=args.title or "", pov=args.pov or "",
            character_ids=args.character, location_ids=args.location,
        )
    except (WritebackError, OSError) as exc:
        print(f"ERROR {exc}")
        return 1
    print(json.dumps({name: getattr(result, name) for name in result.__dataclass_fields__},
                     ensure_ascii=False, indent=2))
    return 0


def command_state_review(args: argparse.Namespace) -> int:
    try:
        value = inspect_state_proposal(Path(args.runtime), library_root=Path(args.library).resolve())
    except (StateReviewError, OSError) as exc:
        print(f"ERROR {exc}")
        return 1
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    return 0


def command_state_approve(args: argparse.Namespace) -> int:
    if not args.yes:
        print("ERROR 必须传入 --yes 表示已核对最终正文和状态变化")
        return 1
    try:
        value = approve_state_proposal(
            Path(args.runtime), library_root=Path(args.library).resolve(),
            index_root=Path(args.index).resolve() if args.index else None,
            character_ids=args.character, include_world=not args.no_world, note=args.note or "",
        )
    except (StateReviewError, OSError) as exc:
        print(f"ERROR {exc}")
        return 1
    print(json.dumps({name: getattr(value, name) for name in value.__dataclass_fields__},
                     ensure_ascii=False, indent=2, default=str))
    return 0


def command_state_reject(args: argparse.Namespace) -> int:
    if not args.yes:
        print("ERROR 必须传入 --yes 明确拒绝该提案")
        return 1
    try:
        value = reject_state_proposal(Path(args.runtime), library_root=Path(args.library).resolve(),
                                      reason=args.reason)
    except (StateReviewError, OSError) as exc:
        print(f"ERROR {exc}")
        return 1
    print(json.dumps({name: getattr(value, name) for name in value.__dataclass_fields__},
                     ensure_ascii=False, indent=2, default=str))
    return 0


def _dataclass_json(value) -> str:
    return json.dumps({name: getattr(value, name) for name in value.__dataclass_fields__},
                      ensure_ascii=False, indent=2, default=str)


def command_import_rag(args: argparse.Namespace) -> int:
    try:
        library, index = _paths(args)
        preview = preview_rag_yaml(
            Path(args.source), library_root=library, index_root=index,
            story_id=args.story, timeline_id=args.timeline, version=args.version,
            supersedes=args.supersedes, document_family=args.family,
        )
        print(_dataclass_json(preview))
        if not args.yes:
            print("PREVIEW_ONLY 使用 --yes 才会写入正式 RAG")
            return 0
        if preview.conflicts:
            print("ERROR 预览存在冲突；请显式提供新版本、supersedes 和 document_family")
            return 1
        result = import_rag_yaml(
            Path(args.source), library_root=library, index_root=index,
            story_id=args.story, timeline_id=args.timeline, version=args.version,
            supersedes=args.supersedes, document_family=args.family,
            coordinator=build_mutation_coordinator(library, index_directory=index),
        )
    except (RagImportError, GraphError, OSError, ValueError) as exc:
        print(f"ERROR {exc}")
        return 1
    print(_dataclass_json(result))
    return 0


def command_import_outline(args: argparse.Namespace) -> int:
    try:
        library, index = _paths(args)
        preview = preview_outline(
            Path(args.source), library_root=library, index_root=index,
            story_id=args.story, timeline_id=args.timeline, title=args.title,
            volume=args.volume, chapter=args.chapter, version=args.version,
            supersedes=args.supersedes, document_family=args.family,
        )
        print(_dataclass_json(preview))
        if not args.yes:
            print("PREVIEW_ONLY 使用 --yes 才会写入正式 Outline")
            return 0
        if preview.conflicts:
            print("ERROR 预览存在冲突；请显式提供新版本、supersedes 和 document_family")
            return 1
        result = import_outline(
            Path(args.source), library_root=library, index_root=index,
            story_id=args.story, timeline_id=args.timeline, title=args.title,
            volume=args.volume, chapter=args.chapter, version=args.version,
            supersedes=args.supersedes, document_family=args.family,
            coordinator=build_mutation_coordinator(library, index_directory=index),
        )
    except (RagImportError, GraphError, OSError, ValueError) as exc:
        print(f"ERROR {exc}")
        return 1
    print(_dataclass_json(result))
    return 0


def command_feedback_create(args: argparse.Namespace) -> int:
    if not args.yes:
        print("ERROR Feedback 会进入正式 RAG；必须传入 --yes 明确确认")
        return 1
    try:
        library, index = _paths(args)
        result = create_feedback(
            library_root=library, index_root=index, story_id=args.story, timeline_id=args.timeline,
            target_type=args.target_type, target_id=args.target_id, issue=args.issue,
            user_comment=args.comment or "", affected_scope=args.scope or "",
            correction_rule=args.rule, examples=args.example,
            runtime_dir=args.runtime, history_id=args.history_id,
            version=args.version, supersedes=args.supersedes, document_family=args.family,
            coordinator=build_mutation_coordinator(library, index_directory=index),
        )
    except (FeedbackError, RagImportError, GraphError, OSError, ValueError) as exc:
        print(f"ERROR {exc}")
        return 1
    print(_dataclass_json(result))
    return 0


def command_feedback_list(args: argparse.Namespace) -> int:
    try:
        library, index = _paths(args)
        rows = list_feedback(library_root=library, index_root=index, story_id=args.story,
                             timeline_id=args.timeline, status=args.status,
                             target_type=args.target_type, target_id=args.target_id)
    except (FeedbackError, RagImportError, GraphError, OSError, ValueError) as exc:
        print(f"ERROR {exc}")
        return 1
    print(json.dumps([{name: getattr(row, name) for name in row.__dataclass_fields__} for row in rows],
                     ensure_ascii=False, indent=2, default=str))
    return 0


def command_feedback_resolve(args: argparse.Namespace) -> int:
    if not args.yes:
        print("ERROR 必须传入 --yes 明确创建解决版本")
        return 1
    try:
        library, index = _paths(args)
        result = resolve_feedback(
            library_root=library, index_root=index, story_id=args.story, timeline_id=args.timeline,
            feedback_id=args.feedback_id, resolution=args.resolution, version=args.version,
            supersedes=args.feedback_id,
            coordinator=build_mutation_coordinator(library, index_directory=index),
        )
    except (FeedbackError, RagImportError, OSError) as exc:
        print(f"ERROR {exc}")
        return 1
    print(_dataclass_json(result))
    return 0


def command_api_config(args: argparse.Namespace) -> int:
    from ..model_config import ModelConfigError, ModelConfigStore
    store = ModelConfigStore(args.model_config)
    try:
        if args.config_action == "path":
            print(store.path)
            return 0
        if args.config_action == "list":
            document = store.load()
            print(json.dumps({"path": str(store.path), "active": document.get("active"),
                              "profiles": store.list_profiles()}, ensure_ascii=False, indent=2))
            return 0
        if args.config_action == "show":
            profile = store.get(args.name)
            if profile is None:
                raise ModelConfigError(f"找不到模型 profile: {args.name or 'active'}")
            print(json.dumps({"name": profile.name, **profile.to_dict()}, ensure_ascii=False, indent=2))
            return 0
        if args.config_action == "set":
            updates = {key: value for key, value in {
                "base_url": args.base_url, "model": args.model, "mode": args.mode,
                "timeout": args.timeout, "retries": args.retries,
                "max_output_tokens": args.max_output_tokens, "no_auth": args.no_auth,
            }.items() if value is not None}
            if args.api_key_file:
                updates["api_key"] = Path(args.api_key_file).read_text(encoding="utf-8-sig").strip()
            elif args.api_key_stdin:
                updates["api_key"] = sys.stdin.read().strip()
            profile = store.set_profile(args.name, updates)
            if args.active:
                store.set_active(args.name)
            print(json.dumps({"path": str(store.path), "active": store.load().get("active"),
                              "profile": {"name": profile.name, **profile.to_dict()}},
                             ensure_ascii=False, indent=2))
            return 0
        if args.config_action == "use":
            store.set_active(args.name)
            print(f"当前模型 profile: {args.name}")
            return 0
        if args.config_action == "delete":
            if not args.yes:
                raise ModelConfigError("删除 profile 必须传入 --yes")
            removed = store.delete_profile(args.name)
            print("deleted" if removed else "not_found")
            return 0
        raise ModelConfigError("未知 api-config 操作")
    except (ModelConfigError, OSError) as exc:
        print(f"ERROR {exc}")
        return 1


def command_tui(args: argparse.Namespace) -> int:
    from ..tui import run_tui
    library, index = _paths(args)
    return run_tui(library, index, model_config_path=Path(args.model_config))
