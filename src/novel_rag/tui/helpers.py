"""Helper functions for the TUI."""

from __future__ import annotations

import getpass
import json
import os
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from ..documents import read_yaml_mapping
from ..catalog.paths import resolve_timeline_registry_path, resolve_version_map_path
from ..generation import GenerationError
from ..model_api import ModelAPIError, OpenAICompatibleModel
from ..model_config import ModelConfigStore
from ..mutations import SummaryDocument


Input = Callable[[str], str]
Output = Callable[[str], None]


def matches_word(value: str, word: str) -> bool:
    """大小写不敏感地比较用户输入与确认口令。"""

    return value.strip().upper() == str(word).strip().upper()


def confirm_word(input_fn: Input, output: Output, prompt: str, word: str) -> bool:
    """大小写不敏感的危险操作确认；仅当输入与 word 一致时返回 True。"""

    answer = ask(input_fn, f"{prompt}（输入 {word} 确认，其他任意取消）")
    if matches_word(answer, word):
        return True
    output(f"已取消：需要输入 {word} 确认。")
    return False


def suggest_task_id(output_root: Path, story_id: str) -> str:
    """返回 outputs/.workflow/<story_id>/ 下第一个空闲任务 ID。

    优先 ``YYYYMMDD``；被占用时依次尝试 ``YYYYMMDD-2``、``YYYYMMDD-3``……
    """

    from datetime import datetime

    base = datetime.now().strftime("%Y%m%d")
    root = output_root / ".workflow" / story_id
    if not root.is_dir():
        return base
    occupied = {entry.name for entry in root.iterdir()}
    if base not in occupied:
        return base
    index = 2
    while f"{base}-{index}" in occupied:
        index += 1
    return f"{base}-{index}"


def list_summary_documents(root: Path) -> list[SummaryDocument]:
    """按路径排序列出 summaries 目录下全部可解析摘要；解析失败跳过。"""

    rows: list[SummaryDocument] = []
    if not root.is_dir():
        return rows
    for path in sorted((*root.rglob("*.yaml"), *root.rglob("*.yml"))):
        try:
            rows.append(SummaryDocument.from_yaml(path))
        except Exception:
            continue
    return rows


