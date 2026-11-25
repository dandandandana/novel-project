"""Interactive prompt session with graceful standard-library fallback.

prompt_toolkit 是可选的 TUI extra；缺失或非交互终端时回落到裸
``input``/``print``，因此 ``run_tui`` 的注入契约（测试传入自定义
input_fn）不受影响。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

from .helpers import Input, Output

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import PathCompleter, WordCompleter
    from prompt_toolkit.history import FileHistory

    _PROMPT_TOOLKIT_AVAILABLE = True
except Exception:  # pragma: no cover - exercised via the plain fallback
    _PROMPT_TOOLKIT_AVAILABLE = False


_HISTORY_PATH = Path.home() / ".novel-rag" / "tui-history"
_PATH_PROMPT_HINTS = ("路径", "文件", "目录", "runtime", "YAML")


def prompt_toolkit_available() -> bool:
    return _PROMPT_TOOLKIT_AVAILABLE


def stdin_is_interactive() -> bool:
    """公开版 tty 探测：console 与 plain 会话共用。"""

    return _stdin_is_interactive()


def _stdin_is_interactive() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:
        return False


def _default_history_path() -> Path:
    return _HISTORY_PATH


class _CompleterRouter:
    """按提问文本路由补全器：路径类用文件补全，其余可用候选词。"""

    def __init__(self, candidates_provider: Callable[[], list[str]] | None = None) -> None:
        self._path_completer = PathCompleter(expanduser=True)
        self._candidates_provider = candidates_provider

    def completer_for(self, prompt: str) -> Any | None:
        if any(hint in prompt for hint in _PATH_PROMPT_HINTS):
            return self._path_completer
        provider = self._candidates_provider
        words = provider() if provider is not None else []
        return WordCompleter([str(word) for word in words], ignore_case=True) if words else None


def create_interactive_io(
    *,
    mode: str = "auto",
    history_path: Path | None = None,
    candidates_provider: Callable[[], list[str]] | None = None,
    session_factory: Callable[[Path], Any] | None = None,
) -> tuple[Input, Output]:
    """返回供 run_tui 使用的 ``(input_fn, output_fn)``。

    ``mode``：``auto`` 在已安装 prompt_toolkit 且标准输入为 tty 时启用会话，
    否则与 ``plain`` 一样返回内建 ``(input, print)``。
    ``session_factory(history_path)`` 仅供测试注入；生产默认构造
    带持久历史的 PromptSession，无控制台等异常一律降级为 plain。
    """

    use_session = mode == "prompt_toolkit" or (
        mode == "auto" and _PROMPT_TOOLKIT_AVAILABLE and _stdin_is_interactive()
    )
    if not use_session:
        return input, print

    router = _CompleterRouter(candidates_provider)
    target = Path(history_path) if history_path is not None else _default_history_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if session_factory is not None:
            session = session_factory(target)
        else:
            session = PromptSession(history=FileHistory(str(target)))
    except Exception:
        return input, print

    def input_fn(prompt: str) -> str:
        return session.prompt(prompt, completer=router.completer_for(prompt))

    def output_fn(message: str) -> None:
        print(message)

    return input_fn, output_fn
