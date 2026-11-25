"""Wizard-style interactive functions for the TUI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..model_config import ModelConfigError, ModelConfigStore
from ..onboarding import PREFERENCE_SECTIONS, render_author_preferences, save_author_preferences
from ..scaffold import create_story
from .helpers import Input, Output, ask, confirm_word, number, secret, choose


def api_config_wizard(config_path: Path, input_fn: Input, output: Output) -> None:
    store = ModelConfigStore(config_path)
    document = store.load()
    output(f"本地配置文件: {store.path}")
    output(f"当前 profile: {document.get('active') or '未设置'}；可用: {', '.join(store.list_profiles()) or '无'}")
    output("1. 新增/修改  2. 切换  3. 查看  4. 删除  其他. 返回")
    action = ask(input_fn, "选择")
    if action == "1":
        name = ask(input_fn, "profile 名称", default=str(document.get("active") or "default"))
        current = store.get(name)
        base_url = ask(input_fn, "API 根地址", default=current.base_url if current else "https://api.openai.com/v1")
        model = ask(input_fn, "模型名称", default=current.model if current else "", required=not bool(current))
        mode = ask(input_fn, "协议 responses/chat", default=current.mode if current else "chat")
        no_auth = ask(input_fn, "本地无鉴权接口？yes/no", default="yes" if current and current.no_auth else "no")
        key = "" if no_auth.lower() in {"yes", "y"} else secret(
            input_fn, "API key（直接回车保留旧 key；输入 CLEAR 清除）"
        )
        timeout = number(input_fn, output, "连接超时秒（可留空）",
                         default=int(current.timeout) if current else None, minimum=1)
        retries = number(input_fn, output, "重试次数（可留空）",
                         default=current.retries if current else None)
        max_tokens = number(input_fn, output, "最大输出 tokens（可留空）",
                            default=current.max_output_tokens if current else None, minimum=1)
        updates: dict[str, Any] = {
            "base_url": base_url, "model": model, "mode": mode,
            "no_auth": no_auth.lower() in {"yes", "y"},
        }
        if timeout is not None:
            updates["timeout"] = timeout
        if retries is not None:
            updates["retries"] = retries
        if max_tokens is not None:
            updates["max_output_tokens"] = max_tokens
        if key == "CLEAR":
            updates["api_key"] = None
        elif key:
            updates["api_key"] = key
        output(json.dumps({key: ("***" if key == "api_key" else value)
                           for key, value in updates.items()}, ensure_ascii=False, indent=2))
        if not confirm_word(input_fn, output, "保存并设为当前", "SAVE"):
            output("已取消保存。")
            return
        store.set_profile(name, updates)
        store.set_active(name)
        output(f"模型配置已保存并启用: {name}")
    elif action == "2":
        name = choose(input_fn, output, "模型 profile", store.list_profiles())
        store.set_active(name)
        output(f"已切换到: {name}")
    elif action == "3":
        profile = store.get(ask(input_fn, "profile 名称（留空查看当前）"))
        if profile is None:
            raise ModelConfigError("找不到模型 profile")
        output(json.dumps({"name": profile.name, **profile.to_dict()}, ensure_ascii=False, indent=2))
    elif action == "4":
        name = choose(input_fn, output, "模型 profile", store.list_profiles())
        if confirm_word(input_fn, output, f"删除 profile {name}", "DELETE"):
            store.delete_profile(name)
            output(f"已删除: {name}")


def preferences_wizard(library_root: Path, story_id: str, input_fn: Input, output: Output) -> Path | None:
    path = library_root / "stories" / story_id / "author-preferences.txt"
    overwrite = path.exists() and bool(path.read_text(encoding="utf-8-sig").strip())
    if overwrite:
        output("当前作者偏好：\n" + path.read_text(encoding="utf-8-sig"))
        if not confirm_word(input_fn, output, "重新填写作者偏好", "EDIT"):
            return None
    output("逐项填写即可；不指定的项目直接回车。")
    values = {section: ask(input_fn, section) for section in PREFERENCE_SECTIONS}
    text = render_author_preferences(values)
    output("\n即将保存的作者偏好：\n" + text)
    if not confirm_word(input_fn, output, "保存作者偏好", "SAVE"):
        output("已取消保存。")
        return None
    saved = save_author_preferences(library_root, story_id, text, overwrite=overwrite)
    output(f"作者偏好已保存: {saved}")
    return saved


def create_story_wizard(library_root: Path, input_fn: Input, output: Output) -> tuple[str, str] | None:
    story_id = ask(input_fn, "新作品 story_id（小写字母、数字、连字符）", required=True)
    title = ask(input_fn, "作品标题", required=True)
    timeline_id = ask(input_fn, "时间线 ID", default="main")
    timeline_name = ask(input_fn, "时间线名称", default="主世界线")
    language = ask(input_fn, "语言", default="zh-CN")
    output(f"将创建 {story_id} / {title} / {timeline_id}，并继承共享模块。")
    if not confirm_word(input_fn, output, "确认创建", "CREATE"):
        output("已取消创建。")
        return None
    create_story(library_root, story_id=story_id, title=title, timeline_id=timeline_id,
                 timeline_name=timeline_name, language=language, inherit_shared=True)
    output(f"作品已创建: {story_id}")
    preferences_wizard(library_root, story_id, input_fn, output)
    return story_id, timeline_id