def ask(input_fn: Input, prompt: str, *, default: str = "", required: bool = False) -> str:
    while True:
        value = input_fn(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
        if value:
            return value
        if default:
            return default
        if not required:
            return ""


def number(input_fn: Input, output: Output, prompt: str, *, default: int | None = None,
            minimum: int = 0) -> int | None:
    while True:
        value = ask(input_fn, prompt, default=str(default) if default is not None else "")
        if not value:
            return None
        try:
            number = int(value)
            if number >= minimum:
                return number
        except ValueError:
            pass
        output(f"请输入不小于 {minimum} 的整数。")


def choose(input_fn: Input, output: Output, title: str, values: list[str]) -> str:
    if not values:
        raise GenerationError(f"没有可用的{title}")
    if len(values) == 1:
        output(f"{title}: {values[0]}")
        return values[0]
    output(title + "：")
    for index, value in enumerate(values, 1):
        output(f"  {index}. {value}")
    while True:
        selected = ask(input_fn, "请选择编号", required=True)
        if selected.isdigit() and 1 <= int(selected) <= len(values):
            return values[int(selected) - 1]
        output("无效编号。")


def timeline_ids(library_root: Path, story_id: str) -> list[str]:
    rows = read_yaml_mapping(
        resolve_timeline_registry_path(library_root, story_id, required=False)
    ).get("timelines", [])
    return [str(row["timeline_id"]) for row in rows
            if isinstance(row, dict) and row.get("story_id") == story_id and row.get("timeline_id")]


def reference_texts(value: str) -> list[str]:
    references: list[str] = []
    for item in (part.strip() for part in value.split(";") if part.strip()):
        path = Path(item)
        references.append(path.read_text(encoding="utf-8-sig") if path.is_file() else item)
    return references


def outline_input(value: str) -> Any:
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


def text_preview(text: str, limit: int = 1200) -> str:
    clean = text.strip()
    return clean if len(clean) <= limit else clean[:limit] + "\n……（完整正文见 runtime）"


def dataclass_preview(value: Any) -> str:
    fields = getattr(value, "__dataclass_fields__", {})
    return json.dumps({name: getattr(value, name) for name in fields},
                      ensure_ascii=False, indent=2, default=str)


def latest_runtime(output_root: Path, story_id: str) -> Path | None:
    root = output_root / ".workflow" / story_id
    candidates = [path for path in root.iterdir() if path.is_dir()] if root.is_dir() else []
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def current_family_document(
    library_root: Path,
    story_id: str,
    family: str,
    timeline_id: str | None = None,
) -> str:
    value = read_yaml_mapping(
        resolve_version_map_path(
            library_root,
            story_id,
            timeline_id=timeline_id,
            required=False,
        )
    )
    for row in value.get("versions", []) if isinstance(value.get("versions"), list) else []:
        if isinstance(row, dict) and str(row.get("document_family") or "") == family:
            return str(row.get("current") or "")
    return ""


def show_runtime(path: Path, output: Output) -> None:
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
        output("\n正文预览：\n" + text_preview(text))
    elif (path / "confirmation.json").is_file():
        output("正文已确认并迁移到正式 History。")


def model_from_local_config(input_fn: Input, output: Output, config_path: Path) -> OpenAICompatibleModel:
    store = ModelConfigStore(config_path)
    profile = store.get()
    if profile is not None:
        output(f"使用本地模型配置: {profile.name} ({profile.model})")
        return store.build_model()
    model_name = ask(input_fn, "API 模型", default=os.environ.get("NOVEL_RAG_MODEL", ""), required=True)
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    api_key = os.environ.get("OPENAI_API_KEY")
    if "api.openai.com" in base_url and not api_key:
        raise ModelAPIError("请先设置环境变量 OPENAI_API_KEY")
    return OpenAICompatibleModel(
        base_url=base_url, model=model_name, api_key=api_key,
        mode=os.environ.get("OPENAI_API_MODE", "responses"),
    )


def secret(input_fn: Input, prompt: str) -> str:
    if input_fn is input:
        return getpass.getpass(prompt + ": ").strip()
    return input_fn(prompt + ": ").strip()


def confirm_review(path: Path, output: Output) -> dict[str, Any] | None:
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


def _char_display_width(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1


def display_width(text: str) -> int:
    """按终端显示宽度计算文本宽度：全角/宽字符记 2，其余记 1。"""

    return sum(_char_display_width(char) for char in text)


def pad_display(text: str, width: int) -> str:
    return text + " " * (width - display_width(text))


def truncate_display(text: str, width: int, *, ellipsis: str = "…") -> str:
    """按显示宽度截断文本；超宽时以省略号收尾（省略号计入宽度预算）。"""

    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text
    budget = max(0, width - _char_display_width(ellipsis))
    parts: list[str] = []
    used = 0
    for char in text:
        char_width = _char_display_width(char)
        if used + char_width > budget:
            break
        parts.append(char)
        used += char_width
    return "".join(parts) + ellipsis


def _table_cell(value: Any, *, max_cell: int) -> str:
    text = str(value).replace("\r", "").replace("\n", "↵")
    if display_width(text) <= max_cell:
        return text
    parts: list[str] = []
    used = 0
    for char in text:
        char_width = _char_display_width(char)
        if used + char_width > max_cell - 1:
            break
        parts.append(char)
        used += char_width
    return "".join(parts) + "…"


def _row_value(row: Any, selector: Any) -> Any:
    if callable(selector):
        return selector(row)
    if isinstance(row, Mapping):
        return row.get(selector)
    return getattr(row, str(selector), None)


def render_rows(rows: Sequence[Any], columns: Sequence[tuple[str, Any]], *, max_cell: int = 40) -> str:
    """把任意对象序列渲染成按显示宽度对齐的纯文本表格；空集返回占位提示。"""

    if not rows:
        return "（无记录）"
    headers = [_table_cell(header, max_cell=max_cell) for header, _ in columns]
    body = []
    for row in rows:
        cells = []
        for _, selector in columns:
            value = _row_value(row, selector)
            cells.append(_table_cell("" if value is None else value, max_cell=max_cell))
        body.append(cells)
    widths = [
        max(display_width(headers[column]), *(display_width(cells[column]) for cells in body))
        for column in range(len(columns))
    ]
    lines = ["  ".join(pad_display(headers[index], width) for index, width in enumerate(widths))]
    lines.append("  ".join("-" * width for width in widths))
    for cells in body:
        lines.append("  ".join(pad_display(cell, width) for cell, width in zip(cells, widths)))
    return "\n".join(lines)


def pick_file_from_directory(
    input_fn: Input,
    output: Output,
    *,
    start: Path = Path("."),
    suffixes: frozenset[str] = frozenset({".txt", ".md", ".yaml", ".yml"}),
) -> Path | None:
    """交互式目录文件选择器；子目录在前带 /，回车放弃返回 None。

    数字进入目录或返回文件；``..`` 上级；其余非空文本按用户给定路径处理。
    """

    current = (start if start.is_dir() else Path(".")).resolve()
    lowered = {suffix.lower() for suffix in suffixes}
    while True:
        entries = sorted(current.iterdir(), key=lambda path: path.name.lower())
        options = [entry for entry in entries if entry.is_dir()]
        options += [entry for entry in entries
                    if entry.is_file() and entry.suffix.lower() in lowered]
        output(f"当前目录: {current}")
        for index, entry in enumerate(options, 1):
            label = entry.name + ("/" if entry.is_dir() else "")
            output(f"  {index}. {label}")
        choice = ask(input_fn, "编号选择，.. 返回上级，回车放弃，或直接输入路径")
        if not choice:
            return None
        if choice == "..":
            parent = current.parent
            current = parent if parent != current else current
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            selected = options[int(choice) - 1]
            if selected.is_dir():
                current = selected
                continue
            return selected.resolve()
        candidate = Path(choice)
        if not candidate.exists() and not candidate.is_absolute():
            candidate = current / choice
        if candidate.exists():
            return candidate.resolve()
        output(f"路径不存在: {choice}")

