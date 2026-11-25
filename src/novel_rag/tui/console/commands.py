"""动词解析与业务接线：命令语义映射既有 CLI/菜单词汇，业务 API 单一归属不复制。"""

from __future__ import annotations

import json
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ...documents import registered_story_ids
from ...feedback import create_feedback, list_feedback, resolve_feedback
from ...generation import GenerationError, generate
from ...composition import (
    build_graph_retriever,
    build_mutation_coordinator,
    rebuild_graph_projections,
    search_graph,
)
from ...graph import GraphError
from ...identity import GraphKey
from ...importers import (
    RagImportError,
    import_outline,
    import_rag_yaml,
    preview_outline,
    preview_rag_yaml,
)
from ...model_api import ModelAPIError
from ...model_config import ModelConfigError
from ...resume import continue_generation
from ...service import load_valid_documents
from ...state import approve_state_proposal, inspect_state_proposal, reject_state_proposal
from ...writeback import WritebackError, confirm_runtime
from ..helpers import (
    choose,
    confirm_review,
    confirm_word,
    latest_runtime,
    matches_word,
    model_from_local_config,
    outline_input,
    pick_file_from_directory,
    reference_texts,
    show_runtime,
    suggest_task_id,
    text_preview,
    timeline_ids,
)
from ..wizards import api_config_wizard, create_story_wizard, preferences_wizard
from .dialogs import MENU_NUMBERS, FieldSpec, make_form_float

_ALIASES = {"g": "gen", "quit": "q", "exit": "q", "cls": "clear", "?": "help"}


def parse_command(raw: str) -> tuple[str | None, list[str]]:
    text = raw.strip()
    if text.startswith(":"):
        text = text[1:].strip()
    if not text:
        return None, []
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()
    head = tokens[0]
    rest = tokens[1:]
    if head.isdigit() and head in MENU_NUMBERS:
        head = MENU_NUMBERS[head]
    verb = _ALIASES.get(head.lower(), head.lower())
    return verb, rest


@dataclass
class ConsoleContext:
    library_root: Path
    index_root: Path
    output_root: Path
    model_config_path: Path
    adapter: Any
    story_id: str = ""
    timeline_id: str = ""
    last_runtime: Path | None = None
    last_outline: Path | None = None
    open_overlay: Callable[[Any], None] = lambda _f: None
    close_overlay: Callable[[], None] = lambda: None
    quit_app: Callable[[], None] = lambda: None
    _coordinator: Any = field(default=None, repr=False)

    def bind_ui(self, *, open_overlay: Callable[[Any], None],
                close_overlay: Callable[[], None],
                quit_app: Callable[[], None]) -> None:
        self.open_overlay = open_overlay
        self.close_overlay = close_overlay
        self.quit_app = quit_app

    @property
    def out(self) -> Callable[[str], None]:
        return self.adapter.bridge_output

    @property
    def bridge_in(self) -> Callable[[str], str]:
        return self.adapter.bridge_input

    def coordinator(self) -> Any:
        if self._coordinator is None:
            self._coordinator = build_mutation_coordinator(
                self.library_root, index_directory=self.index_root)
        return self._coordinator

    def graph_key(self) -> GraphKey:
        return GraphKey(self.story_id or "", self.timeline_id or "")

    def run(self, echo: str, work: Callable[[Any], Any], *, kind: str,
            label: str) -> None:
        self.adapter.run_flow(echo, work, kind=kind, label=label)

    def emit(self, job: Any, text: str) -> None:
        self.adapter.runner.emit(job, text)


VERBS: dict[str, Callable[[ConsoleContext, list[str]], None]] = {}


def _verb(name: str):
    def register(fn: Callable[[ConsoleContext, list[str]], None]) -> Callable[
            [ConsoleContext, list[str]], None]:
        VERBS[name] = fn
        return fn
    return register


@_verb("info")
def cmd_info(ctx: ConsoleContext, _args: list[str]) -> None:
    from .config import DEFAULT_CONFIG_PATH

    def work(_job: Any) -> None:
        profile = ctx.adapter.workspace.model_profile
        ctx.out("\n".join([
            f"库目录: {ctx.library_root}",
            f"索引目录: {ctx.index_root}",
            f"输出根: {ctx.output_root}",
            f"作品/时间线: {ctx.story_id or '未选择'} / {ctx.timeline_id or '-'}",
            f"模型 profile: {profile or '未设置'}",
            f"模型配置: {ctx.model_config_path}",
            f"UI 配置: {DEFAULT_CONFIG_PATH}",
        ]))

    ctx.run("info", work, kind="meta", label="环境信息")


