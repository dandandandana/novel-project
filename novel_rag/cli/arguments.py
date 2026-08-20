"""Argument parser construction for the novel-rag CLI."""

from __future__ import annotations

import argparse

from ..config import INDEX_ROOT, LIBRARY_ROOT
from ..model_config import default_config_path
from .helpers import _add_model_arguments


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="小说生成 RAG 管理工具")
    parser.add_argument("--library", default=str(LIBRARY_ROOT), help="知识库根目录")
    parser.add_argument("--index", default=None, help=f"隔离索引目录（默认 {INDEX_ROOT}）")
    parser.add_argument("--model-config", default=str(default_config_path()),
                        help="本地模型 API 配置 JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    from .commands import (
        command_validate, command_index, command_search, command_list_stories,
        command_create_story, command_generate, command_continue,
        command_init_preferences, command_confirm, command_state_review,
        command_state_approve, command_state_reject, command_import_rag,
        command_import_outline, command_feedback_create, command_feedback_list,
        command_feedback_resolve, command_api_config, command_tui, command_doctor,
        command_summary, command_pending,
    )

    validate = subparsers.add_parser("validate", help="校验注册表、元数据和引用")
    validate.add_argument("--story", help="只加载指定小说与共享系统层；注册表结构仍全量校验")
    validate.set_defaults(func=command_validate)

    doctor = subparsers.add_parser(
        "doctor", help="检查安装所需的 Python/SQLite/FTS5/trigram 能力"
    )
    doctor.set_defaults(func=command_doctor)

    summary = subparsers.add_parser(
        "summary", help="查看、编辑或写入 timeline 摘要 YAML"
    )
    summary.add_argument("--story", required=True)
    summary.add_argument("--timeline", default="main")
    summary_actions = summary.add_subparsers(dest="summary_action", required=True)
    summary_list = summary_actions.add_parser("list", help="列出当前 timeline 摘要")
    summary_list.set_defaults(func=command_summary)
    summary_show = summary_actions.add_parser("show", help="显示一个摘要")
    summary_show.add_argument("--document-id", required=True)
    summary_show.set_defaults(func=command_summary)

    def _summary_content_arguments(parser: argparse.ArgumentParser) -> None:
        content = parser.add_mutually_exclusive_group(required=True)
        content.add_argument("--content", help="摘要正文")
        content.add_argument("--content-file", help="UTF-8 摘要正文文件")

    summary_edit = summary_actions.add_parser("edit", help="以 expected revision 编辑摘要")
    summary_edit.add_argument("--document-id", required=True)
    summary_edit.add_argument("--expected-revision", type=int, required=True)
    _summary_content_arguments(summary_edit)
    summary_edit.set_defaults(func=command_summary)

    summary_ai = summary_actions.add_parser("write-ai", help="写入无需批准的 AI 摘要")
    summary_ai.add_argument("--path", required=True, help="目标 summaries 下的 YAML 文件名或路径")
    summary_ai.add_argument("--document-id")
    summary_ai.add_argument("--source-fingerprint")
    summary_ai.add_argument("--document-type", default="chapter-summary")
    summary_ai.add_argument("--generated-by", default="ai")
    _summary_content_arguments(summary_ai)
    summary_ai.set_defaults(func=command_summary)

    pending = subparsers.add_parser("pending", help="查看或重试待提升图")
    pending_actions = pending.add_subparsers(dest="pending_action", required=True)
    pending_list = pending_actions.add_parser("list", help="列出库内 pending manifest")
    pending_list.set_defaults(func=command_pending)
    pending_retry = pending_actions.add_parser("retry", help="重试所有可恢复的 pending 图提升")
    pending_retry.set_defaults(func=command_pending)

    index = subparsers.add_parser("index", help="校验并重建检索索引")
    index.add_argument("--story", help="只重建指定 story 的图")
    index.add_argument("--timeline", help="与 --story 一起只重建指定 timeline 图")
    index.add_argument("--shared", action="store_true", help="只重建 shared.db")
    index.set_defaults(func=command_index)

    search = subparsers.add_parser("search", help="在指定作品和世界线中检索")
    search.add_argument("query")
    search.add_argument("--story", required=True)
    search.add_argument("--timeline", required=True)
    search.add_argument("--type", action="append", choices=sorted(__import__('novel_rag.config', fromlist=['DOCUMENT_TYPES']).DOCUMENT_TYPES))
    search.add_argument("--status", action="append", help="默认仅 active/canon；显式指定才检索其他状态")
    search.add_argument("--limit", type=int, default=6)
    search.add_argument("--no-shared", action="store_true", help="仅检索小说隔离索引，不注入共享系统层")
    search.add_argument("--legacy", action="store_true", help="显式读取迁移期旧 stories/<story>.db 索引")
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
    generate_parser.add_argument("--legacy", action="store_true", help="显式使用迁移期 YAML 兼容检索")
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
