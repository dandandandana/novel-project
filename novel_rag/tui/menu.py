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
from ..index import rebuild_isolated_indexes
from ..model_api import ModelAPIError
from ..model_config import ModelConfigError, default_config_path
from ..resume import continue_generation
from ..service import load_valid_documents
from ..state import approve_state_proposal, inspect_state_proposal, reject_state_proposal
from ..writeback import WritebackError, confirm_runtime
from .helpers import (
    Input, Output, ask, number, choose, timeline_ids, reference_texts,
    outline_input, text_preview, latest_runtime, show_runtime, model_from_local_config,
    confirm_review, dataclass_preview,
)
from .wizards import api_config_wizard, preferences_wizard, create_story_wizard


def run_tui(
    library_root: Path,
    index_root: Path | None = None,
    *,
    input_fn: Input = input,
    output: Output = print,
    generate_fn: Callable[..., Any] = generate,
    confirm_fn: Callable[..., Any] = None,
    resume_fn: Callable[..., Any] | None = None,
    state_inspect_fn: Callable[..., Any] | None = None,
    state_approve_fn: Callable[..., Any] | None = None,
    state_reject_fn: Callable[..., Any] | None = None,
    model_config_path: Path | None = None,
) -> int:
    confirm_fn = confirm_fn or confirm_runtime

    library_root = library_root.resolve()
    index_root = (index_root or library_root / "index").resolve()
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

    last_runtime = latest_runtime(output_root, story_id)
    last_outline: Path | None = None
    while True:
        output("\n=== Novel RAG ===")
        output("1. 生成草稿\n2. 查看最近运行\n3. 确认并回写\n4. 上传大纲\n5. 上传 RAG YAML"
               "\n6. 校验并重建索引\n7. 退出\n8. 审核状态提案\n9. 继续需要指导的任务"
               "\n10. 作品与作者偏好\n11. Feedback 管理\n12. 本地模型 API 设置")
        try:
            choice = ask(input_fn, "选择", required=True)
            if choice == "7":
                output("已退出。")
                return 0
            if choice == "1":
                outline_value = ask(
                    input_fn, "大纲文本或 UTF-8 文件路径",
                    default=str(last_outline) if last_outline else "", required=not bool(last_outline),
                )
                outline = outline_input(outline_value)
                current_request = ask(input_fn, "本轮补充要求（可留空）")
                references = reference_texts(ask(input_fn, "Reference 路径/文本，多个用分号分隔（可留空）"))
                target = number(input_fn, output, "目标字数（可留空）")
                model = model_from_local_config(input_fn, output, model_config_path)
                task_id = ask(input_fn, "任务 ID", default="generation")
                target_runtime = output_root / ".workflow" / story_id / task_id
                if target_runtime.exists() and any(target_runtime.iterdir()):
                    output(f"任务目录已存在: {target_runtime}")
                    action = ask(input_fn, "输入 NEW 使用新任务 ID；输入 CONTINUE 转到指导续作；其他输入取消")
                    if action == "CONTINUE":
                        last_runtime = target_runtime
                        output("请从菜单 9 继续该任务。")
                        continue
                    if action != "NEW":
                        output("已取消生成。")
                        continue
                    task_id = ask(input_fn, "新的任务 ID", required=True)
                result = generate_fn(
                    {"story_id": story_id, "timeline_id": timeline_id, "outline": outline,
                     "current_request": current_request, "references": references,
                     "length": {"target": target}},
                    model, library_root=library_root, index_root=index_root,
                    output_root=output_root, task_id=task_id,
                )
                last_runtime = Path(result.extensions["runtime_dir"])
                output(f"生成状态: {result.status}\nruntime: {last_runtime}")
                for warning in result.warnings:
                    output(f"警告: {warning}")
                output("\n正文预览：\n" + text_preview(result.text))
                if result.status == "user_guidance_required":
                    output("该任务需要作者补充指导；可从菜单 9 继续，不会覆盖当前 runtime。")
            elif choice == "2":
                default = str(last_runtime) if last_runtime else ""
                runtime = Path(ask(input_fn, "runtime 目录", default=default, required=not bool(default)))
                show_runtime(runtime, output)
                last_runtime = runtime
            elif choice == "3":
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
                if ask(input_fn, "输入 YES 确认迁移到正式 History 并清理临时正文") != "YES":
                    output("已取消回写。")
                    continue
                result = confirm_fn(
                    runtime, library_root=library_root, index_root=index_root, confirmed=True,
                    volume=volume if volume is not None else 0, chapter=chapter,
                    scene=scene if scene is not None else 1,
                    title=title, pov=pov, character_ids=character_ids, location_ids=location_ids,
                )
                output(f"回写状态: {result.status}\nHistory: {result.history_path}"
                       f"\n已清理临时文件: {getattr(result, 'cleaned_files', 0)}"
                       "\n角色/世界状态尚未自动晋升，请从菜单 8 审核状态提案。")
            elif choice == "4":
                source = Path(ask(input_fn, "大纲 TXT/Markdown/YAML 文件", required=True))
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
                if ask(input_fn, "输入 IMPORT 确认写入正式 Outline") != "IMPORT":
                    output("已取消上传。")
                    continue
                imported = import_outline(
                    source, library_root=library_root, index_root=index_root,
                    story_id=story_id, timeline_id=timeline_id, title=title,
                    volume=volume if volume is not None else 0, chapter=chapter, version=version,
                    supersedes=supersedes, document_family=family or preview.document_family,
                )
                last_outline = imported.path
                output(f"大纲上传状态: {imported.status}\n路径: {imported.path}")
            elif choice == "5":
                source = Path(ask(input_fn, "符合 novel-rag 模板的 YAML 文件", required=True))
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
                if ask(input_fn, "输入 IMPORT 确认写入正式 RAG") != "IMPORT":
                    output("已取消上传。")
                    continue
                imported = import_rag_yaml(
                    source, library_root=library_root, index_root=index_root,
                    story_id=story_id, timeline_id=timeline_id,
                    version=version, supersedes=supersedes, document_family=family,
                )
                output(f"RAG 上传状态: {imported.status}\n路径: {imported.path}")
            elif choice == "6":
                documents, issues = load_valid_documents(library_root)
                if issues:
                    for issue in issues:
                        output(f"ERROR {issue.path}: {issue.message}")
                    output("存在校验问题，索引未更新。")
                    continue
                results = rebuild_isolated_indexes(index_root, documents, registered_story_ids(library_root))
                output(f"校验通过：{len(documents)} 个文档；已重建 {len(results)} 个索引分区。")
            elif choice == "8":
                inspect = state_inspect_fn or inspect_state_proposal
                approve = state_approve_fn or approve_state_proposal
                reject = state_reject_fn or reject_state_proposal
                default = str(last_runtime) if last_runtime else ""
                runtime = Path(ask(input_fn, "runtime 目录", default=default, required=not bool(default)))
                proposal = inspect(runtime, library_root=library_root)
                output(json.dumps(proposal, ensure_ascii=False, indent=2, default=str))
                decision = ask(input_fn, "输入 APPROVE 批准，REJECT 拒绝，其他输入取消")
                if decision == "APPROVE":
                    reason = ask(input_fn, "审核说明", default="作者已核对最终正文与状态变化")
                    reviewed = approve(runtime, library_root=library_root, index_root=index_root, note=reason)
                    output(f"状态提案处理完成: {getattr(reviewed, 'status', reviewed)}")
                elif decision == "REJECT":
                    reason = ask(input_fn, "拒绝原因", required=True)
                    reviewed = reject(runtime, library_root=library_root, reason=reason)
                    output(f"状态提案已拒绝: {getattr(reviewed, 'status', reviewed)}")
                else:
                    output("已取消审核。")
            elif choice == "9":
                resume = resume_fn or continue_generation
                default = str(last_runtime) if last_runtime else ""
                runtime = Path(ask(input_fn, "需要继续的 runtime", default=default, required=not bool(default)))
                show_runtime(runtime, output)
                guidance = ask(input_fn, "请提供针对审计问题的写作指导", required=True)
                child_task_id = ask(input_fn, "新任务 ID（不会覆盖原任务）", default=runtime.name + "-guided")
                model = model_from_local_config(input_fn, output, model_config_path)
                continued = resume(runtime, guidance, model, library_root=library_root,
                                   index_root=index_root, output_root=output_root, task_id=child_task_id)
                last_runtime = Path(continued.extensions["runtime_dir"])
                output(f"继续生成状态: {continued.status}\nruntime: {last_runtime}")
                output("\n正文预览：\n" + text_preview(continued.text))
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
                output("1. 新建 Feedback  2. 查看未解决 Feedback  3. 标记已解决")
                action = ask(input_fn, "选择", required=True)
                if action == "1":
                    issue = ask(input_fn, "问题", required=True)
                    comment = ask(input_fn, "作者反馈", required=True)
                    scope = ask(input_fn, "影响范围", default="后续生成")
                    rule = ask(input_fn, "修正规则", required=True)
                    target_type = ask(input_fn, "目标类型", default="runtime" if last_runtime else "history")
                    target_id = ask(input_fn, "绑定的 runtime task ID / RAG document_id",
                                     default=last_runtime.name if last_runtime and target_type == "runtime" else "",
                                     required=True)
                    output(f"将把 Feedback 写入正式 RAG: {target_type}/{target_id}；问题：{issue}")
                    if ask(input_fn, "输入 FEEDBACK 确认写入") != "FEEDBACK":
                        output("已取消 Feedback 写入。")
                        continue
                    created = create_feedback(library_root=library_root, index_root=index_root,
                                              story_id=story_id, timeline_id=timeline_id, issue=issue,
                                              user_comment=comment, affected_scope=scope,
                                              correction_rule=[rule], target_type=target_type,
                                              target_id=target_id,
                                              runtime_dir=last_runtime if target_type == "runtime" else None)
                    output(f"Feedback 已保存: {getattr(created, 'path', created)}")
                elif action == "2":
                    rows = list_feedback(library_root=library_root, story_id=story_id,
                                         timeline_id=timeline_id, index_root=index_root, status="active")
                    serializable = [{name: getattr(row, name) for name in row.__dataclass_fields__} for row in rows]
                    output(json.dumps(serializable, ensure_ascii=False, indent=2, default=str))
                elif action == "3":
                    document_id = ask(input_fn, "Feedback document_id", required=True)
                    resolution = ask(input_fn, "解决说明", required=True)
                    version = ask(input_fn, "新版本", default="1.1")
                    resolved = resolve_feedback(library_root=library_root, index_root=index_root,
                                                story_id=story_id, timeline_id=timeline_id,
                                                feedback_id=document_id, resolution=resolution,
                                                version=version, supersedes=document_id)
                    output(f"Feedback 已解决: {getattr(resolved, 'status', resolved)}")
                else:
                    output("无效选项。")
            elif choice == "12":
                api_config_wizard(model_config_path, input_fn, output)
            else:
                output("无效选项。")
        except (EOFError, KeyboardInterrupt):
            output("已退出。")
            return 0
        except PreferenceRequired as exc:
            output(f"请先运行 init-preferences 并填写: {exc.path}")
        except (GenerationError, ModelAPIError, ModelConfigError, WritebackError, RagImportError,
                OSError, ValueError, KeyError, json.JSONDecodeError, yaml.YAMLError) as exc:
            output(f"ERROR {exc}")