@_verb("search")
def cmd_search(ctx: ConsoleContext, args: list[str]) -> None:
    limit, doc_type, status, query = 6, "", "", []
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--limit" and index + 1 < len(args):
            try:
                limit = max(1, int(args[index + 1]))
            except ValueError:
                pass
            index += 2
        elif token == "--type" and index + 1 < len(args):
            doc_type = args[index + 1]
            index += 2
        elif token == "--status" and index + 1 < len(args):
            status = args[index + 1]
            index += 2
        else:
            query = [*query, token]
            index += 1
    query_text = " ".join(query)
    if not query_text:
        ctx.out("   · 用法: search 关键词 [--limit N] [--type T] [--status S]")
        return

    def work(_job: Any) -> None:
        results = search_graph(
            ctx.index_root, query_text, ctx.graph_key(),
            library_root=ctx.library_root, include_shared=True,
            document_types=[doc_type] if doc_type else None,
            statuses=[status] if status else None, limit=limit,
        )
        table = render_rows_safe(results)
        for line in table.splitlines():
            ctx.out(line)

    ctx.run(f"search {query_text}", work, kind="search", label="检索")


@_verb("rebuild")
def cmd_rebuild(ctx: ConsoleContext, args: list[str]) -> None:
    scope_story = "--story" in args
    scope_shared = "--shared" in args

    def work(job: Any) -> None:
        documents, issues = load_valid_documents(ctx.library_root)
        if issues:
            for issue in issues:
                ctx.out(f"ERROR {issue.path}: {issue.message}")
            ctx.out("存在校验问题，索引未更新。")
            return
        kwargs: dict[str, Any] = {}
        if scope_story:
            kwargs["story_id"] = ctx.story_id
        elif scope_shared:
            kwargs["shared_only"] = True
        ctx.out(f"正在校验并重建索引（{len(documents)} 个文档）…")

        def on_partition(result: Any) -> None:
            ctx.adapter.runner.progress(
                job, detail=f"[分区完成] {result.scope} "
                            f"文档{result.document_count} 分块{result.chunk_count}")

        results = rebuild_graph_projections(
            ctx.index_root, documents, registered_story_ids(ctx.library_root),
            library_root=ctx.library_root, on_partition=on_partition, **kwargs)
        ctx.out(f"校验通过：{len(documents)} 个文档；已重建 {len(results)} 个索引分区。")

    echo = "rebuild" + (" --story" if scope_story else "") + \
        (" --shared" if scope_shared else "")
    ctx.run(echo, work, kind="rebuild", label="重建索引")


