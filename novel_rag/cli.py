from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from .config import INDEX_ROOT, LIBRARY_ROOT
from .documents import read_yaml_mapping, registered_story_ids
from .index import rebuild_isolated_indexes, search_isolated
from .generation import GenerationError, PreferenceRequired, generate
from .model_api import ModelAPIError, OpenAICompatibleModel
from .model_config import (ModelConfigError, ModelConfigStore,
                           default_config_path)
from .resume import ResumeError, continue_generation
from .writeback import WritebackError, confirm_runtime
from .scaffold import create_story
from .service import load_valid_documents
from .state_review import (StateReviewError, approve_state_proposal,
                           inspect_state_proposal, reject_state_proposal)
from .rag_import import (RagImportError, import_outline, import_rag_yaml,
                         preview_outline, preview_rag_yaml)
from .feedback import FeedbackError, create_feedback, list_feedback, resolve_feedback


def _paths(args: argparse.Namespace) -> tuple[Path, Path]:
    library = Path(args.library).resolve()
    index = Path(args.index).resolve() if args.index else library / "index"
    return library, index


def command_validate(args: argparse.Namespace) -> int:
    documents, issues = load_valid_documents(
        Path(args.library).resolve(),
        story_id=getattr(args, "story", None),
    )
    for issue in issues:
        print(f"ERROR {issue.path}: {issue.message}")
    print(f"校验完成: {len(documents)} 个有效文档, {len(issues)} 个问题")
    return 1 if issues else 0


def command_index(args: argparse.Namespace) -> int:
    library, index_path = _paths(args)
    documents, issues = load_valid_documents(library)
    if issues:
        for issue in issues:
            print(f"ERROR {issue.path}: {issue.message}")
        print("存在校验错误，索引未更新。")
        return 1
    results = rebuild_isolated_indexes(index_path, documents, registered_story_ids(library))
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
        library / "stories" / args.story / "registry" / "timelines.yaml"
    ).get("timelines", [])
    if not any(
        isinstance(row, dict)
        and row.get("story_id") == args.story
        and row.get("timeline_id") == args.timeline
        for row in timeline_rows if isinstance(timeline_rows, list)
    ):
        print(f"ERROR 未注册 timeline_id: {args.story}/{args.timeline}")
        return 1
    results = search_isolated(
        index_path,
        args.query,
        args.story,
        args.timeline,
        document_types=args.type,
        statuses=args.status,
        limit=args.limit,
        include_shared=not args.no_shared,
    )
    output = [{
        "document_id": item.document_id, "title": item.title, "document_type": item.document_type,
        "status": item.status, "score": item.score, "source_file": item.source_file,
        "content": item.content, "metadata": item.metadata,
    } for item in results]
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


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


