"""Main TUI menu loop."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from ..documents import registered_story_ids
from ..feedback import create_feedback, list_feedback, resolve_feedback
from ..generation import GenerationError, PreferenceRequired, generate
from ..importers import (
    RagImportError,
    import_outline,
    import_rag_yaml,
    preview_outline,
    preview_rag_yaml,
)
from ..composition import (
    build_graph_retriever,
    build_mutation_coordinator,
    rebuild_graph_projections,
    search_graph,
    timeline_summary_root,
)
from ..graph import GraphError
from ..identity import GraphKey
from ..model_api import ModelAPIError
from ..model_config import ModelConfigError, default_config_path
from ..mutations import SummaryDocument, SummaryEditor, SummaryError, SummaryStore, SummaryUpdate, SummaryWriter
from ..resume import continue_generation
from ..service import load_valid_documents
from ..state import approve_state_proposal, inspect_state_proposal, reject_state_proposal
from ..writeback import WritebackError, confirm_runtime
from .helpers import (
    Input, Output, ask, number, choose, timeline_ids, reference_texts,
    outline_input, text_preview, latest_runtime, show_runtime, model_from_local_config,
    confirm_review, dataclass_preview, confirm_word, matches_word, list_summary_documents, suggest_task_id,
    render_rows, pick_file_from_directory,
)
from .wizards import api_config_wizard, preferences_wizard, create_story_wizard
from .session import create_interactive_io


_EXIT_WORDS = {"0", "q", "quit", "exit"}

_MENU_TEXT = (
    "\n—— 写作流 ——\n"
    "1. 生成草稿\n"
    "2. 查看最近运行\n"
    "3. 继续需要指导的任务\n"
    "4. 确认并回写\n"
    "5. 审核状态提案\n"
    "—— 资料与库 ——\n"
    "6. 上传大纲\n"
    "7. 上传 RAG YAML\n"
    "8. 校验并重建索引\n"
    "9. 检索\n"
    "—— 作品与设置 ——\n"
    "10. 作品/时间线与作者偏好\n"
    "11. 本地模型 API 设置\n"
    "12. Feedback 管理\n"
    "13. 摘要管理\n"
    "—— 维护 ——\n"
    "14. Pending 图恢复\n"
    "0. 退出（q/Q 同效）"
)


def _summary_payload(document: SummaryDocument) -> dict[str, Any]:
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


def _load_summaries(root: Path) -> list[SummaryDocument]:
    return list_summary_documents(root)


def _choose_upload_file(prompt: str, input_fn: Input, output: Output) -> Path | None:
    """空回车进入目录浏览；已存在的目录作为浏览起点；其余按路径采用。"""

    value = ask(input_fn, prompt)
    if not value:
        return pick_file_from_directory(input_fn, output, start=Path.cwd())
    candidate = Path(value)
    if candidate.is_dir():
        return pick_file_from_directory(input_fn, output, start=candidate)
    return candidate


def _choose_summary(
    root: Path,
    input_fn: Input,
    output: Output,
) -> SummaryDocument | None:
    """List existing summaries first, then pick one by number."""

    rows = _load_summaries(root)
    if not rows:
        output("当前 timeline 还没有摘要。")
        return None
    document_id = choose(input_fn, output, "摘要", [row.document_id for row in rows])
    for row in rows:
        if row.document_id == document_id:
            return row
    return None


def summary_menu(
    library_root: Path,
    index_root: Path,
    key: GraphKey,
    coordinator: Any,
    input_fn: Input,
    output: Output,
) -> None:
    """List / view / edit / write summaries for the current timeline.

    供 plain 菜单与 console 共同复用；console 经桥接 io 注入。
    """
    root = timeline_summary_root(library_root, key)
    store = SummaryStore(root)
    output("1. 列出摘要  2. 查看摘要  3. 编辑摘要  4. 写入 AI 摘要  其他. 返回")
    action = ask(input_fn, "选择")
    if action == "1":
        rows = _load_summaries(root)
        if not rows:
            output("当前 timeline 还没有摘要。")
            return
        for row in rows:
            stale_mark = "；stale" if row.stale else ""
            output(f"- {row.document_id}（revision={row.revision}, ownership={row.ownership}{stale_mark}）")
    elif action == "2":
        document = _choose_summary(root, input_fn, output)
        if document is None:
            return
        output(json.dumps(_summary_payload(document), ensure_ascii=False, indent=2, default=str))
    elif action == "3":
        current = _choose_summary(root, input_fn, output)
        if current is None:
            return
        expected_revision = number(
            input_fn,
            output,
            "expected revision",
            default=current.revision,
            minimum=0,
        )
        content = ask(input_fn, "新的摘要正文", required=True)
        updated = SummaryEditor(root, coordinator=coordinator).update(
            SummaryUpdate(
                current.document_id,
                expected_revision=current.revision if expected_revision is None else expected_revision,
                content=content,
            )
        )
        output(json.dumps(_summary_payload(updated), ensure_ascii=False, indent=2, default=str))
    elif action == "4":
        filename = ask(input_fn, "目标 YAML 文件名", required=True)
        target = Path(filename)
        if not target.is_absolute():
            target = root / target
        target = target.resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as exc:
            raise SummaryError("摘要路径必须位于当前 timeline summaries 目录") from exc
        content = ask(input_fn, "AI 摘要正文", required=True)
        document_id = ask(input_fn, "document_id（可留空使用文件名）") or None
        source_fingerprint = ask(input_fn, "source fingerprint（可留空）") or None
        written = SummaryWriter(root, coordinator=coordinator).write_ai(
            target,
            content,
            document_id=document_id,
            source_fingerprint=source_fingerprint,
            metadata={
                "story_id": key.story_id,
                "timeline_id": key.timeline_id,
                "document_type": "chapter-summary",
                "generated_by": "ai",
            },
        )
        output(json.dumps(_summary_payload(written), ensure_ascii=False, indent=2, default=str))


def pending_menu(coordinator: Any, input_fn: Input, output: Output) -> None:
    """Expose durable graph-promotion recovery without hiding per-graph state.

    供 plain 菜单与 console 共同复用；console 经桥接 io 注入。
    """

    rows = coordinator.list_pending()
    output(render_rows(
        rows,
        [
            ("change_id", "change_id"),
            ("状态", "status"),
            ("图数量", lambda r: len(r.get("graphs", []) or [])),
            ("错误", "error"),
        ],
    ))
    if not confirm_word(input_fn, output, "输入 RETRY 重试全部 pending；其他返回", "RETRY"):
        return
    output("正在重试 pending 图提升，请稍候…")
    results = coordinator.retry_persisted_pending()
    output(json.dumps(
        [
            {
                "status": getattr(result, "status", None),
                "change_id": getattr(result, "change_id", None),
                "yaml_committed": getattr(result, "yaml_committed", False),
                "staging_root": str(getattr(result, "staging_root", ""))
                if getattr(result, "staging_root", None) else None,
                "error": getattr(result, "error", None),
                "graphs": [
                    {
                        "key": item.key.as_dict() if hasattr(item.key, "as_dict") else str(item.key),
                        "status": item.status,
                        "target_path": str(item.target_path) if item.target_path else None,
                        "staged_path": str(item.staged_path) if item.staged_path else None,
                        "error": item.error,
                    }
                    for item in getattr(result, "graph_results", ())
                ],
            }
            for result in results
        ],
        ensure_ascii=False,
        indent=2,
        default=str,
    ))



def run_tui(
    library_root: Path,
    index_root: Path | None = None,
    *,
    input_fn: Input = input,
    output: Output = print,
    generate_fn: Callable[..., Any] | None = None,
    confirm_fn: Callable[..., Any] = None,
    resume_fn: Callable[..., Any] | None = None,
    state_inspect_fn: Callable[..., Any] | None = None,
    state_approve_fn: Callable[..., Any] | None = None,
    state_reject_fn: Callable[..., Any] | None = None,
    model_config_path: Path | None = None,
    search_fn: Callable[..., Any] | None = None,
) -> int:
    confirm_fn = confirm_fn or confirm_runtime
    if input_fn is input:
        # Interactive terminals get history/completion via prompt_toolkit;
        # injected input_fn (tests/embedded hosts) keeps the plain contract.
        input_fn, output = create_interactive_io()

    library_root = library_root.resolve()
    index_root = (index_root or library_root / "index").resolve()
    generate_fn = generate_fn or generate
    search_fn = search_fn or search_graph
    output_root = library_root.parent / "outputs"
    model_config_path = Path(model_config_path or default_config_path()).expanduser()
    try:
        stories = sorted(registered_story_ids(library_root))
        if not stories:
            output("当前知识库还没有作品，先完成一次建书向导。")
            created = create_story_wizard(library_root, input_fn, output)
            if created is None:
                return 0
            story_id, timeline_id = created
        else:
            story_id = choose(input_fn, output, "作品", stories)
            timeline_id = choose(input_fn, output, "时间线", timeline_ids(library_root, story_id))
    except (EOFError, KeyboardInterrupt):
        output("已退出。")
        return 0
    except (GenerationError, OSError, ValueError) as exc:
        output(f"ERROR {exc}")
        return 1

    coordinator = build_mutation_coordinator(library_root, index_directory=index_root)
    last_runtime = latest_runtime(output_root, story_id)
    last_outline: Path | None = None
    while True:
        runtime_note = str(last_runtime) if last_runtime else "无"
        output("\n=== Novel RAG ===")
        output(f"当前作品: {story_id}    时间线: {timeline_id}    库: {library_root}")
        output(f"最近任务: {runtime_note}")
        output(_MENU_TEXT)
        try:
            choice = ask(input_fn, "选择", required=True)
        except (EOFError, KeyboardInterrupt):
            output("已退出。")
            return 0
        if choice.strip().casefold() in _EXIT_WORDS:
            output("已退出。")
            return 0
        try:
            if choice == "1":
                outline_value = ask(
                    input_fn, "大纲文本或 UTF-8 文件路径",
                    default=str(last_outline) if last_outline else "", required=not bool(last_outline),
                )
                outline = outline_input(outline_value)
                current_request = ask(input_fn, "本轮补充要求（可留空）")
                references = reference_texts(ask(input_fn, "Reference 路径/文本，多个用分号分隔（可留空）"))
                target = number(input_fn, output, "目标字数（可留空）")
                minimum = number(input_fn, output, "最小字数（可留空）")
                maximum = number(input_fn, output, "最大字数（可留空）")
                model = model_from_local_config(input_fn, output, model_config_path)
                task_id = ask(input_fn, "任务 ID", default=suggest_task_id(output_root, story_id))
                target_runtime = output_root / ".workflow" / story_id / task_id
                if target_runtime.exists() and any(target_runtime.iterdir()):
                    output(f"任务目录已存在: {target_runtime}")
                    action = ask(input_fn, "输入 NEW 使用新任务 ID；输入 CONTINUE 转到指导续作；其他输入取消")
                    if matches_word(action, "CONTINUE"):
                        last_runtime = target_runtime
                        output("请从菜单 3 继续该任务。")
                        continue
                    if not matches_word(action, "NEW"):
                        output("已取消生成。")
                        continue
                    task_id = ask(input_fn, "新的任务 ID", required=True)
                length: dict[str, int] = {}
                if target is not None:
                    length["target"] = target
                if minimum is not None:
                    length["minimum"] = minimum
                if maximum is not None:
                    length["maximum"] = maximum
                request = {
                    "story_id": story_id, "timeline_id": timeline_id, "outline": outline,
                    "current_request": current_request, "references": references,
                    "length": length,
                }
                output("正在生成正文，请稍候…")
                if generate_fn is generate:
                    retriever = build_graph_retriever(
                        library_root,
                        GraphKey(story_id, timeline_id),
                        index_directory=index_root,
                    )
                    try:
                        result = generate_fn(
                            request,
                            model,
                            library_root=library_root,
                            index_root=index_root,
                            output_root=output_root,
                            task_id=task_id,
                            retriever=retriever,
                            progress=lambda m: output(m),
                        )
                    finally:
                        retriever.close()
                else:
                    # Tests and embedding hosts may inject their own command
                    # service; production TUI generation always gets the
                    # canonical composition retriever above.
                    result = generate_fn(
                        request,
                        model,
                        library_root=library_root,
                        index_root=index_root,
                        output_root=output_root,
                        task_id=task_id,
                        progress=lambda m: output(m),
                    )
                last_runtime = Path(result.extensions["runtime_dir"])
                output(f"生成状态: {result.status}\nruntime: {last_runtime}")
                for warning in result.warnings:
                    output(f"警告: {warning}")
                output("\n正文预览：\n" + text_preview(result.text))
                if result.status == "user_guidance_required":
                    output("该任务需要作者补充指导；可从菜单 3 继续，不会覆盖当前 runtime。")
            elif choice == "2":
                default = str(last_runtime) if last_runtime else ""
                runtime = Path(ask(input_fn, "runtime 目录", default=default, required=not bool(default)))
                show_runtime(runtime, output)
                last_runtime = runtime
            elif choice == "3":
                resume = resume_fn or continue_generation
                default = str(last_runtime) if last_runtime else ""
                runtime = Path(ask(input_fn, "需要继续的 runtime", default=default, required=not bool(default)))
                show_runtime(runtime, output)
                guidance = ask(input_fn, "请提供针对审计问题的写作指导", required=True)
                child_task_id = ask(input_fn, "新任务 ID（不会覆盖原任务）", default=runtime.name + "-guided")
                model = model_from_local_config(input_fn, output, model_config_path)
                output("正在继续生成，请稍候…")
                continued = resume(runtime, guidance, model, library_root=library_root,
                                   index_root=index_root, output_root=output_root, task_id=child_task_id)
                last_runtime = Path(continued.extensions["runtime_dir"])
                output(f"继续生成状态: {continued.status}\nruntime: {last_runtime}")
                output("\n正文预览：\n" + text_preview(continued.text))
            elif choice == "4":
                default = str(last_runtime) if last_runtime else ""
                runtime = Path(ask(input_fn, "runtime 目录", default=default, required=not bool(default)))
                review = confirm_review(runtime, output)
                volume = number(input_fn, output, "卷号", default=1)
                chapter = number(input_fn, output, "章节号", minimum=1)
                scene = number(input_fn, output, "场景号", default=1, minimum=1)
                if chapter is None:
                    output("章节号不能为空。")
                    continue
                title = pov = ""
                character_ids: list[str] | None = None
                location_ids: list[str] | None = None
                if review is not None:
                    title = ask(input_fn, "章节/场景标题（可留空使用默认）")
                    pov = ask(input_fn, "POV 角色 ID（可留空）")
                    characters = ask(input_fn, "角色 ID，多个用逗号分隔（可留空）")
                    locations = ask(input_fn, "地点 ID，多个用逗号分隔（可留空）")
                    character_ids = [item.strip() for item in characters.split(",") if item.strip()] or None
                    location_ids = [item.strip() for item in locations.split(",") if item.strip()] or None
                    output(f"正式目标: {story_id}/{timeline_id} 卷{volume} 章{chapter} 场景{scene}")
                if not confirm_word(input_fn, output, "输入 YES 确认迁移到正式 History 并清理临时正文", "YES"):
                    output("已取消回写。")
                    continue
                output("正在写入正式 History 并重建索引，请稍候…")
                result = confirm_fn(
                    runtime, library_root=library_root, index_root=index_root, confirmed=True,
                    volume=volume if volume is not None else 0, chapter=chapter,
                    scene=scene if scene is not None else 1,
                    title=title, pov=pov, character_ids=character_ids, location_ids=location_ids,
                    coordinator=coordinator,
                )
                output(f"回写状态: {result.status}\nHistory: {result.history_path}"
                       f"\n已清理临时文件: {getattr(result, 'cleaned_files', 0)}"
                       "\n角色/世界状态尚未自动晋升，请从菜单 5 审核状态提案。")
            elif choice == "5":
                inspect = state_inspect_fn or inspect_state_proposal
                approve = state_approve_fn or approve_state_proposal
                reject = state_reject_fn or reject_state_proposal
                default = str(last_runtime) if last_runtime else ""
                runtime = Path(ask(input_fn, "runtime 目录", default=default, required=not bool(default)))
                proposal = inspect(runtime, library_root=library_root)
                output(json.dumps(proposal, ensure_ascii=False, indent=2, default=str))
                decision = ask(input_fn, "输入 APPROVE 批准，REJECT 拒绝，其他输入取消")
                if matches_word(decision, "APPROVE"):
                    reason = ask(input_fn, "审核说明", default="作者已核对最终正文与状态变化")
                    scope_answer = ask(input_fn, "批准范围（回车=全部 / 输入角色ID逗号分隔=部分）")
                    approve_kwargs: dict[str, Any] = {}
                    selected_characters = [item.strip() for item in scope_answer.split(",") if item.strip()]
                    if selected_characters:
                        approve_kwargs["character_ids"] = selected_characters
                        approve_kwargs["include_world"] = not matches_word(
                            ask(input_fn, "包含世界状态？[yes]/no"), "no")
                    reviewed = approve(
                        runtime,
                        library_root=library_root,
                        index_root=index_root,
                        note=reason,
                        coordinator=coordinator,
                        **approve_kwargs,
                    )
                    output(f"状态提案处理完成: {getattr(reviewed, 'status', reviewed)}")
                elif matches_word(decision, "REJECT"):
                    reason = ask(input_fn, "拒绝原因", required=True)
                    reviewed = reject(runtime, library_root=library_root, reason=reason)
                    output(f"状态提案已拒绝: {getattr(reviewed, 'status', reviewed)}")
                else:
                    output("已取消审核。")
            elif choice == "6":
                source = _choose_upload_file("大纲 TXT/Markdown/YAML 路径（直接回车浏览目录）", input_fn, output)
                if source is None:
                    continue
                title = ask(input_fn, "大纲标题", default=source.stem)
                volume = number(input_fn, output, "卷号", default=1)
                chapter = number(input_fn, output, "章节号", minimum=1)
                version = ask(input_fn, "版本", default="1.0")
                if chapter is None:
                    output("章节号不能为空。")
                    continue
                family = None
                supersedes = None
                preview = preview_outline(
                    source, library_root=library_root, index_root=index_root,
                    story_id=story_id, timeline_id=timeline_id, title=title,
                    volume=volume if volume is not None else 0, chapter=chapter, version=version,
                )
                output("大纲上传预览：\n" + dataclass_preview(preview))
                if preview.conflicts:
                    output("检测到大纲版本冲突；旧版本不会被覆盖。")
                    version = ask(input_fn, "新版本号", required=True)
                    supersedes = ask(input_fn, "要替代的 current document_id", required=True)
                    family = ask(input_fn, "document_family", default=preview.document_family)
                    preview = preview_outline(
                        source, library_root=library_root, index_root=index_root,
                        story_id=story_id, timeline_id=timeline_id, title=title,
                        volume=volume if volume is not None else 0, chapter=chapter, version=version,
                        supersedes=supersedes, document_family=family,
                    )
                    if preview.conflicts:
                        raise RagImportError("版本预览仍有冲突: " + "；".join(preview.conflicts))
                if not confirm_word(input_fn, output, "输入 IMPORT 确认写入正式 Outline", "IMPORT"):
                    output("已取消上传。")
                    continue
                output("正在写入正式 Outline，请稍候…")
                imported = import_outline(
                    source, library_root=library_root, index_root=index_root,
                    story_id=story_id, timeline_id=timeline_id, title=title,
                    volume=volume if volume is not None else 0, chapter=chapter, version=version,
                    supersedes=supersedes, document_family=family or preview.document_family,
                    coordinator=coordinator,
                )
                last_outline = imported.path
                output(f"大纲上传状态: {imported.status}\n路径: {imported.path}")
            elif choice == "7":
                source = _choose_upload_file("符合 novel-rag 模板的 YAML 路径（直接回车浏览目录）", input_fn, output)
                if source is None:
                    continue
                preview = preview_rag_yaml(
                    source, library_root=library_root, index_root=index_root,
                    story_id=story_id, timeline_id=timeline_id,
                )
                output("上传预览：\n" + dataclass_preview(preview))
                version = supersedes = family = None
                if preview.conflicts:
                    output("检测到版本冲突；不会覆盖现有文档。")
                    version = ask(input_fn, "新版本号", required=True)
                    supersedes = ask(input_fn, "要替代的 current document_id", required=True)
                    family = ask(input_fn, "document_family", default=preview.document_family)
                    preview = preview_rag_yaml(
                        source, library_root=library_root, index_root=index_root,
                        story_id=story_id, timeline_id=timeline_id,
                        version=version, supersedes=supersedes, document_family=family,
                    )
                    if preview.conflicts:
                        raise RagImportError("版本预览仍有冲突: " + "；".join(preview.conflicts))
                if not confirm_word(input_fn, output, "输入 IMPORT 确认写入正式 RAG", "IMPORT"):
                    output("已取消上传。")
                    continue
                output("正在写入正式 RAG，请稍候…")
                imported = import_rag_yaml(
                    source, library_root=library_root, index_root=index_root,
                    story_id=story_id, timeline_id=timeline_id,
                    version=version, supersedes=supersedes, document_family=family,
                    coordinator=coordinator,
                )
                output(f"RAG 上传状态: {imported.status}\n路径: {imported.path}")
            elif choice == "8":
                documents, issues = load_valid_documents(library_root)
                if issues:
                    for issue in issues:
                        output(f"ERROR {issue.path}: {issue.message}")
                    output("存在校验问题，索引未更新。")
                    continue
                output(f"正在校验并重建索引（{len(documents)} 个文档），请稍候…")
                scope_choice = ask(input_fn, "重建范围 [全部] / 当前作品 / 仅共享")
                rebuild_kwargs: dict[str, Any] = {}
                if matches_word(scope_choice, "当前作品"):
                    rebuild_kwargs["story_id"] = story_id
                elif matches_word(scope_choice, "仅共享"):
                    rebuild_kwargs["shared_only"] = True
                results = rebuild_graph_projections(
                    index_root,
                    documents,
                    registered_story_ids(library_root),
                    library_root=library_root,
                    on_partition=lambda r: output(
                        f"[分区完成] {r.scope} 文档{r.document_count} 分块{r.chunk_count}"
                    ),
                    **rebuild_kwargs,
                )
                output(f"校验通过：{len(documents)} 个文档；已重建 {len(results)} 个索引分区。")
            elif choice == "9":
                query = ask(input_fn, "检索词", required=True)
                document_type_value = ask(input_fn, "类型过滤（可留空）")
                status_value = ask(input_fn, "状态过滤（可留空）")
                limit = number(input_fn, output, "条数上限", default=6)
                results = search_fn(
                    index_root,
                    query,
                    GraphKey(story_id, timeline_id),
                    library_root=library_root,
                    include_shared=True,
                    document_types=[document_type_value] if document_type_value else None,
                    statuses=[status_value] if status_value else None,
                    limit=limit if limit is not None else 6,
                )
                output(render_rows(
                    results,
                    [
                        ("得分", lambda r: f"{r.score:.3f}"),
                        ("类型", "document_type"),
                        ("状态", "status"),
                        ("document_id", "document_id"),
                        ("标题", "title"),
                    ],
                ))
            elif choice == "10":
                output("1. 新建作品  2. 编辑当前作品作者偏好  3. 切换作品/时间线")
                action = ask(input_fn, "选择", required=True)
                if action == "1":
                    created = create_story_wizard(library_root, input_fn, output)
                    if created:
                        story_id, timeline_id = created
                        last_runtime = latest_runtime(output_root, story_id)
                elif action == "2":
                    preferences_wizard(library_root, story_id, input_fn, output)
                elif action == "3":
                    story_id = choose(input_fn, output, "作品", sorted(registered_story_ids(library_root)))
                    timeline_id = choose(input_fn, output, "时间线", timeline_ids(library_root, story_id))
                    last_runtime = latest_runtime(output_root, story_id)
                else:
                    output("无效选项。")
            elif choice == "11":
                api_config_wizard(model_config_path, input_fn, output)
            elif choice == "12":
                output("1. 新建 Feedback  2. 查看未解决 Feedback  3. 标记已解决")
                action = ask(input_fn, "选择", required=True)
                if action == "1":
                    issue = ask(input_fn, "问题", required=True)
                    comment = ask(input_fn, "作者反馈", required=True)
                    scope = ask(input_fn, "影响范围", default="后续生成")
                    rules_text = ask(input_fn, "修正规则（多个用分号分隔）", required=True)
                    examples_text = ask(input_fn, "示例片段（可留空，多个用分号分隔）")
                    target_type = ask(input_fn, "目标类型", default="runtime" if last_runtime else "history")
                    history_id_value = ""
                    if target_type == "history":
                        history_id_value = ask(input_fn, "绑定的 History document_id（可留空）")
                    target_id = ask(input_fn, "绑定的 runtime task ID / RAG document_id",
                                     default=last_runtime.name if last_runtime and target_type == "runtime" else "",
                                     required=True)
                    output(f"将把 Feedback 写入正式 RAG: {target_type}/{target_id}；问题：{issue}")
                    if not confirm_word(input_fn, output, "输入 FEEDBACK 确认写入", "FEEDBACK"):
                        output("已取消 Feedback 写入。")
                        continue
                    created = create_feedback(library_root=library_root, index_root=index_root,
                                              story_id=story_id, timeline_id=timeline_id, issue=issue,
                                              user_comment=comment, affected_scope=scope,
                                              correction_rule=[item.strip() for item in rules_text.split(";") if item.strip()],
                                              examples=[item.strip() for item in examples_text.split(";") if item.strip()],
                                              target_type=target_type,
                                              target_id=target_id,
                                              runtime_dir=last_runtime if target_type == "runtime" else None,
                                              history_id=history_id_value or None,
                                              coordinator=coordinator)
                    output(f"Feedback 已保存: {getattr(created, 'path', created)}")
                elif action == "2":
                    rows = list_feedback(library_root=library_root, story_id=story_id,
                                         timeline_id=timeline_id, index_root=index_root, status="active")
                    output(render_rows(
                        rows,
                        [
                            ("document_id", "document_id"),
                            ("状态", "status"),
                            ("目标", lambda r: f"{r.target_type}/{getattr(r, 'target_id', '')}"),
                            ("问题", "issue"),
                        ],
                    ))
                elif action == "3":
                    rows = list_feedback(library_root=library_root, story_id=story_id,
                                         timeline_id=timeline_id, index_root=index_root, status="active")
                    if not rows:
                        output("没有未解决的 Feedback。")
                        continue
                    document_id = choose(input_fn, output, "未解决 Feedback",
                                         [str(row.document_id) for row in rows])
                    resolution = ask(input_fn, "解决说明", required=True)
                    version = ask(input_fn, "新版本", default="1.1")
                    resolved = resolve_feedback(library_root=library_root, index_root=index_root,
                                                story_id=story_id, timeline_id=timeline_id,
                                                feedback_id=document_id, resolution=resolution,
                                                version=version, supersedes=document_id,
                                                coordinator=coordinator)
                    output(f"Feedback 已解决: {getattr(resolved, 'status', resolved)}")
                else:
                    output("无效选项。")
            elif choice == "13":
                summary_menu(
                    library_root,
                    index_root,
                    GraphKey(story_id, timeline_id),
                    coordinator,
                    input_fn,
                    output,
                )
            elif choice == "14":
                pending_menu(coordinator, input_fn, output)
            else:
                output("无效选项。")
        except KeyboardInterrupt:
            output("已取消当前操作。")
            continue
        except EOFError:
            output("已退出。")
            return 0
        except PreferenceRequired as exc:
            output(f"请先运行 init-preferences 并填写: {exc.path}")
        except (GenerationError, ModelAPIError, ModelConfigError, WritebackError, RagImportError,
                GraphError, SummaryError, OSError, ValueError, KeyError,
                json.JSONDecodeError, yaml.YAMLError) as exc:
            output(f"ERROR {exc}")
