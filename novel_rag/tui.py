from __future__ import annotations

import json
import os
import getpass
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from .documents import read_yaml_mapping, registered_story_ids
from .generation import GenerationError, PreferenceRequired, generate
from .index import rebuild_isolated_indexes
from .layout import story_root
from .model_api import ModelAPIError, OpenAICompatibleModel
from .model_config import ModelConfigError, ModelConfigStore, default_config_path
from .onboarding import PREFERENCE_SECTIONS, render_author_preferences, save_author_preferences
from .rag_import import (RagImportError, import_outline, import_rag_yaml,
                         preview_outline, preview_rag_yaml)
from .scaffold import create_story
from .service import load_valid_documents
from .writeback import WritebackError, confirm_runtime


Input = Callable[[str], str]
Output = Callable[[str], None]


def _ask(input_fn: Input, prompt: str, *, default: str = "", required: bool = False) -> str:
    while True:
        value = input_fn(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
        if value:
            return value
        if default:
            return default
        if not required:
            return ""


def _number(input_fn: Input, output: Output, prompt: str, *, default: int | None = None,
            minimum: int = 0) -> int | None:
    while True:
        value = _ask(input_fn, prompt, default=str(default) if default is not None else "")
        if not value:
            return None
        try:
            number = int(value)
            if number >= minimum:
                return number
        except ValueError:
            pass
        output(f"请输入不小于 {minimum} 的整数。")


def _choose(input_fn: Input, output: Output, title: str, values: list[str]) -> str:
    if not values:
        raise GenerationError(f"没有可用的{title}")
    if len(values) == 1:
        output(f"{title}: {values[0]}")
        return values[0]
    output(title + "：")
    for index, value in enumerate(values, 1):
        output(f"  {index}. {value}")
    while True:
        selected = _ask(input_fn, "请选择编号", required=True)
        if selected.isdigit() and 1 <= int(selected) <= len(values):
            return values[int(selected) - 1]
        output("无效编号。")


def _timeline_ids(library_root: Path, story_id: str) -> list[str]:
    rows = read_yaml_mapping(story_root(library_root, story_id) / "registry" / "timelines.yaml").get("timelines", [])
    return [str(row["timeline_id"]) for row in rows
            if isinstance(row, dict) and row.get("story_id") == story_id and row.get("timeline_id")]


def _reference_texts(value: str) -> list[str]:
    references: list[str] = []
    for item in (part.strip() for part in value.split(";") if part.strip()):
        path = Path(item)
        references.append(path.read_text(encoding="utf-8-sig") if path.is_file() else item)
    return references


def _outline_input(value: str) -> Any:
    path = Path(value)
    if not path.is_file():
        return value
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in {".yaml", ".yml"}:
        parsed = yaml.safe_load(text)
        if isinstance(parsed, dict) and isinstance(parsed.get("metadata"), dict):
            if parsed["metadata"].get("document_type") == "outline" and isinstance(parsed.get("outline"), dict):
                return parsed["outline"]
    return text


def _preview(text: str, limit: int = 1200) -> str:
    clean = text.strip()
    return clean if len(clean) <= limit else clean[:limit] + "\n……（完整正文见 runtime）"


def _dataclass_preview(value: Any) -> str:
    fields = getattr(value, "__dataclass_fields__", {})
    return json.dumps({name: getattr(value, name) for name in fields},
                      ensure_ascii=False, indent=2, default=str)


def _latest_runtime(output_root: Path, story_id: str) -> Path | None:
    root = output_root / ".workflow" / story_id
    candidates = [path for path in root.iterdir() if path.is_dir()] if root.is_dir() else []
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def _current_family_document(library_root: Path, story_id: str, family: str) -> str:
    value = read_yaml_mapping(story_root(library_root, story_id) / "registry" / "version-map.yaml")
    for row in value.get("versions", []) if isinstance(value.get("versions"), list) else []:
        if isinstance(row, dict) and str(row.get("document_family") or "") == family:
            return str(row.get("current") or "")
    return ""


def _show_runtime(path: Path, output: Output) -> None:
    result_path = path / "result.json"
    if not result_path.is_file():
        raise OSError(f"runtime 缺少 result.json: {path}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    output(f"状态: {result.get('status', 'unknown')}")
    output(f"自动修复次数: {result.get('attempts', 0)}")
    for warning in result.get("warnings", []) if isinstance(result.get("warnings"), list) else []:
        output(f"警告: {warning}")
    validation = result.get("validation") or {}
    for issue in validation.get("issues", []) if isinstance(validation, dict) else []:
        if isinstance(issue, dict):
            output(f"审计[{issue.get('severity', 'warning')} / {issue.get('check', 'unknown')}]: "
                   f"{issue.get('message', '')}")
    final = path / "final.txt"
    text = final.read_text(encoding="utf-8") if final.is_file() else str(result.get("text") or "")
    if text.strip():
        output("\n正文预览：\n" + _preview(text))
    elif (path / "confirmation.json").is_file():
        output("正文已确认并迁移到正式 History。")


def _model_from_local_config(input_fn: Input, output: Output, config_path: Path) -> OpenAICompatibleModel:
    store = ModelConfigStore(config_path)
    profile = store.get()
    if profile is not None:
        output(f"使用本地模型配置: {profile.name} ({profile.model})")
        return store.build_model()
    # Backward-compatible fallback for existing users. New setups use menu 12
    # and never need environment variables.
    model_name = _ask(input_fn, "API 模型", default=os.environ.get("NOVEL_RAG_MODEL", ""), required=True)
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    api_key = os.environ.get("OPENAI_API_KEY")
    if "api.openai.com" in base_url and not api_key:
        raise ModelAPIError("请先设置环境变量 OPENAI_API_KEY")
    return OpenAICompatibleModel(
        base_url=base_url, model=model_name, api_key=api_key,
        mode=os.environ.get("OPENAI_API_MODE", "responses"),
    )


def _secret(input_fn: Input, prompt: str) -> str:
    if input_fn is input:
        return getpass.getpass(prompt + ": ").strip()
    return input_fn(prompt + ": ").strip()


def _api_config_wizard(config_path: Path, input_fn: Input, output: Output) -> None:
    store = ModelConfigStore(config_path)
    document = store.load()
    output(f"本地配置文件: {store.path}")
    output(f"当前 profile: {document.get('active') or '未设置'}；可用: {', '.join(store.list_profiles()) or '无'}")
    output("1. 新增/修改  2. 切换  3. 查看  4. 删除  其他. 返回")
    action = _ask(input_fn, "选择")
    if action == "1":
        name = _ask(input_fn, "profile 名称", default=str(document.get("active") or "default"))
        current = store.get(name)
        base_url = _ask(input_fn, "API 根地址", default=current.base_url if current else "https://api.openai.com/v1")
        model = _ask(input_fn, "模型名称", default=current.model if current else "", required=not bool(current))
        mode = _ask(input_fn, "协议 responses/chat", default=current.mode if current else "responses")
        no_auth = _ask(input_fn, "本地无鉴权接口？yes/no", default="yes" if current and current.no_auth else "no")
        key = "" if no_auth.lower() in {"yes", "y"} else _secret(
            input_fn, "API key（直接回车保留旧 key；输入 CLEAR 清除）"
        )
        updates: dict[str, Any] = {
            "base_url": base_url, "model": model, "mode": mode,
            "no_auth": no_auth.lower() in {"yes", "y"},
        }
        if key == "CLEAR":
            updates["api_key"] = None
        elif key:
            updates["api_key"] = key
        output(json.dumps({key: ("***" if key == "api_key" else value)
                           for key, value in updates.items()}, ensure_ascii=False, indent=2))
        if _ask(input_fn, "输入 SAVE 保存并设为当前") != "SAVE":
            output("已取消保存。")
            return
        store.set_profile(name, updates)
        store.set_active(name)
        output(f"模型配置已保存并启用: {name}")
    elif action == "2":
        name = _choose(input_fn, output, "模型 profile", store.list_profiles())
        store.set_active(name)
        output(f"已切换到: {name}")
    elif action == "3":
        profile = store.get(_ask(input_fn, "profile 名称（留空查看当前）"))
        if profile is None:
            raise ModelConfigError("找不到模型 profile")
        output(json.dumps({"name": profile.name, **profile.to_dict()}, ensure_ascii=False, indent=2))
    elif action == "4":
        name = _choose(input_fn, output, "模型 profile", store.list_profiles())
        if _ask(input_fn, f"输入 DELETE 删除 {name}") == "DELETE":
            store.delete_profile(name)
            output(f"已删除: {name}")


def _preferences_wizard(library_root: Path, story_id: str, input_fn: Input, output: Output) -> Path | None:
    path = library_root / "stories" / story_id / "author-preferences.txt"
    overwrite = path.exists() and bool(path.read_text(encoding="utf-8-sig").strip())
    if overwrite:
        output("当前作者偏好：\n" + path.read_text(encoding="utf-8-sig"))
        if _ask(input_fn, "输入 EDIT 重新填写；其他输入取消") != "EDIT":
            return None
    output("逐项填写即可；不指定的项目直接回车。")
    values = {section: _ask(input_fn, section) for section in PREFERENCE_SECTIONS}
    text = render_author_preferences(values)
    output("\n即将保存的作者偏好：\n" + text)
    if _ask(input_fn, "输入 SAVE 保存") != "SAVE":
        output("已取消保存。")
        return None
    saved = save_author_preferences(library_root, story_id, text, overwrite=overwrite)
    output(f"作者偏好已保存: {saved}")
    return saved


def _create_story_wizard(library_root: Path, input_fn: Input, output: Output) -> tuple[str, str] | None:
    story_id = _ask(input_fn, "新作品 story_id（小写字母、数字、连字符）", required=True)
    title = _ask(input_fn, "作品标题", required=True)
    timeline_id = _ask(input_fn, "时间线 ID", default="main")
    timeline_name = _ask(input_fn, "时间线名称", default="主世界线")
    language = _ask(input_fn, "语言", default="zh-CN")
    output(f"将创建 {story_id} / {title} / {timeline_id}，并继承共享模块。")
    if _ask(input_fn, "输入 CREATE 确认") != "CREATE":
        output("已取消创建。")
        return None
    create_story(library_root, story_id=story_id, title=title, timeline_id=timeline_id,
                 timeline_name=timeline_name, language=language, inherit_shared=True)
    output(f"作品已创建: {story_id}")
    _preferences_wizard(library_root, story_id, input_fn, output)
    return story_id, timeline_id


def _confirm_review(path: Path, output: Output) -> dict[str, Any] | None:
    try:
        contract = json.loads((path / "contract.json").read_text(encoding="utf-8"))
        result = json.loads((path / "result.json").read_text(encoding="utf-8"))
        final = (path / "final.txt").read_text(encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    output("\n=== 确认前完整复核 ===")
    request = contract.get("request") or {}
    output(f"作品/时间线: {request.get('story_id', '')}/{request.get('timeline_id', '')}")
    output(f"状态: {result.get('status')}；修复次数: {result.get('attempts', 0)}")
    for warning in result.get("warnings", []) if isinstance(result.get("warnings"), list) else []:
        output(f"警告: {warning}")
    validation = result.get("validation") or {}
    for issue in validation.get("issues", []) if isinstance(validation, dict) else []:
        if isinstance(issue, dict):
            output(f"审计[{issue.get('severity', '')}]: {issue.get('message', '')}")
    output("\n--- 正文全文 ---\n" + final + "\n--- 正文结束 ---")
    output("确认后将写入正式 History、生成状态审核提案，并清理 runtime 中的正文/审计临时文件。")
    return {"contract": contract, "result": result, "text": final}


def run_tui(
    library_root: Path,
    index_root: Path | None = None,
    *,
    input_fn: Input = input,
    output: Output = print,
    generate_fn: Callable[..., Any] = generate,
    confirm_fn: Callable[..., Any] = confirm_runtime,
    resume_fn: Callable[..., Any] | None = None,
    state_inspect_fn: Callable[..., Any] | None = None,
    state_approve_fn: Callable[..., Any] | None = None,
    state_reject_fn: Callable[..., Any] | None = None,
    model_config_path: Path | None = None,
) -> int:
    library_root = library_root.resolve()
    index_root = (index_root or library_root / "index").resolve()
    output_root = library_root.parent / "outputs"
    model_config_path = Path(model_config_path or default_config_path()).expanduser()
    try:
        stories = sorted(registered_story_ids(library_root))
        if not stories:
            output("当前知识库还没有作品，先完成一次建书向导。")
            created = _create_story_wizard(library_root, input_fn, output)
            if created is None:
                return 0
            story_id, timeline_id = created
        else:
            story_id = _choose(input_fn, output, "作品", stories)
            timeline_id = _choose(input_fn, output, "时间线", _timeline_ids(library_root, story_id))
    except (EOFError, KeyboardInterrupt):
        output("已退出。")
        return 0
    except (GenerationError, OSError, ValueError) as exc:
        output(f"ERROR {exc}")
        return 1

    last_runtime = _latest_runtime(output_root, story_id)
    last_outline: Path | None = None
    while True:
        output("\n=== Novel RAG ===")
        output("1. 生成草稿\n2. 查看最近运行\n3. 确认并回写\n4. 上传大纲\n5. 上传 RAG YAML"
               "\n6. 校验并重建索引\n7. 退出\n8. 审核状态提案\n9. 继续需要指导的任务"
               "\n10. 作品与作者偏好\n11. Feedback 管理\n12. 本地模型 API 设置")
        try:
            choice = _ask(input_fn, "选择", required=True)
            if choice == "7":
                output("已退出。")
                return 0
            if choice == "1":
                outline_value = _ask(
                    input_fn, "大纲文本或 UTF-8 文件路径",
                    default=str(last_outline) if last_outline else "", required=not bool(last_outline),
                )
                outline = _outline_input(outline_value)
                current_request = _ask(input_fn, "本轮补充要求（可留空）")
                references = _reference_texts(_ask(input_fn, "Reference 路径/文本，多个用分号分隔（可留空）"))
                target = _number(input_fn, output, "目标字数（可留空）")
                model = _model_from_local_config(input_fn, output, model_config_path)
                task_id = _ask(input_fn, "任务 ID", default="generation")
                target_runtime = output_root / ".workflow" / story_id / task_id
                if target_runtime.exists() and any(target_runtime.iterdir()):
                    output(f"任务目录已存在: {target_runtime}")
                    action = _ask(input_fn, "输入 NEW 使用新任务 ID；输入 CONTINUE 转到指导续作；其他输入取消")
                    if action == "CONTINUE":
                        last_runtime = target_runtime
                        output("请从菜单 9 继续该任务。")
                        continue
                    if action != "NEW":
                        output("已取消生成。")
                        continue
                    task_id = _ask(input_fn, "新的任务 ID", required=True)
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
                output("\n正文预览：\n" + _preview(result.text))
                if result.status == "user_guidance_required":
                    output("该任务需要作者补充指导；可从菜单 9 继续，不会覆盖当前 runtime。")
            elif choice == "2":
                default = str(last_runtime) if last_runtime else ""
                runtime = Path(_ask(input_fn, "runtime 目录", default=default, required=not bool(default)))
                _show_runtime(runtime, output)
                last_runtime = runtime
            elif choice == "3":
                default = str(last_runtime) if last_runtime else ""
                runtime = Path(_ask(input_fn, "runtime 目录", default=default, required=not bool(default)))
                review = _confirm_review(runtime, output)
                volume = _number(input_fn, output, "卷号", default=1)
                chapter = _number(input_fn, output, "章节号", minimum=1)
                scene = _number(input_fn, output, "场景号", default=1, minimum=1)
                if chapter is None:
                    output("章节号不能为空。")
                    continue
                title = pov = ""
                character_ids: list[str] | None = None
                location_ids: list[str] | None = None
                if review is not None:
                    title = _ask(input_fn, "章节/场景标题（可留空使用默认）")
                    pov = _ask(input_fn, "POV 角色 ID（可留空）")
                    characters = _ask(input_fn, "角色 ID，多个用逗号分隔（可留空）")
                    locations = _ask(input_fn, "地点 ID，多个用逗号分隔（可留空）")
                    character_ids = [item.strip() for item in characters.split(",") if item.strip()] or None
                    location_ids = [item.strip() for item in locations.split(",") if item.strip()] or None
                    output(f"正式目标: {story_id}/{timeline_id} 卷{volume} 章{chapter} 场景{scene}")
                if _ask(input_fn, "输入 YES 确认迁移到正式 History 并清理临时正文") != "YES":
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
                source = Path(_ask(input_fn, "大纲 TXT/Markdown/YAML 文件", required=True))
                title = _ask(input_fn, "大纲标题", default=source.stem)
                volume = _number(input_fn, output, "卷号", default=1)
                chapter = _number(input_fn, output, "章节号", minimum=1)
                version = _ask(input_fn, "版本", default="1.0")
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
                output("大纲上传预览：\n" + _dataclass_preview(preview))
                if preview.conflicts:
                    output("检测到大纲版本冲突；旧版本不会被覆盖。")
                    version = _ask(input_fn, "新版本号", required=True)
                    supersedes = _ask(input_fn, "要替代的 current document_id", required=True)
                    family = _ask(input_fn, "document_family", default=preview.document_family)
                    preview = preview_outline(
                        source, library_root=library_root, index_root=index_root,
                        story_id=story_id, timeline_id=timeline_id, title=title,
                        volume=volume if volume is not None else 0, chapter=chapter, version=version,
                        supersedes=supersedes, document_family=family,
                    )
                    if preview.conflicts:
                        raise RagImportError("版本预览仍有冲突: " + "；".join(preview.conflicts))
                if _ask(input_fn, "输入 IMPORT 确认写入正式 Outline") != "IMPORT":
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
                source = Path(_ask(input_fn, "符合 novel-rag 模板的 YAML 文件", required=True))
                preview = preview_rag_yaml(
                    source, library_root=library_root, index_root=index_root,
                    story_id=story_id, timeline_id=timeline_id,
                )
                output("上传预览：\n" + _dataclass_preview(preview))
                version = supersedes = family = None
                if preview.conflicts:
                    output("检测到版本冲突；不会覆盖现有文档。")
                    version = _ask(input_fn, "新版本号", required=True)
                    supersedes = _ask(input_fn, "要替代的 current document_id", required=True)
                    family = _ask(input_fn, "document_family", default=preview.document_family)
                    preview = preview_rag_yaml(
                        source, library_root=library_root, index_root=index_root,
                        story_id=story_id, timeline_id=timeline_id,
                        version=version, supersedes=supersedes, document_family=family,
                    )
                    if preview.conflicts:
                        raise RagImportError("版本预览仍有冲突: " + "；".join(preview.conflicts))
                if _ask(input_fn, "输入 IMPORT 确认写入正式 RAG") != "IMPORT":
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
                from .state_review import approve_state_proposal, inspect_state_proposal, reject_state_proposal
                inspect = state_inspect_fn or inspect_state_proposal
                approve = state_approve_fn or approve_state_proposal
                reject = state_reject_fn or reject_state_proposal
                default = str(last_runtime) if last_runtime else ""
                runtime = Path(_ask(input_fn, "runtime 目录", default=default, required=not bool(default)))
                proposal = inspect(runtime, library_root=library_root)
                output(json.dumps(proposal, ensure_ascii=False, indent=2, default=str))
                decision = _ask(input_fn, "输入 APPROVE 批准，REJECT 拒绝，其他输入取消")
                if decision == "APPROVE":
                    reason = _ask(input_fn, "审核说明", default="作者已核对最终正文与状态变化")
                    reviewed = approve(runtime, library_root=library_root, index_root=index_root, note=reason)
                    output(f"状态提案处理完成: {getattr(reviewed, 'status', reviewed)}")
                elif decision == "REJECT":
                    reason = _ask(input_fn, "拒绝原因", required=True)
                    reviewed = reject(runtime, library_root=library_root, reason=reason)
                    output(f"状态提案已拒绝: {getattr(reviewed, 'status', reviewed)}")
                else:
                    output("已取消审核。")
            elif choice == "9":
                from .resume import continue_generation
                resume = resume_fn or continue_generation
                default = str(last_runtime) if last_runtime else ""
                runtime = Path(_ask(input_fn, "需要继续的 runtime", default=default, required=not bool(default)))
                _show_runtime(runtime, output)
                guidance = _ask(input_fn, "请提供针对审计问题的写作指导", required=True)
                child_task_id = _ask(input_fn, "新任务 ID（不会覆盖原任务）", default=runtime.name + "-guided")
                model = _model_from_local_config(input_fn, output, model_config_path)
                continued = resume(runtime, guidance, model, library_root=library_root,
                                   index_root=index_root, output_root=output_root, task_id=child_task_id)
                last_runtime = Path(continued.extensions["runtime_dir"])
                output(f"继续生成状态: {continued.status}\nruntime: {last_runtime}")
                output("\n正文预览：\n" + _preview(continued.text))
            elif choice == "10":
                output("1. 新建作品  2. 编辑当前作品作者偏好  3. 切换作品/时间线")
                action = _ask(input_fn, "选择", required=True)
                if action == "1":
                    created = _create_story_wizard(library_root, input_fn, output)
                    if created:
                        story_id, timeline_id = created
                        last_runtime = _latest_runtime(output_root, story_id)
                elif action == "2":
                    _preferences_wizard(library_root, story_id, input_fn, output)
                elif action == "3":
                    story_id = _choose(input_fn, output, "作品", sorted(registered_story_ids(library_root)))
                    timeline_id = _choose(input_fn, output, "时间线", _timeline_ids(library_root, story_id))
                    last_runtime = _latest_runtime(output_root, story_id)
                else:
                    output("无效选项。")
            elif choice == "11":
                from .feedback import create_feedback, list_feedback, resolve_feedback
                output("1. 新建 Feedback  2. 查看未解决 Feedback  3. 标记已解决")
                action = _ask(input_fn, "选择", required=True)
                if action == "1":
                    issue = _ask(input_fn, "问题", required=True)
                    comment = _ask(input_fn, "作者反馈", required=True)
                    scope = _ask(input_fn, "影响范围", default="后续生成")
                    rule = _ask(input_fn, "修正规则", required=True)
                    target_type = _ask(input_fn, "目标类型", default="runtime" if last_runtime else "history")
                    target_id = _ask(input_fn, "绑定的 runtime task ID / RAG document_id",
                                     default=last_runtime.name if last_runtime and target_type == "runtime" else "",
                                     required=True)
                    output(f"将把 Feedback 写入正式 RAG: {target_type}/{target_id}；问题：{issue}")
                    if _ask(input_fn, "输入 FEEDBACK 确认写入") != "FEEDBACK":
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
                    document_id = _ask(input_fn, "Feedback document_id", required=True)
                    resolution = _ask(input_fn, "解决说明", required=True)
                    version = _ask(input_fn, "新版本", default="1.1")
                    resolved = resolve_feedback(library_root=library_root, index_root=index_root,
                                                story_id=story_id, timeline_id=timeline_id,
                                                feedback_id=document_id, resolution=resolution,
                                                version=version, supersedes=document_id)
                    output(f"Feedback 已解决: {getattr(resolved, 'status', resolved)}")
                else:
                    output("无效选项。")
            elif choice == "12":
                _api_config_wizard(model_config_path, input_fn, output)
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
