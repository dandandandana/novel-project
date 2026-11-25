"""ConsoleApp 组装：布局 / 双态导航 / 浮层栈 / 键位 / 生命周期。"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import CompleteEvent, Completer, Completion, PathCompleter, WordCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, is_searching
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.bindings.search import start_forward_incremental_search
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import (
    ConditionalContainer,
    Float,
    FloatContainer,
    HSplit,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.widgets import SearchToolbar, TextArea

from .adapter import ConsoleAdapter
from .commands import VERBS, ConsoleContext, dispatch
from .config import UiConfig
from .dialogs import make_confirm_float, make_procs_float, make_viewer_float
from .status import input_prefix, render_hint, render_top_line
from .theme import build_style
from .widgets import TranscriptLexer


class _VerbCompleter(Completer):
    """动词补全 + 路径参数补全路由。"""

    _PATH_VERBS = {"upload", "rag", "cont", "confirm", "review"}

    def __init__(self, verbs: tuple[str, ...]) -> None:
        self._words = WordCompleter(list(verbs) + ["q"], ignore_case=True,
                                    sentence=True, match_middle=True)
        self._paths = PathCompleter(expanduser=True)

    def _argument_document(self, raw: str) -> Document | None:
        """抽出动词之后的参数段；非路径动词或仍在输入动词时返回 None。

        PathCompleter 把整段 text_before_cursor 当作路径，因此必须先剥掉
        动词前缀再交给它；返回文档的光标位于参数段末尾，补全的相对位置
        与真实缓冲一致。
        """

        parts = raw.lstrip().split()
        at_argument = len(parts) >= 2 or (len(parts) == 1 and raw[-1:].isspace())
        if not at_argument or parts[0].lower() not in self._PATH_VERBS:
            return None
        verb_end = (len(raw) - len(raw.lstrip())) + len(parts[0])
        rest = raw[verb_end:]
        argument = rest.lstrip()
        return Document(argument, cursor_position=len(argument))

    def get_completions(self, document: Document, event: CompleteEvent):
        argument = self._argument_document(document.text_before_cursor)
        if argument is not None:
            yield from self._paths.get_completions(argument, event)
            return
        yield from self._words.get_completions(document, event)


class ConsoleApp:
    """组装并运行全屏控制台；内部错误一律降级而非崩溃。"""

    def __init__(self, context: ConsoleContext, adapter: ConsoleAdapter,
                 config: UiConfig, history_path: Path,
                 *, output=None, input=None) -> None:
        self.ctx = context
        self.adapter = adapter
        self.config = config
        self.floats: list[Float] = []
        self._ticker_stop = threading.Event()

        history_path.parent.mkdir(parents=True, exist_ok=True)
        self.input_buffer = Buffer(multiline=False,
                                   history=FileHistory(str(history_path)),
                                   completer=_VerbCompleter(tuple(sorted(VERBS))),
                                   accept_handler=self._accept)

        self.search_bar = SearchToolbar()
        self.transcript = TextArea(text="", read_only=True, wrap_lines=True,
                                   scrollbar=True, lexer=TranscriptLexer(),
                                   search_field=self.search_bar,
                                   focusable=True, name="transcript")
        self._sync_text(force=True)

        top = Window(content=FormattedTextControl(self._top_fragments), height=1)
        hint = ConditionalContainer(
            Window(content=FormattedTextControl(self._hint_fragments), height=1),
            filter=Condition(lambda: self._input_focused()))
        prefix_window = Window(content=FormattedTextControl(self._prefix_fragments),
                               height=1, dont_extend_height=True)
        self.input_window = Window(content=BufferControl(buffer=self.input_buffer),
                                   height=1)
        input_row = VSplit([prefix_window, self.input_window])
        body = HSplit([
            top,
            Window(height=1, char="─", style="class:border"),
            ConditionalContainer(self.search_bar, filter=is_searching),
            self.transcript,
            Window(height=1, char="─", style="class:border"),
            hint,
            ConditionalContainer(Window(height=1, char="─", style="class:border"),
                                 filter=Condition(lambda: self._input_focused())),
            input_row,
        ])
        root = FloatContainer(content=body, floats=self.floats)
        self.root_container = root

        self.app: Application = Application(
            layout=Layout(root, focused_element=self.input_window),
            style=build_style(config),
            key_bindings=self._build_keys(),
            mouse_support=True,
            full_screen=True,
            output=output,
            input=input,
        )
        adapter._on_invalidate = self._on_invalidate

    # ------------------------------------------------------------------ 状态投影
    def _input_focused(self) -> bool:
        return self.app.layout.current_control is not None and \
            getattr(self.app.layout.current_control, "buffer", None) is self.input_buffer

    def _top_fragments(self):
        columns = shutil.get_terminal_size().columns
        state = self.adapter.snapshot()
        line = render_top_line(state, max(20, columns))
        badge = f"[{state.unread}]" if state.unread else ""
        if badge and line.endswith(badge):
            head = line[: -len(badge)].rstrip()
            return [("class:header", head), ("class:badge", " " + badge)]
        return [("class:header", line)]

    def _hint_fragments(self):
        columns = shutil.get_terminal_size().columns
        state = self.adapter.snapshot()
        return [("", render_hint(state, max(20, columns)))]

    def _prefix_fragments(self):
        request = self.adapter.pending_ask
        if request is not None:
            return [("class:input-prefix", f"? {request.prompt}: ")]
        state = self.adapter.snapshot()
        style = "class:muted" if state.active_jobs else "class:input-prefix"
        return [(style, input_prefix(state))]

    # ------------------------------------------------------------------ 转录同步
    def _sync_text(self, force: bool = False) -> None:
        store = self.adapter.blocks
        if not force and not store.dirty:
            return
        new_text = store.render_text()
        buffer = self.transcript.buffer
        old_len = len(buffer.text)
        old_pos = buffer.cursor_position
        stay_end = old_pos >= old_len - 1
        buffer.set_document(Document(new_text, len(new_text)), bypass_readonly=True)
        if not stay_end:
            buffer.cursor_position = min(old_pos, len(new_text))
        store.mark_clean()

    def _on_invalidate(self) -> None:
        self._sync_text()
        try:
            self.app.invalidate()
        except Exception:
            pass

    # ------------------------------------------------------------------ 输入处理
    def _accept(self, buffer: Buffer) -> bool:
        text = buffer.text.strip()
        request = self.adapter.pending_ask
        if request is not None:
            # 桥接回答（含确认口令/密钥）一律不写入持久历史文件。
            buffer.reset(document=Document("", 0), append_to_history=False)
            self.adapter.resolve_pending(text)
            return True
        buffer.reset(document=Document("", 0), append_to_history=bool(text))
        if text:
            dispatch(self.ctx, text)
        return True

    def open_overlay(self, float_obj: Float) -> None:
        self.floats.append(float_obj)
        self.adapter.mode = "overlay"
        try:
            self.app.layout.focus(float_obj.content)
        except Exception:
            pass
        self.app.invalidate()

    def close_overlay(self) -> None:
        if self.floats:
            self.floats.pop()
        if self.floats:
            self.adapter.mode = "overlay"
            try:
                self.app.layout.focus(self.floats[-1].content)
            except Exception:
                pass
        else:
            self.adapter.mode = "command"
            try:
                self.app.layout.focus(self.input_buffer)
            except Exception:
                pass
        self.app.invalidate()

    # ------------------------------------------------------------------ 键位
    def _build_keys(self) -> KeyBindings:
        kb = KeyBindings()
        input_focused = Condition(lambda: self._input_focused())
        transcript_focused = Condition(
            lambda: self.app.layout.current_control is self.transcript.control)
        searching = is_searching

        @kb.add("escape")
        def _esc(event) -> None:
            if self.floats:
                self.close_overlay()

        @kb.add("c-f", filter=transcript_focused)
        def _search_cf(event) -> None:
            start_forward_incremental_search(event)

        @kb.add("/", filter=transcript_focused)
        def _search_slash(event) -> None:
            start_forward_incremental_search(event)

        @kb.add("tab", filter=input_focused)
        def _complete(event) -> None:
            self.input_buffer.complete_next()

        @kb.add("c-c")
        def _cancel(event) -> None:
            if searching():
                from prompt_toolkit import search as pt_search
                pt_search.stop_search()
                return
            request = self.adapter.pending_ask
            if request is not None and request.event.is_set() is False:
                self.adapter.resolve_pending(None)
                return
            actives = self.adapter.runner.active_handles()
            if actives:
                latest = actives[-1]
                latest.cancel()
                self.adapter.system_line(f"   ⊘ 已请求取消：{latest.label}")
                return
            self.input_buffer.reset(document=Document("", 0))

        @kb.add("c-g", filter=transcript_focused)
        def _jump_fail(event) -> None:
            index = self.adapter.blocks.last_fail_index()
            if index is None:
                self.adapter.system_line("   · 当前转录没有失败块")
                return
            lines = self.transcript.buffer.text.splitlines()
            offset = sum(len(line) + 1 for line in lines[:index])
            self.transcript.buffer.cursor_position = min(
                offset, len(self.transcript.buffer.text))

        @kb.add("o", filter=transcript_focused)
        def _open_last(event) -> None:
            text = getattr(self.adapter, "last_output_text", "")
            if not text:
                self.adapter.system_line("   · 最近命令没有可展开的输出")
                return
            self.open_overlay(make_viewer_float("最近输出全文", text,
                                                on_close=self.close_overlay))

        @kb.add("f10")
        def _quit(event) -> None:
            self.confirm_quit()

        return kb

    def confirm_quit(self) -> None:
        def _ok() -> None:
            self.app.exit(result=0)

        def _cancel() -> None:
            self.close_overlay()

        self.open_overlay(make_confirm_float("退出 novel-rag 控制台？", "QUIT",
                                             _ok, _cancel))

    def open_procs(self) -> None:
        self.open_overlay(make_procs_float(self.adapter.runner.active_handles,
                                           on_close=self.close_overlay))

    # ------------------------------------------------------------------ 生命周期
    def run(self) -> int:
        ticker = threading.Thread(target=self._tick_loop, name="console-tick",
                                  daemon=True)
        ticker.start()
        try:
            code: int = self.app.run()
        finally:
            self._ticker_stop.set()
            self.adapter.shutdown()
        return int(code or 0)

    def _tick_loop(self) -> None:
        import time
        while not self._ticker_stop.wait(0.5):
            if self.adapter.jobs:
                self.adapter.invalidate()
