"""Helper functions for the TUI."""

from __future__ import annotations

import getpass
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from ..documents import read_yaml_mapping
from ..generation import GenerationError
from ..layout import story_root
from ..model_api import ModelAPIError, OpenAICompatibleModel
from ..model_config import ModelConfigStore


Input = Callable[[str], str]
Output = Callable[[str], None]


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
    rows = read_yaml_mapping(story_root(library_root, story_id) / "registry" / "timelines.yaml").get("timelines", [])
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


def current_family_document(library_root: Path, story_id: str, family: str) -> str:
    value = read_yaml_mapping(story_root(library_root, story_id) / "registry" / "version-map.yaml")
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