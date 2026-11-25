"""浮层组件：帮助 / 进程表 / 查看器 / 确认框 / 表单（V1 全浮层，Esc 逐层关闭）。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from prompt_toolkit.layout.containers import Float, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.widgets import Button, Dialog, Label, TextArea

from ..helpers import matches_word

HELP_TEXT = """\
novel-rag 控制台 · 动词一览

写作流   gen 生成草稿 · cont 继续指导任务 · confirm 确认回写 · review 状态提案
资料     upload 上传大纲 · rag 上传 RAG YAML · rebuild 重建索引 · search 检索
管理     stories 作品/时间线 · api 模型配置 · feedback Feedback · summary 摘要
维护     pending Pending 图恢复 · tasks 最近任务 · procs 后台任务 · info 环境
其他     clear 清屏 · help 帮助 · :q 退出（数字 1-14 兼容旧菜单）

按键     Tab 补全/切换焦点 · ↑↓ 历史 · Enter 执行/详情
         o 展开最近折叠全文 · / 或 Ctrl+F 搜索输出 · Ctrl+G 跳最近错误
         Esc 关闭浮层 · Ctrl+C 取消最新任务 · F10 退出确认\
"""

MENU_NUMBERS: dict[str, str] = {
    "1": "gen", "2": "tasks", "3": "cont", "4": "confirm", "5": "review",
    "6": "upload", "7": "rag", "8": "rebuild", "9": "search", "10": "stories",
    "11": "api", "12": "feedback", "13": "summary", "14": "pending",
}


@dataclass
class FieldSpec:
    name: str
    label: str
    default: str = ""
    password: bool = False
    multiline: bool = False
    required: bool = False


def make_help_float(on_close: Callable[[], None] | None = None) -> Float:
    rows = []
    for line in HELP_TEXT.splitlines():
        style = "class:muted" if line.startswith("按键") or line.startswith("novel") \
            else ""
        rows.append(Window(content=FormattedTextControl([(style, line)]),
                           height=1, dont_extend_height=True))
    body = HSplit(rows, width=D(preferred=72))
    close = on_close or (lambda: None)
    return Float(content=Dialog(title="帮助", body=body,
                                buttons=[Button("关闭", handler=close)]))


def make_procs_float(handles_provider: Callable[[], Any],
                     on_close: Callable[[], None] | None = None) -> Float:
    def _rows():
        handles = handles_provider()
        if not handles:
            return [("", "（无活动任务）")]
        rows = [("class:muted", f"{'ID':<9} {'KIND':<10} {'状态':<8} 耗时   详情")]
        for job in handles:
            status = "⊘ 已取消" if job.cancelled else "● 运行中"
            rows.append(("", f"{job.id:<9} {job.kind:<10} {status:<6} "
                             f"{job.elapsed:>5.0f}s {job.detail or ''}"))
        return rows

    body = HSplit([Window(content=FormattedTextControl(_rows),
                          height=D(min=3, max=16))], width=D(preferred=64))
    close = on_close or (lambda: None)
    return Float(content=Dialog(title="后台任务", body=body,
                                buttons=[Button("关闭", handler=close)]))


def make_viewer_float(title: str, text: str,
                      on_close: Callable[[], None] | None = None) -> Float:
    area = TextArea(text=text or "（空）", read_only=True, wrap_lines=True,
                    scrollbar=True)
    body = HSplit([area], width=D(preferred=100), height=D(preferred=24))
    close = on_close or (lambda: None)
    return Float(content=Dialog(title=title, body=body,
                                buttons=[Button("关闭", handler=close)]))


def make_confirm_float(message: str, word: str, on_ok: Callable[[], None],
                       on_cancel: Callable[[], None]) -> Float:
    entry = TextArea(multiline=False, height=1)

    def _ok() -> None:
        if matches_word(entry.text, word):
            on_ok()
        else:
            on_cancel()

    def _accept(_buffer) -> bool:
        _ok()
        return True

    entry.accept_handler = _accept
    buttons = [Button(f"输入 {word} 确认", handler=_ok),
               Button("取消", handler=on_cancel)]
    body = HSplit([Label(text=message), entry], width=D(min=48))
    return Float(content=Dialog(title="确认操作", body=body, buttons=buttons))


def make_form_float(title: str, fields: list[FieldSpec],
                    on_submit: Callable[[dict[str, str]], None],
                    on_cancel: Callable[[], None]) -> Float:
    entries: dict[str, TextArea] = {}
    error_holder: list[str] = []

    def _submit() -> None:
        values: dict[str, str] = {}
        missing = []
        for spec in fields:
            value = entries[spec.name].text.strip()
            if spec.required and not value:
                missing.append(spec.label.rstrip("* "))
                continue
            values[spec.name] = value
        if missing:
            error_holder[:] = ["、".join(missing)]
            return
        error_holder[:] = []
        on_submit(values)

    def _entry_accept(_buffer) -> bool:
        _submit()
        return True

    def _error_fragments():
        if not error_holder:
            return [("", "")]
        return [("class:error", f"✗ 必填未填：{error_holder[0]}")]

    rows = [Window(content=FormattedTextControl(_error_fragments), height=1,
                   dont_extend_height=True)]
    for spec in fields:
        area = TextArea(text=spec.default, multiline=spec.multiline,
                        password=spec.password,
                        height=4 if spec.multiline else 1,
                        accept_handler=None if spec.multiline else _entry_accept)
        entries[spec.name] = area
        suffix = " *" if spec.required else ""
        rows.append(HSplit([Label(text=f"{spec.label}{suffix}"), area]))

    body = HSplit(rows, width=D(preferred=72))
    buttons = [Button("提交", handler=_submit), Button("取消", handler=on_cancel)]
    return Float(content=Dialog(title=title, body=body, buttons=buttons))
