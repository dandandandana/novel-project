"""Console TUI 入口：能力探测 → 组装 → 运行；任何失败降级返回 None。"""

from __future__ import annotations

import sys
from pathlib import Path

from ...documents import registered_story_ids
from ...model_config import ModelConfigStore, default_config_path
from ..session import prompt_toolkit_available, stdin_is_interactive
from .adapter import ConsoleAdapter
from .app import ConsoleApp
from .commands import ConsoleContext
from .config import DEFAULT_CONFIG_PATH, load_ui_config

_HISTORY_PATH = Path.home() / ".novel-rag" / "console-history"


def run_console(library_root: Path, index_root: Path | None = None, *,
                model_config_path: Path | None = None) -> int | None:
    """运行全屏控制台；不可用或内部失败时返回 None，调用方回落 plain 菜单。"""

    if not prompt_toolkit_available() or not stdin_is_interactive():
        return None
    if not sys.stdin or not sys.stdout:
        return None
    library_root = Path(library_root).resolve()
    index_root = (Path(index_root) if index_root else library_root / "index").resolve()
    config_path = Path(model_config_path).expanduser() if model_config_path \
        else default_config_path()

    try:
        return _launch(library_root, index_root, config_path)
    except Exception as exc:  # noqa: BLE001 - UI 层任何异常都降级到 plain
        print(f"控制台启动失败（{exc}），回落经典菜单。")
        return None


def _launch(library_root: Path, index_root: Path,
            model_config_path: Path) -> int | None:
    config, warnings = load_ui_config()
    adapter = ConsoleAdapter(config)
    context = ConsoleContext(
        library_root=library_root,
        index_root=index_root,
        output_root=library_root.parent / "outputs",
        model_config_path=model_config_path,
        adapter=adapter,
        story_id=_default_story(library_root),
        timeline_id="main",
    )
    app = ConsoleApp(context, adapter, config, history_path=_HISTORY_PATH)
    context.bind_ui(open_overlay=app.open_overlay,
                    close_overlay=app.close_overlay,
                    quit_app=app.confirm_quit)
    profile = None
    try:
        current = ModelConfigStore(model_config_path).get()
        profile = current.name if current is not None else None
    except Exception:
        profile = None
    adapter.set_workspace(
        library_root=str(library_root), index_root=str(index_root),
        story_id=context.story_id or None, timeline_id=context.timeline_id,
        model_profile=profile)
    for warning in warnings:
        adapter.system_line(f"⚠ {warning}")
    adapter.system_line("novel-rag 控制台已就绪 · help 查看动词 · :q 退出")
    return app.run()


def _default_story(library_root: Path) -> str | None:
    try:
        stories = sorted(registered_story_ids(library_root))
    except Exception:
        return None
    return stories[0] if stories else None


__all__ = ["run_console", "DEFAULT_CONFIG_PATH"]