def _command_model(command: str, timeout: int):
    if timeout <= 0:
        raise GenerationError("model timeout 必须大于 0")
    argv = shlex.split(command, posix=False)
    def call(stage: str, payload: dict):
        try:
            completed = subprocess.run(
                argv, input=json.dumps({"stage": stage, "payload": payload}, ensure_ascii=False),
                text=True, encoding="utf-8", capture_output=True, check=False, timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise GenerationError(f"模型命令超时（{timeout} 秒）") from exc
        except OSError as exc:
            raise GenerationError(f"无法启动模型命令: {exc}") from exc
        if completed.returncode:
            raise GenerationError(completed.stderr.strip() or f"模型命令失败: {completed.returncode}")
        output = completed.stdout.strip()
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return output
    return call


def _model_from_args(args: argparse.Namespace):
    if args.model_command:
        return _command_model(args.model_command, args.model_timeout)
    store = ModelConfigStore(getattr(args, "model_config", None))
    if not args.api_model:
        return store.build_model(getattr(args, "api_profile", None))
    stored = store.get(getattr(args, "api_profile", None))
    no_auth = args.api_no_auth or bool(stored and stored.no_auth)
    api_key = None if no_auth else ((stored.api_key if stored else None) or os.environ.get(args.api_key_env))
    if not api_key and not no_auth:
        raise GenerationError("当前本地模型 profile 没有 API key；请运行 api-config set，"
                              "或对无鉴权本地服务使用 --api-no-auth")
    return OpenAICompatibleModel(
        base_url=args.api_base or (stored.base_url if stored else "https://api.openai.com/v1"),
        model=args.api_model, api_key=api_key,
        mode=args.api_mode or (stored.mode if stored else "responses"),
        timeout=args.model_timeout, retries=args.api_retries,
        max_output_tokens=args.api_max_output_tokens if args.api_max_output_tokens is not None
        else (stored.max_output_tokens if stored else None),
    )


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
    try:
        model = _model_from_args(args)
        result = generate(request, model, library_root=Path(args.library).resolve(),
                          index_root=Path(args.index).resolve() if args.index else None,
                          output_root=Path(args.output_root).resolve() if args.output_root else None,
                          task_id=args.task_id)
    except PreferenceRequired as exc:
        print(f"AUTHOR_PREFERENCES_REQUIRED {exc.path}")
        return 2
    except (GenerationError, ModelAPIError, ModelConfigError) as exc:
        print(f"ERROR {exc}")
        return 1
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


def _add_model_arguments(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group(required=False)
    source.add_argument("--model-command", help="从 stdin 接收 JSON、向 stdout 返回 JSON/正文的模型命令")
    source.add_argument("--api-model", help="OpenAI 兼容 API 的模型名称")
    parser.add_argument("--model-timeout", type=int, default=300, help="单次模型调用超时秒数")
    parser.add_argument("--api-base")
    parser.add_argument("--api-mode", choices=["responses", "chat"],
                        default=None)
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--api-no-auth", action="store_true")
    parser.add_argument("--api-retries", type=int, default=2)
    parser.add_argument("--api-max-output-tokens", type=int)
    parser.add_argument("--api-profile", help="本地 model-api.json 中的 profile；默认使用 active")


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
        )
    except (RagImportError, OSError) as exc:
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
        )
    except (RagImportError, OSError) as exc:
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
        )
    except (FeedbackError, RagImportError, OSError) as exc:
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
    except (FeedbackError, RagImportError, OSError) as exc:
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
        )
    except (FeedbackError, RagImportError, OSError) as exc:
        print(f"ERROR {exc}")
        return 1
    print(_dataclass_json(result))
    return 0


