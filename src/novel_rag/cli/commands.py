"""CLI command implementations."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from importlib import import_module as _import_module

from .helpers import _paths, _model_from_args

# Retain the original module attributes as lazy replacement points for legacy callers.
_EXPORT_MODULES = {
    "read_yaml_mapping": "..documents",
    "registered_story_ids": "..documents",
    "timeline_registry_path": "..catalog.paths",
    "GraphError": "..graph",
    "build_graph_retriever": "..composition",
    "build_mutation_coordinator": "..composition",
    "rebuild_graph_projections": "..composition",
    "search_graph": "..composition",
    "timeline_summary_root": "..composition",
    "GraphKey": "..identity",
    "StoryCoordinate": "..identity",
    "GenerationError": "..generation",
    "LegacyRetrieverAdapter": "..generation",
    "PreferenceRequired": "..generation",
    "generate": "..generation",
    "ModelAPIError": "..model_api",
    "ModelConfigError": "..model_config",
    "ResumeError": "..resume",
    "continue_generation": "..resume",
    "WritebackError": "..writeback",
    "confirm_runtime": "..writeback",
    "create_story": "..scaffold",
    "load_story_sources": "..service",
    "load_valid_documents": "..service",
    "StateReviewError": "..state",
    "approve_state_proposal": "..state",
    "inspect_state_proposal": "..state",
    "reject_state_proposal": "..state",
    "RagImportError": "..importers",
    "import_outline": "..importers",
    "import_rag_yaml": "..importers",
    "preview_outline": "..importers",
    "preview_rag_yaml": "..importers",
    "FeedbackError": "..feedback",
    "create_feedback": "..feedback",
    "list_feedback": "..feedback",
    "resolve_feedback": "..feedback",
    "run_doctor": "..doctor",
    "SummaryDocument": "..mutations",
    "SummaryEditor": "..mutations",
    "SummaryError": "..mutations",
    "SummaryStore": "..mutations",
    "SummaryUpdate": "..mutations",
    "SummaryWriter": "..mutations",
    "MutationError": "..mutations",
}


def __getattr__(name: str):
    """依赖：importlib与原业务owner。输入：旧模块依赖名。输出：原对象或AttributeError。实现：首次按需加载并缓存，命令自本模块取值以保留既有替换点。"""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(_import_module(module_name, __package__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """依赖：命名空间与旧依赖导出表。输入：无。输出：原名称集合。实现：合并可发现名称，不装配未选命令。"""
    return sorted(set(globals()) | set(_EXPORT_MODULES))


def command_validate(args: argparse.Namespace) -> int:
    """依赖：原文档校验。输入：库根/作品过滤。输出：问题及退出码。实现：执行时加载owner并打印原结果。"""

    from .commands import load_valid_documents

    documents, issues = load_valid_documents(
        Path(args.library).resolve(),
        story_id=getattr(args, "story", None),
    )
    for issue in issues:
        print(f"ERROR {issue.path}: {issue.message}")
    print(f"校验完成: {len(documents)} 个有效文档, {len(issues)} 个问题")
    return 1 if issues else 0


def command_doctor(args: argparse.Namespace) -> int:
    """依赖：原标准库能力探针。输入：CLI参数。输出：能力JSON及退出码。实现：只加载doctor并执行原探针。"""

    from .commands import run_doctor

    del args  # The preflight intentionally has no filesystem or user options.
    report = run_doctor()
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


def command_index(args: argparse.Namespace) -> int:
    """依赖：原文档与图组合根。输入：作品/时间线索引参数。输出：分区结果及退出码。实现：执行时加载索引能力并保留过滤和校验。"""

    from .commands import GraphError, load_valid_documents, rebuild_graph_projections, registered_story_ids

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
    """依赖：原检索组合根。输入：作用域、查询与legacy开关。输出：命中JSON及退出码。实现：按命令加载检索并保持显式legacy分流。"""

    from .commands import (
        GraphError, GraphKey, read_yaml_mapping, registered_story_ids, search_graph,
        timeline_registry_path,
    )

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
    """依赖：Path与原SummaryError。输入：摘要根和目标。输出：范围内绝对路径或错误。实现：解析路径并验证目标仍位于摘要根。"""

    from .commands import SummaryError

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
    """依赖：原SummaryDocument。输入：摘要目录。输出：可读摘要列表。实现：排序读取并保留坏单项的既有跳过行为。"""

    from .commands import SummaryDocument, SummaryError

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
    """依赖：原摘要owner/协调器。输入：查看或编辑参数。输出：摘要JSON及退出码。实现：按命令加载，保留commands协调器替换点及CAS。"""

    from .commands import (
        GraphError, GraphKey, SummaryEditor, SummaryError, SummaryStore, SummaryUpdate, SummaryWriter,
        build_mutation_coordinator, timeline_summary_root,
    )

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
    """依赖：原变更协调器。输入：pending动作。输出：原日志或重试结果及退出码。实现：执行时加载并委托同一协调器。"""

    from .commands import GraphError, MutationError, build_mutation_coordinator

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
    """依赖：原YAML加载器。输入：库根。输出：作品清单及退出码。实现：读取原注册表并打印JSON。"""

    from .commands import read_yaml_mapping

    library = Path(args.library).resolve()
    rows = read_yaml_mapping(library / "registry" / "stories.yaml").get("stories", [])
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def command_create_story(args: argparse.Namespace) -> int:
    """依赖：原scaffold。输入：作品及时间线参数。输出：目录提示及退出码。实现：执行时委托唯一建树owner。"""

    from .commands import create_story

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
    """依赖：原v2生成/检索/模型。输入：旧生成参数。输出：正文、诊断及退出码。实现：从本模块惰性解析原替换点，保持legacy分流和reader释放。"""

    from .commands import (
        GenerationError, GraphError, GraphKey, LegacyRetrieverAdapter, ModelAPIError, ModelConfigError,
        PreferenceRequired, build_graph_retriever, generate,
    )

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
    """依赖：原v2续写/模型。输入：runtime和指导。输出：正文、诊断及退出码。实现：执行时加载原续写能力并保留错误语义。"""

    from .commands import GenerationError, ModelAPIError, ModelConfigError, ResumeError, continue_generation

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
    """依赖：原作品注册查询。输入：作品及force参数。输出：偏好文件提示及退出码。实现：核注册和覆盖条件后沿原模板写入。"""

    from .commands import registered_story_ids

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
    """依赖：原v2 confirm。输入：runtime及作者采用参数。输出：原回执或错误及退出码。实现：执行时加载旧采用并保留确认语义。"""

    from .commands import WritebackError, confirm_runtime

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
    """依赖：原v2状态审阅。输入：runtime与库。输出：提案JSON及退出码。实现：只在旧命令执行时读取原提案。"""

    from .commands import StateReviewError, inspect_state_proposal

    try:
        value = inspect_state_proposal(Path(args.runtime), library_root=Path(args.library).resolve())
    except (StateReviewError, OSError) as exc:
        print(f"ERROR {exc}")
        return 1
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    return 0


def command_state_approve(args: argparse.Namespace) -> int:
    """依赖：原v2状态批准。输入：runtime和作者确认。输出：原回执及退出码。实现：保留yes门并委托原批准入口。"""

    from .commands import StateReviewError, approve_state_proposal

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
    """依赖：原v2状态拒绝。输入：runtime和作者确认。输出：原回执及退出码。实现：保留yes门并委托原拒绝入口。"""

    from .commands import StateReviewError, reject_state_proposal

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
    """依赖：原RAG导入/协调器。输入：来源与目标参数。输出：预览或提交结果及退出码。实现：惰性加载并保留预览、冲突和确认门。"""

    from .commands import (
        GraphError, RagImportError, build_mutation_coordinator, import_rag_yaml, preview_rag_yaml,
    )

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
    """依赖：原大纲导入/协调器。输入：来源与目标参数。输出：预览或提交结果及退出码。实现：惰性加载并保留预览、冲突和确认门。"""

    from .commands import (
        GraphError, RagImportError, build_mutation_coordinator, import_outline, preview_outline,
    )

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
    """依赖：原feedback/协调器。输入：反馈参数和确认。输出：原创建结果及退出码。实现：执行时加载并保留确认门与提交owner。"""

    from .commands import (
        FeedbackError, GraphError, RagImportError, build_mutation_coordinator, create_feedback,
    )

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
    """依赖：原feedback查询。输入：作用域与过滤参数。输出：反馈JSON及退出码。实现：执行时委托原查询。"""

    from .commands import FeedbackError, GraphError, RagImportError, list_feedback

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
    """依赖：原feedback/协调器。输入：反馈及解决版本参数。输出：原结果及退出码。实现：执行时加载并保留确认和版本语义。"""

    from .commands import FeedbackError, RagImportError, build_mutation_coordinator, resolve_feedback

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
    from ..tui.console import run_console

    library, index = _paths(args)
    model_config = Path(args.model_config)
    mode = getattr(args, "console", False), getattr(args, "plain", False)
    if not mode[1]:
        try:
            code = run_console(library, index, model_config_path=model_config)
        except Exception:
            code = None
        if code is not None:
            return code
    return run_tui(library, index, model_config_path=model_config)


def _safe_writer_error(error: object, model_config_path: Path,
                       profile_name: str | None) -> dict[str, str]:
    """依赖：安全异常字段与本地模型配置。输入：异常或错误映射及profile位置。输出：仅含code/message的安全错误。实现：校验错误码并从消息中移除已配置密钥。"""

    if isinstance(error, dict):
        raw_code = error.get("code") or error.get("error_code")
        raw_message = error.get("message") or error.get("safe_message")
    else:
        raw_code = getattr(error, "code", None) or getattr(error, "error_code", None)
        raw_message = getattr(error, "safe_message", None) or getattr(error, "message", None)
        if not isinstance(raw_message, str):
            raw_message = str(error)

    code = str(raw_code or "write_failed")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
        code = "write_failed"
    message = str(raw_message or "写作运行失败；请检查本地配置和作品来源。")

    try:
        from ..model_config import ModelConfigStore

        profile = ModelConfigStore(model_config_path).get(profile_name)
        secret = profile.api_key if profile is not None else None
    except Exception:
        secret = None
    if secret:
        message = message.replace(secret, "[已隐藏]")
    return {"code": code, "message": message}


def command_write(args: argparse.Namespace) -> int:
    """依赖：RunService应用结果/生命周期锁及async运行时。输入：作品、原纲、请求和来源/坐标。输出：原五字段JSON与退出码。实现：独占启动后读取应用结果，CLI只脱敏/打印错误，异常保留草稿。"""

    from .commands import GraphKey, StoryCoordinate, load_story_sources

    service = None
    run_id: str | None = None
    output: dict = {}
    model_config_path = Path(args.model_config).resolve()
    profile_name = getattr(args, "profile", None)
    try:
        library_root = Path(args.library).resolve()
        workspace_value = getattr(args, "workspace", None)
        workspace_root = Path(workspace_value).resolve() if workspace_value else None
        outline_path = Path(args.outline_file)
        outline = outline_path.read_text(encoding="utf-8-sig")
        request = getattr(args, "request", "") or ""
        scope = GraphKey(args.story, args.timeline)

        coordinate_values = tuple(
            getattr(args, name, None) for name in ("volume", "chapter", "scene")
        )
        if any(value is not None for value in coordinate_values):
            if any(value is None for value in coordinate_values):
                raise ValueError("volume、chapter、scene 必须同时提供")
            target_coordinate = StoryCoordinate(*coordinate_values)
        else:
            target_coordinate = None

        base_ref = None
        base_document = getattr(args, "base_document", None)
        if base_document:
            sources = load_story_sources(library_root, scope)
            source_ref = sources.source_refs.get(base_document)
            if source_ref is None:
                raise ValueError(f"当前作品作用域中找不到基础文档: {base_document}")
            base_ref = source_ref.as_dict()

        from ..composition import build_writer_service

        service = build_writer_service(
            library_root,
            workspace_root=workspace_root,
            model_config_path=model_config_path,
        )
        with service.writer_lease():
            run_id = service.start(
                scope,
                task_kind=args.task_kind,
                outline=outline,
                request=request,
                base_ref=base_ref,
                target_coordinate=target_coordinate,
                profile_name=profile_name,
            )
            asyncio.run(service.run(run_id))
            output = service.run_result(run_id)
        if not isinstance(output, dict):
            raise TypeError("写作服务返回了无效运行快照")

        if output["error"] is not None:
            output["error"] = _safe_writer_error(output["error"], model_config_path, profile_name)
        print(json.dumps(output, ensure_ascii=False))
        return 0 if output["status"] == "completed" else 1
    except Exception as exc:
        output = {}
        if service is not None and run_id is not None:
            try:
                output = service.run_result(run_id, error=exc)
            except Exception:
                output = {}
        if not isinstance(output, dict) or not output:
            output = {"run_id": run_id, "status": "failed" if run_id is None else "interrupted",
                      "draft_ref": None, "draft_text": "", "error": exc}
        output["error"] = _safe_writer_error(output["error"], model_config_path, profile_name)
        print(json.dumps(output, ensure_ascii=False))
        return 1


def command_harness(args: argparse.Namespace) -> int:
    """依赖：薄BackendClient/McpStdioAdapter/已有身份类型。输入：host动作、固定后端和run或原纲。输出：JSON/stdio协议/退出码。实现：只连接既有单写者，不打开Store/模型；写失败保留原request ID。"""
    import sys
    from uuid import uuid4
    from ..harness import BackendClient, BackendError, McpStdioAdapter

    request_id, run_id = getattr(args, "request_id", None), getattr(args, "run_id", None)
    output = {}
    try:
        client = BackendClient(args.backend)
        if args.harness_action == "mcp":
            return McpStdioAdapter(client, run_id).run()
        if args.harness_action == "prepare":
            request_id = request_id or "prepare-" + uuid4().hex
            data = {"driver": "harness", "story_id": args.story, "timeline_id": args.timeline,
                    "outline": Path(args.outline_file).read_text(encoding="utf-8-sig"),
                    "request": args.request, "task_kind": args.task_kind, "request_id": request_id}
            if args.base_ref_file:
                data["base_ref"] = json.loads(Path(args.base_ref_file).read_text(encoding="utf-8-sig"))
            if args.target_coordinate:
                data["target_coordinate"] = json.loads(args.target_coordinate)
            output = client.request("/api/v1/runs", data)
            run_id = output["run_id"]
            output.update(request_id=request_id, backend=client.backend, backend_identity=client.identity,
                          workspace_url=client.backend + "/?run=" + run_id)
            output["context"] = client.request(client.run_path(run_id, "/harness-context"))
        elif args.harness_action == "context":
            output = client.request(client.run_path(run_id, "/harness-context"))
        elif args.harness_action == "status":
            output = client.request(client.run_path(run_id))
        elif args.harness_action == "cancel":
            output = client.request(client.run_path(run_id, "/cancel"), {})
        else:
            data = {"status": args.status}
            if args.discussion_file:
                data["discussion_text"] = Path(args.discussion_file).read_text(encoding="utf-8-sig")
            output = client.request(client.run_path(run_id, "/harness-finish"), data)
        print(json.dumps(output, ensure_ascii=False))
        return 0
    except (BackendError, ValueError, OSError, KeyError) as exc:
        output.update(run_id=run_id, request_id=request_id,
                      error=exc.error if isinstance(exc, BackendError) else {"code": "source_invalid", "message": str(exc)})
        print(json.dumps(output, ensure_ascii=False), file=sys.stderr if args.harness_action == "mcp" else sys.stdout)
        return 1


def command_workspace(args: argparse.Namespace) -> int:
    """依赖：可选FastAPI/Uvicorn及同一web应用工厂。输入：库、工作区、模型配置和端口。输出：本机网页服务退出码。实现：延迟导入可选运行依赖并固定监听127.0.0.1。"""

    try:
        import uvicorn
        from ..web.app import create_app
    except ImportError:
        print(json.dumps({
            "error": {
                "code": "capability_missing",
                "message": "workspace 需要安装 FastAPI 和 Uvicorn 可选依赖。",
            }
        }, ensure_ascii=False))
        return 1

    library_root = Path(args.library).resolve()
    workspace_value = getattr(args, "workspace", None)
    workspace_root = Path(workspace_value).resolve() if workspace_value else None
    model_config_path = Path(args.model_config).resolve()
    try:
        app = create_app(
            library_root,
            workspace_root=workspace_root,
            model_config_path=model_config_path,
        )
    except ImportError:
        print(json.dumps({
            "error": {
                "code": "capability_missing",
                "message": "workspace 需要安装 FastAPI 和 Uvicorn 可选依赖。",
            }
        }, ensure_ascii=False))
        return 1
    uvicorn.run(app, host="127.0.0.1", port=args.port)
    return 0


# Preserve the previous implicit star exports, including original dependency names.
__all__ = [name for name in globals() if not name.startswith("_")] + list(_EXPORT_MODULES)