def _short(text: str, limit: int = 48) -> str:
    cleaned = " ".join(str(text).split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


@_verb("gen")
def cmd_gen(ctx: ConsoleContext, args: list[str]) -> None:
    if not ctx.story_id:
        ctx.out("   · 尚未选择作品：先运行 stories 切换或创建。")
        return
    fields = [
        FieldSpec(name="outline", label="大纲文本或 UTF-8 文件路径",
                  default=str(ctx.last_outline) if ctx.last_outline else "",
                  required=True),
        FieldSpec(name="request", label="本轮补充要求（可留空）"),
        FieldSpec(name="references", label="Reference 路径/文本，分号分隔（可留空）"),
        FieldSpec(name="target", label="目标字数（可留空）"),
        FieldSpec(name="minimum", label="最小字数（可留空）"),
        FieldSpec(name="maximum", label="最大字数（可留空）"),
        FieldSpec(name="task_id", label="任务 ID",
                  default=suggest_task_id(ctx.output_root, ctx.story_id)),
    ]

    def submit(values: dict[str, str]) -> None:
        ctx.close_overlay()
        _start_gen(ctx, values)

    ctx.open_overlay(make_form_float("生成草稿", fields, submit, ctx.close_overlay))


def _start_gen(ctx: ConsoleContext, values: dict[str, str]) -> None:
    outline_raw = values["outline"]
    task_id = values.get("task_id") or suggest_task_id(ctx.output_root, ctx.story_id)
    length: dict[str, int] = {}
    for key in ("target", "minimum", "maximum"):
        raw = (values.get(key) or "").strip()
        if raw.isdigit():
            length[key] = int(raw)

    def work(job: Any) -> None:
        model = model_from_local_config(ctx.bridge_in, ctx.out, ctx.model_config_path)
        target_dir = ctx.output_root / ".workflow" / ctx.story_id / task_id
        actual_task = task_id
        if target_dir.exists() and any(target_dir.iterdir()):
            action = ctx.bridge_in(
                "任务目录已存在；输入 NEW 使用新任务 ID，其他输入取消").strip()
            if not matches_word(action, "NEW"):
                ctx.out("已取消生成。")
                return
            actual_task = _required_line(ctx, "新的任务 ID")
        request = {
            "story_id": ctx.story_id,
            "timeline_id": ctx.timeline_id,
            "outline": outline_input(outline_raw),
            "current_request": values.get("request") or "",
            "references": reference_texts(values.get("references") or ""),
            "length": length,
        }
        retriever = build_graph_retriever(
            ctx.library_root, ctx.graph_key(), index_directory=ctx.index_root)
        try:
            result = generate(
                request, model,
                library_root=ctx.library_root, index_root=ctx.index_root,
                output_root=ctx.output_root, task_id=actual_task,
                progress=lambda message: ctx.adapter.runner.progress(
                    job, detail=str(message)[:60]),
            )
        finally:
            retriever.close()
        runtime = Path(result.extensions["runtime_dir"])
        ctx.last_runtime = runtime
        ctx.out(f"生成状态: {result.status}")
        for warning in result.warnings:
            ctx.out(f"⚠ {warning}")
        ctx.out("")
        ctx.out(text_preview(result.text, ctx.adapter.config.preview_chars))
        if result.status == "user_guidance_required":
            ctx.out("该任务需要补充指导；可用 cont 继续（不会覆盖当前 runtime）。")

    ctx.run(f"gen {_short(outline_raw)}", work, kind="generate",
            label=f"生成草稿 {task_id}")


@_verb("cont")
def cmd_cont(ctx: ConsoleContext, args: list[str]) -> None:
    default_runtime = latest_runtime(ctx.output_root, ctx.story_id) \
        if ctx.story_id else None
    default_runtime = ctx.last_runtime or default_runtime
    fields = [
        FieldSpec(name="runtime", label="需要继续的 runtime 目录",
                  default=str(default_runtime) if default_runtime else "",
                  required=True),
        FieldSpec(name="guidance", label="针对审计问题的写作指导 *", multiline=True),
        FieldSpec(name="task_id", label="新任务 ID（默认 <原ID>-guided）"),
    ]

    def submit(values: dict[str, str]) -> None:
        ctx.close_overlay()
        guidance = values.get("guidance") or ""
        if not guidance.strip():
            ctx.out("   · 写作指导不能为空。")
            return
        _start_cont(ctx, values)

    ctx.open_overlay(make_form_float("继续指导任务", fields, submit, ctx.close_overlay))


def _start_cont(ctx: ConsoleContext, values: dict[str, str]) -> None:
    runtime = Path(values["runtime"])
    guidance = values["guidance"]
    child_task = values.get("task_id") or f"{runtime.name}-guided"

    def work(_job: Any) -> None:
        show_runtime(runtime, ctx.out)
        model = model_from_local_config(ctx.bridge_in, ctx.out, ctx.model_config_path)
        continued = continue_generation(
            runtime, guidance, model,
            library_root=ctx.library_root, index_root=ctx.index_root,
            output_root=ctx.output_root, task_id=child_task,
        )
        ctx.last_runtime = Path(continued.extensions["runtime_dir"])
        ctx.out(f"继续生成状态: {continued.status}")
        for warning in getattr(continued, "warnings", []) or []:
            ctx.out(f"⚠ {warning}")
        ctx.out("")
        ctx.out(text_preview(continued.text, ctx.adapter.config.preview_chars))

    ctx.run(f"cont {_short(runtime.name)}", work, kind="continue",
            label=f"续写 {child_task}")


@_verb("confirm")
def cmd_confirm(ctx: ConsoleContext, args: list[str]) -> None:
    default_runtime = ctx.last_runtime or (
        latest_runtime(ctx.output_root, ctx.story_id) if ctx.story_id else None)
    fields = [
        FieldSpec(name="runtime", label="runtime 目录",
                  default=str(default_runtime) if default_runtime else "",
                  required=True),
        FieldSpec(name="volume", label="卷号", default="1"),
        FieldSpec(name="chapter", label="章节号 *"),
        FieldSpec(name="scene", label="场景号", default="1"),
        FieldSpec(name="title", label="标题（可留空使用默认）"),
        FieldSpec(name="pov", label="POV 角色 ID（可留空）"),
        FieldSpec(name="characters", label="角色 ID，逗号分隔（可留空）"),
        FieldSpec(name="locations", label="地点 ID，逗号分隔（可留空）"),
    ]

    def submit(values: dict[str, str]) -> None:
        ctx.close_overlay()
        chapter_raw = (values.get("chapter") or "").strip()
        if not chapter_raw.isdigit():
            ctx.out("   · 章节号必须是正整数。")
            return
        _start_confirm(ctx, values)

    ctx.open_overlay(make_form_float("确认并回写", fields, submit, ctx.close_overlay))


def _start_confirm(ctx: ConsoleContext, values: dict[str, str]) -> None:
    runtime = Path(values["runtime"])
    volume = int(values.get("volume") or 1)
    chapter = int(values["chapter"])
    scene = int(values.get("scene") or 1)
    title = values.get("title") or ""
    pov = values.get("pov") or ""

    def split_ids(raw: str) -> list[str] | None:
        items = [item.strip() for item in (raw or "").split(",") if item.strip()]
        return items or None

    character_ids = split_ids(values.get("characters") or "")
    location_ids = split_ids(values.get("locations") or "")

    def work(_job: Any) -> None:
        review = confirm_review(runtime, ctx.out)
        if review is None and not title:
            ctx.out("runtime 资料不完整，请填写标题后再回写。")
            return
        ctx.out(f"正式目标: {ctx.story_id}/{ctx.timeline_id} "
                f"卷{volume} 章{chapter} 场景{scene}")
        if not confirm_word(ctx.bridge_in, ctx.out,
                            "确认迁移到正式 History 并清理临时正文", "YES"):
            ctx.out("已取消回写。")
            return
        result = confirm_runtime(
            runtime, library_root=ctx.library_root, index_root=ctx.index_root,
            confirmed=True, volume=volume, chapter=chapter, scene=scene,
            title=title, pov=pov, character_ids=character_ids,
            location_ids=location_ids, coordinator=ctx.coordinator(),
        )
        ctx.out(f"回写状态: {result.status}")
        ctx.out(f"History: {result.history_path}")
        ctx.out(f"已清理临时文件: {getattr(result, 'cleaned_files', 0)}")
        ctx.out("角色/世界状态尚未晋升：运行 review 审核状态提案。")

    ctx.run(f"confirm {_short(runtime.name)}", work, kind="confirm",
            label=f"回写 卷{volume}章{chapter}")


@_verb("review")
def cmd_review(ctx: ConsoleContext, args: list[str]) -> None:
    default_runtime = ctx.last_runtime or (
        latest_runtime(ctx.output_root, ctx.story_id) if ctx.story_id else None)

    def work(_job: Any) -> None:
        runtime = Path(_ask_runtime(ctx, default_runtime))
        proposal = inspect_state_proposal(runtime, library_root=ctx.library_root)
        ctx.out(json.dumps(proposal, ensure_ascii=False, indent=2, default=str))
        decision = ctx.bridge_in("输入 APPROVE 批准，REJECT 拒绝，其他输入取消").strip()
        if matches_word(decision, "APPROVE"):
            reason = (ctx.bridge_in("审核说明[作者已核对最终正文与状态变化]: ").strip()
                      or "作者已核对最终正文与状态变化")
            approve_kwargs: dict[str, Any] = {}
            scope = ctx.bridge_in("批准范围（回车=全部 / 角色 ID 逗号分隔=部分）").strip()
            selected = [item.strip() for item in scope.split(",") if item.strip()]
            if selected:
                approve_kwargs["character_ids"] = selected
                include_world = ctx.bridge_in("包含世界状态？[yes]/no").strip()
                approve_kwargs["include_world"] = not matches_word(include_world, "no")
            reviewed = approve_state_proposal(
                runtime, library_root=ctx.library_root,
                index_root=ctx.index_root, note=reason,
                coordinator=ctx.coordinator(), **approve_kwargs)
            ctx.out(f"状态提案处理完成: {getattr(reviewed, 'status', reviewed)}")
        elif matches_word(decision, "REJECT"):
            reason = ""
            while not reason:
                reason = ctx.bridge_in("拒绝原因").strip()
                if not reason:
                    ctx.out("拒绝原因不能为空。")
            reviewed = reject_state_proposal(runtime, library_root=ctx.library_root,
                                             reason=reason)
            ctx.out(f"状态提案已拒绝: {getattr(reviewed, 'status', reviewed)}")
        else:
            ctx.out("已取消审核。")

    ctx.run("review", work, kind="review", label="状态提案审核")


def _ask_runtime(ctx: ConsoleContext, default: Path | None) -> str:
    while True:
        hint = f"[{default}]" if default else ""
        value = ctx.bridge_in(f"runtime 目录{hint}: ").strip()
        target = value or (str(default) if default else "")
        if target:
            return target
        ctx.out("runtime 目录不能为空。")


@_verb("upload")
def cmd_upload(ctx: ConsoleContext, args: list[str]) -> None:
    _run_upload(ctx, rag=False)


@_verb("rag")
def cmd_rag(ctx: ConsoleContext, args: list[str]) -> None:
    _run_upload(ctx, rag=True)


def _run_upload(ctx: ConsoleContext, *, rag: bool) -> None:
    if not ctx.story_id:
        ctx.out("   · 尚未选择作品：先运行 stories 切换或创建。")
        return

    def work(_job: Any) -> None:
        source = _pick_source(ctx, rag)
        if source is None:
            ctx.out("已取消上传。")
            return
        if not rag:
            title = _ask_line(ctx, "大纲标题", str(source.stem))
            volume = _ask_int(ctx, "卷号", 1)
            chapter = _ask_positive_int(ctx, "章节号")
            version = _ask_line(ctx, "版本", "1.0")
            preview = preview_outline(
                source, library_root=ctx.library_root,
                index_root=ctx.index_root, story_id=ctx.story_id,
                timeline_id=ctx.timeline_id, title=title, volume=volume,
                chapter=chapter, version=version)
            supersedes = family = None
            while preview.conflicts:
                ctx.out("检测到大纲版本冲突；旧版本不会被覆盖。")
                version = _required_line(ctx, "新版本号")
                supersedes = _required_line(ctx, "要替代的 current document_id")
                family = _ask_line(ctx, "document_family", preview.document_family)
                preview = preview_outline(
                    source, library_root=ctx.library_root,
                    index_root=ctx.index_root, story_id=ctx.story_id,
                    timeline_id=ctx.timeline_id, title=title, volume=volume,
                    chapter=chapter, version=version, supersedes=supersedes,
                    document_family=family)
                if not preview.conflicts:
                    break
                ctx.out("版本预览仍有冲突：" + "；".join(preview.conflicts))
                if not matches_word(
                        ctx.bridge_in("输入 RETRY 重试填写，其他取消"), "RETRY"):
                    ctx.out("已取消上传。")
                    return
            ctx.out(_preview_text(preview))
            if not confirm_word(ctx.bridge_in, ctx.out,
                                "确认写入正式 Outline", "IMPORT"):
                ctx.out("已取消上传。")
                return
            imported = import_outline(
                source, library_root=ctx.library_root,
                index_root=ctx.index_root, story_id=ctx.story_id,
                timeline_id=ctx.timeline_id, title=title, volume=volume,
                chapter=chapter, version=version, supersedes=supersedes,
                document_family=family or preview.document_family,
                coordinator=ctx.coordinator())
            ctx.last_outline = Path(imported.path)
            ctx.out(f"大纲上传状态: {imported.status}")
            ctx.out(f"路径: {imported.path}")
            return
        preview = preview_rag_yaml(
            source, library_root=ctx.library_root, index_root=ctx.index_root,
            story_id=ctx.story_id, timeline_id=ctx.timeline_id)
        version = supersedes = family = None
        while preview.conflicts:
            ctx.out("检测到版本冲突；不会覆盖现有文档。")
            version = _required_line(ctx, "新版本号")
            supersedes = _required_line(ctx, "要替代的 current document_id")
            family = _ask_line(ctx, "document_family", preview.document_family)
            preview = preview_rag_yaml(
                source, library_root=ctx.library_root,
                index_root=ctx.index_root, story_id=ctx.story_id,
                timeline_id=ctx.timeline_id, version=version,
                supersedes=supersedes, document_family=family)
            if not preview.conflicts:
                break
            ctx.out("版本预览仍有冲突：" + "；".join(preview.conflicts))
            if not matches_word(ctx.bridge_in("输入 RETRY 重试填写，其他取消"),
                                "RETRY"):
                ctx.out("已取消上传。")
                return
        ctx.out(_preview_text(preview))
        if not confirm_word(ctx.bridge_in, ctx.out, "确认写入正式 RAG", "IMPORT"):
            ctx.out("已取消上传。")
            return
        imported = import_rag_yaml(
            source, library_root=ctx.library_root, index_root=ctx.index_root,
            story_id=ctx.story_id, timeline_id=ctx.timeline_id,
            version=version, supersedes=supersedes, document_family=family,
            coordinator=ctx.coordinator())
        ctx.out(f"RAG 上传状态: {imported.status}")
        ctx.out(f"路径: {imported.path}")

    label = "上传 RAG YAML" if rag else "上传大纲"
    ctx.run("rag" if rag else "upload", work,
            kind="import", label=label)


def _pick_source(ctx: ConsoleContext, rag: bool) -> Path | None:
    hint = "RAG YAML 路径（回车进入目录浏览）" if rag \
        else "大纲 TXT/Markdown/YAML 路径（回车进入目录浏览）"
    value = ctx.bridge_in(hint).strip()
    if not value:
        return pick_file_from_directory(ctx.bridge_in, ctx.out, start=Path.cwd())
    candidate = Path(value)
    if candidate.is_dir():
        return pick_file_from_directory(ctx.bridge_in, ctx.out, start=candidate)
    if not candidate.exists():
        ctx.out(f"   · 路径不存在：{value}")
        return None
    return candidate


def _ask_line(ctx: ConsoleContext, prompt: str, default: str) -> str:
    value = ctx.bridge_in(f"{prompt}[{default}]: ").strip()
    return value or default


def _required_line(ctx: ConsoleContext, prompt: str) -> str:
    value = ""
    while not value:
        value = ctx.bridge_in(f"{prompt}*: ").strip()
        if not value:
            ctx.out("该项不能为空。")
    return value


def _ask_int(ctx: ConsoleContext, prompt: str, default: int) -> int:
    while True:
        raw = _ask_line(ctx, prompt, str(default))
        try:
            return int(raw)
        except ValueError:
            ctx.out("请输入整数。")


def _ask_positive_int(ctx: ConsoleContext, prompt: str) -> int:
    while True:
        value = _ask_int(ctx, prompt, 1)
        if value >= 1:
            return value
        ctx.out("请输入不小于 1 的整数。")


def _preview_text(preview: Any) -> str:
    from ..helpers import dataclass_preview
    return "上传预览：\n" + dataclass_preview(preview)


@_verb("pending")
def cmd_pending(ctx: ConsoleContext, args: list[str]) -> None:
    from ..menu import pending_menu

    def work(_job: Any) -> None:
        pending_menu(ctx.coordinator(), ctx.bridge_in, ctx.out)

    ctx.run("pending", work, kind="pending_retry", label="Pending 图恢复")


@_verb("summary")
def cmd_summary(ctx: ConsoleContext, args: list[str]) -> None:
    from ..menu import summary_menu

    def work(_job: Any) -> None:
        summary_menu(ctx.library_root, ctx.index_root, ctx.graph_key(),
                     ctx.coordinator(), ctx.bridge_in, ctx.out)

    ctx.run("summary", work, kind="meta", label="摘要管理")


@_verb("feedback")
def cmd_feedback(ctx: ConsoleContext, args: list[str]) -> None:
    def work(_job: Any) -> None:
        action = ctx.bridge_in("1 新建 Feedback / 2 查看未解决 / 3 标记已解决").strip()
        if action == "1":
            _feedback_create(ctx)
        elif action == "2":
            rows = list_feedback(library_root=ctx.library_root,
                                 story_id=ctx.story_id,
                                 timeline_id=ctx.timeline_id,
                                 index_root=ctx.index_root, status="active")
            from ..helpers import render_rows
            ctx.out(render_rows(rows, [
                ("document_id", "document_id"),
                ("状态", "status"),
                ("目标", lambda r: f"{r.target_type}/{getattr(r, 'target_id', '')}"),
                ("问题", "issue"),
            ]))
        elif action == "3":
            _feedback_resolve(ctx)
        else:
            ctx.out("无效选项。")

    ctx.run("feedback", work, kind="meta", label="Feedback 管理")


def _feedback_create(ctx: ConsoleContext) -> None:
    issue = _required_line(ctx, "问题")
    comment = _required_line(ctx, "作者反馈")
    scope = _ask_line(ctx, "影响范围", "后续生成")
    rules_text = _required_line(ctx, "修正规则（分号分隔）")
    examples_text = _ask_line(ctx, "示例片段（可留空，分号分隔）", "")
    target_type = _ask_line(ctx, "目标类型", "runtime")
    target_id = _required_line(ctx, "绑定的 runtime task ID / RAG document_id")
    ctx.out(f"将把 Feedback 写入正式 RAG: {target_type}/{target_id}")
    if not confirm_word(ctx.bridge_in, ctx.out, "确认写入", "FEEDBACK"):
        ctx.out("已取消 Feedback 写入。")
        return
    created = create_feedback(
        library_root=ctx.library_root, index_root=ctx.index_root,
        story_id=ctx.story_id, timeline_id=ctx.timeline_id, issue=issue,
        user_comment=comment, affected_scope=scope,
        correction_rule=[item.strip() for item in rules_text.split(";") if item.strip()],
        examples=[item.strip() for item in examples_text.split(";") if item.strip()],
        target_type=target_type, target_id=target_id,
        coordinator=ctx.coordinator())
    ctx.out(f"Feedback 已保存: {getattr(created, 'path', created)}")


def _feedback_resolve(ctx: ConsoleContext) -> None:
    rows = list_feedback(library_root=ctx.library_root, story_id=ctx.story_id,
                         timeline_id=ctx.timeline_id, index_root=ctx.index_root,
                         status="active")
    if not rows:
        ctx.out("没有未解决的 Feedback。")
        return
    document_id = choose(ctx.bridge_in, ctx.out, "未解决 Feedback",
                         [str(row.document_id) for row in rows])
    resolution = _required_line(ctx, "解决说明")
    version = _ask_line(ctx, "新版本", "1.1")
    resolved = resolve_feedback(library_root=ctx.library_root,
                                index_root=ctx.index_root,
                                story_id=ctx.story_id,
                                timeline_id=ctx.timeline_id,
                                feedback_id=document_id,
                                resolution=resolution, version=version,
                                supersedes=document_id,
                                coordinator=ctx.coordinator())
    ctx.out(f"Feedback 已解决: {getattr(resolved, 'status', resolved)}")


@_verb("stories")
def cmd_stories(ctx: ConsoleContext, args: list[str]) -> None:
    def work(_job: Any) -> None:
        action = ctx.bridge_in(
            "1 新建作品 / 2 编辑作者偏好 / 3 切换作品时间线").strip()
        if action == "1":
            created = create_story_wizard(ctx.library_root, ctx.bridge_in, ctx.out)
            if created:
                _switch_story(ctx, created[0], created[1])
        elif action == "2":
            if not ctx.story_id:
                ctx.out("尚未选择作品。")
                return
            preferences_wizard(ctx.library_root, ctx.story_id,
                               ctx.bridge_in, ctx.out)
        elif action == "3":
            stories = sorted(registered_story_ids(ctx.library_root))
            story_id = choose(ctx.bridge_in, ctx.out, "作品", stories)
            timeline_id = choose(ctx.bridge_in, ctx.out, "时间线",
                                 timeline_ids(ctx.library_root, story_id))
            _switch_story(ctx, story_id, timeline_id)
        else:
            ctx.out("无效选项。")

    ctx.run("stories", work, kind="meta", label="作品与时间线")


def _switch_story(ctx: ConsoleContext, story_id: str, timeline_id: str) -> None:
    ctx.story_id = story_id
    ctx.timeline_id = timeline_id
    ctx.last_runtime = latest_runtime(ctx.output_root, story_id)
    profile = ctx.adapter.workspace.model_profile
    ctx.adapter.set_workspace(story_id=story_id, timeline_id=timeline_id,
                              model_profile=profile)
    ctx.out(f"已切换: {story_id}/{timeline_id}")


@_verb("api")
def cmd_api(ctx: ConsoleContext, args: list[str]) -> None:
    def work(_job: Any) -> None:
        api_config_wizard(ctx.model_config_path, ctx.bridge_in, ctx.out)
        from ...model_config import ModelConfigStore
        profile = ModelConfigStore(ctx.model_config_path).get()
        ctx.adapter.set_workspace(
            model_profile=profile.name if profile else None)

    ctx.run("api", work, kind="meta", label="模型 API 设置")


@_verb("tasks")
def cmd_tasks(ctx: ConsoleContext, args: list[str]) -> None:
    limit = 10
    if args and args[0].isdigit():
        limit = max(1, int(args[0]))

    def work(_job: Any) -> None:
        root = ctx.output_root / ".workflow" / (ctx.story_id or "")
        rows: list[dict[str, str]] = []
        if root.is_dir():
            dirs = [p for p in root.iterdir() if p.is_dir()]
            dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for path in dirs[:limit]:
                status = "-"
                result_path = path / "result.json"
                if result_path.is_file():
                    try:
                        data = json.loads(result_path.read_text(encoding="utf-8"))
                        status = str(data.get("status", "-"))
                    except Exception:
                        status = "?"
                stamp = time.strftime("%m-%d %H:%M", time.localtime(path.stat().st_mtime))
                rows.append({"task": path.name, "状态": status, "开始": stamp})
        ctx.out(render_rows_safe(rows))

    ctx.run("tasks", work, kind="meta", label="最近任务")


def render_rows_safe(rows: Any) -> str:
    from ..helpers import render_rows
    if rows and isinstance(rows[0], dict):
        columns = [(key, key) for key in rows[0]]
    else:
        columns = [
            ("得分", lambda r: f"{r.score:.3f}"),
            ("类型", "document_type"),
            ("状态", "status"),
            ("document_id", "document_id"),
            ("标题", "title"),
        ]
    return render_rows(rows, columns)


@_verb("procs")
def cmd_procs(ctx: ConsoleContext, args: list[str]) -> None:
    from .dialogs import make_procs_float
    ctx.open_overlay(make_procs_float(ctx.adapter.runner.active_handles,
                                      on_close=ctx.close_overlay))


@_verb("help")
def cmd_help(ctx: ConsoleContext, args: list[str]) -> None:
    from .dialogs import make_help_float
    ctx.open_overlay(make_help_float(on_close=ctx.close_overlay))


@_verb("clear")
def cmd_clear(ctx: ConsoleContext, args: list[str]) -> None:
    ctx.adapter.blocks.clear()
    ctx.adapter.block_views.clear()
    ctx.adapter.system_line("novel-rag 控制台 · 转录已清屏 · help 查看动词")


@_verb("q")
def cmd_q(ctx: ConsoleContext, args: list[str]) -> None:
    ctx.quit_app()


def dispatch(ctx: ConsoleContext, raw: str) -> bool:
    verb, rest_args = parse_command(raw)
    if verb is None:
        return False
    handler = VERBS.get(verb)
    if handler is None:
        ctx.adapter.system_line(f"   · 未知命令：{verb}（help 查看动词表）")
        return False
    try:
        handler(ctx, rest_args)
    except (GenerationError, ModelAPIError, ModelConfigError, WritebackError,
            RagImportError, GraphError, OSError, ValueError, KeyError,
            RuntimeError) as exc:
        ctx.adapter.notify("error", f"{verb} 失败：{exc}")
    return True