def command_api_config(args: argparse.Namespace) -> int:
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
    from .tui import run_tui

    library, index = _paths(args)
    return run_tui(library, index, model_config_path=Path(args.model_config))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="小说生成 RAG 管理工具")
    parser.add_argument("--library", default=str(LIBRARY_ROOT), help="知识库根目录")
    parser.add_argument("--index", default=None, help=f"隔离索引目录（默认 {INDEX_ROOT}）")
    parser.add_argument("--model-config", default=str(default_config_path()),
                        help="本地模型 API 配置 JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="校验注册表、元数据和引用")
    validate.add_argument("--story", help="只加载指定小说与共享系统层；注册表结构仍全量校验")
    validate.set_defaults(func=command_validate)
    index = subparsers.add_parser("index", help="校验并重建检索索引")
    index.set_defaults(func=command_index)
    search = subparsers.add_parser("search", help="在指定作品和世界线中检索")
    search.add_argument("query")
    search.add_argument("--story", required=True)
    search.add_argument("--timeline", required=True)
    search.add_argument("--type", action="append", choices=sorted(__import__('novel_rag.config', fromlist=['DOCUMENT_TYPES']).DOCUMENT_TYPES))
    search.add_argument("--status", action="append", help="默认仅 active/canon；显式指定才检索其他状态")
    search.add_argument("--limit", type=int, default=6)
    search.add_argument("--no-shared", action="store_true", help="仅检索小说隔离索引，不注入共享系统层")
    search.set_defaults(func=command_search)
    list_stories = subparsers.add_parser("list-stories", help="列出已注册的隔离小说")
    list_stories.set_defaults(func=command_list_stories)
    create = subparsers.add_parser("create-story", help="创建新的小说隔离目录并继承共享系统模块")
    create.add_argument("story_id")
    create.add_argument("--title", required=True)
    create.add_argument("--timeline", default="main")
    create.add_argument("--timeline-name", default="主世界线")
    create.add_argument("--language", default="zh-CN")
    create.add_argument("--no-shared", action="store_true", help="不在 module-map 中继承共享系统模块")
    create.set_defaults(func=command_create_story)
    generate_parser = subparsers.add_parser("generate", help="根据大纲生成小说正文（不自动回写正式库）")
    generate_parser.add_argument("--story", required=True)
    generate_parser.add_argument("--timeline", default="main")
    generate_parser.add_argument("--outline", required=True, help="大纲文本或 UTF-8 文件路径")
    generate_parser.add_argument("--request", help="本轮补充要求")
    generate_parser.add_argument("--reference", action="append", help="Reference 文本或文件路径")
    _add_model_arguments(generate_parser)
    generate_parser.add_argument("--length-target", type=int, help="作者指定目标字数")
    generate_parser.add_argument("--length-min", type=int, help="作者指定最少字数")
    generate_parser.add_argument("--length-max", type=int, help="作者指定最多字数；超出时只警告")
    generate_parser.add_argument("--expand-at", action="append", help="不足时优先扩写的位置")
    generate_parser.add_argument("--output-root", help="运行时输出根目录")
    generate_parser.add_argument("--task-id", default="generation")
    generate_parser.set_defaults(func=command_generate)
    continue_parser = subparsers.add_parser("continue", help="为需要作者指导的未确认任务创建安全续作")
    continue_parser.add_argument("--runtime", required=True)
    continue_parser.add_argument("--guidance", required=True, help="指导文本或 UTF-8 文件路径")
    continue_parser.add_argument("--task-id", help="新的 child task ID；默认自动生成")
    continue_parser.add_argument("--output-root", help="运行时输出根目录")
    _add_model_arguments(continue_parser)
    continue_parser.set_defaults(func=command_continue)
    init_preferences = subparsers.add_parser("init-preferences", help="为小说创建一次性作者偏好 TXT")
    init_preferences.add_argument("--story", required=True)
    init_preferences.add_argument("--force", action="store_true", help="覆盖已有偏好文件")
    init_preferences.set_defaults(func=command_init_preferences)
    confirm = subparsers.add_parser("confirm", help="确认运行时正文并安全回写正式 History")
    confirm.add_argument("--runtime", required=True, help="outputs/.workflow 下的生成目录")
    confirm.add_argument("--yes", action="store_true", help="明确确认该正文为正式版本")
    confirm.add_argument("--volume", type=int, required=True)
    confirm.add_argument("--chapter", type=int, required=True)
    confirm.add_argument("--scene", type=int, default=1)
    confirm.add_argument("--title")
    confirm.add_argument("--pov")
    confirm.add_argument("--character", action="append", help="正文涉及的角色 ID，可重复")
    confirm.add_argument("--location", action="append", help="正文涉及的地点 ID，可重复")
    confirm.set_defaults(func=command_confirm)
    state_review = subparsers.add_parser("state-review", help="查看确认正文产生的角色/世界状态提案")
    state_review.add_argument("--runtime", required=True)
    state_review.set_defaults(func=command_state_review)
    state_approve = subparsers.add_parser("state-approve", help="人工核对后晋升状态提案")
    state_approve.add_argument("--runtime", required=True)
    state_approve.add_argument("--yes", action="store_true")
    state_approve.add_argument("--character", action="append", help="仅批准指定角色，可重复")
    state_approve.add_argument("--no-world", action="store_true", help="本次不晋升世界状态")
    state_approve.add_argument("--note")
    state_approve.set_defaults(func=command_state_approve)
    state_reject = subparsers.add_parser("state-reject", help="拒绝状态提案且不改正式状态")
    state_reject.add_argument("--runtime", required=True)
    state_reject.add_argument("--yes", action="store_true")
    state_reject.add_argument("--reason", required=True)
    state_reject.set_defaults(func=command_state_reject)
    upload = subparsers.add_parser("import-rag", help="预览或导入带版本的 Canon/Outline/Feedback YAML")
    upload.add_argument("--source", required=True)
    upload.add_argument("--story", required=True)
    upload.add_argument("--timeline", default="main")
    upload.add_argument("--version")
    upload.add_argument("--supersedes", action="append")
    upload.add_argument("--family")
    upload.add_argument("--yes", action="store_true")
    upload.set_defaults(func=command_import_rag)
    upload_outline = subparsers.add_parser("import-outline", help="把 TXT/Markdown/YAML 大纲导入正式版本库")
    upload_outline.add_argument("--source", required=True)
    upload_outline.add_argument("--story", required=True)
    upload_outline.add_argument("--timeline", default="main")
    upload_outline.add_argument("--title", required=True)
    upload_outline.add_argument("--volume", type=int, required=True)
    upload_outline.add_argument("--chapter", type=int, required=True)
    upload_outline.add_argument("--version", default="1.0")
    upload_outline.add_argument("--supersedes", action="append")
    upload_outline.add_argument("--family")
    upload_outline.add_argument("--yes", action="store_true")
    upload_outline.set_defaults(func=command_import_outline)
    feedback_create = subparsers.add_parser("feedback-create", help="创建绑定运行时或正式文档的作者 Feedback")
    feedback_create.add_argument("--story", required=True)
    feedback_create.add_argument("--timeline", default="main")
    feedback_create.add_argument("--target-type", required=True)
    feedback_create.add_argument("--target-id", required=True)
    feedback_create.add_argument("--issue", required=True)
    feedback_create.add_argument("--comment")
    feedback_create.add_argument("--scope")
    feedback_create.add_argument("--rule", action="append")
    feedback_create.add_argument("--example", action="append")
    feedback_create.add_argument("--runtime")
    feedback_create.add_argument("--history-id")
    feedback_create.add_argument("--version", default="1.0")
    feedback_create.add_argument("--supersedes", action="append")
    feedback_create.add_argument("--family")
    feedback_create.add_argument("--yes", action="store_true")
    feedback_create.set_defaults(func=command_feedback_create)
    feedback_list = subparsers.add_parser("feedback-list", help="列出作品 Feedback")
    feedback_list.add_argument("--story", required=True)
    feedback_list.add_argument("--timeline", default="main")
    feedback_list.add_argument("--status", default="all")
    feedback_list.add_argument("--target-type")
    feedback_list.add_argument("--target-id")
    feedback_list.set_defaults(func=command_feedback_list)
    feedback_resolve = subparsers.add_parser("feedback-resolve", help="创建 Feedback 的已解决新版本")
    feedback_resolve.add_argument("--story", required=True)
    feedback_resolve.add_argument("--timeline", default="main")
    feedback_resolve.add_argument("--feedback-id", required=True)
    feedback_resolve.add_argument("--resolution", required=True)
    feedback_resolve.add_argument("--version", required=True)
    feedback_resolve.add_argument("--yes", action="store_true")
    feedback_resolve.set_defaults(func=command_feedback_resolve)
    api_config = subparsers.add_parser("api-config", help="管理本地模型 API 配置（不依赖环境变量）")
    config_actions = api_config.add_subparsers(dest="config_action", required=True)
    config_path = config_actions.add_parser("path", help="显示本地配置文件位置")
    config_path.set_defaults(func=command_api_config)
    config_list = config_actions.add_parser("list", help="列出 profile 和当前选择")
    config_list.set_defaults(func=command_api_config)
    config_show = config_actions.add_parser("show", help="显示脱敏后的 profile")
    config_show.add_argument("--name")
    config_show.set_defaults(func=command_api_config)
    config_set = config_actions.add_parser("set", help="新增或修改 profile")
    config_set.add_argument("--name", required=True)
    config_set.add_argument("--base-url")
    config_set.add_argument("--model")
    config_set.add_argument("--mode", choices=["responses", "chat"])
    config_set.add_argument("--timeout", type=float)
    config_set.add_argument("--retries", type=int)
    config_set.add_argument("--max-output-tokens", type=int)
    config_set.add_argument("--no-auth", action=argparse.BooleanOptionalAction, default=None)
    key_source = config_set.add_mutually_exclusive_group()
    key_source.add_argument("--api-key-file", help="从本地文件读取 key，避免进入 shell history")
    key_source.add_argument("--api-key-stdin", action="store_true", help="从标准输入读取 key")
    config_set.add_argument("--active", action="store_true", help="保存后设为当前 profile")
    config_set.set_defaults(func=command_api_config)
    config_use = config_actions.add_parser("use", help="切换当前 profile")
    config_use.add_argument("name")
    config_use.set_defaults(func=command_api_config)
    config_delete = config_actions.add_parser("delete", help="删除 profile")
    config_delete.add_argument("name")
    config_delete.add_argument("--yes", action="store_true")
    config_delete.set_defaults(func=command_api_config)
    tui = subparsers.add_parser("tui", help="启动简单的交互式小说生成界面")
    tui.set_defaults(func=command_tui)
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
