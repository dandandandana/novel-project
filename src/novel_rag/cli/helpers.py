"""Helper functions for CLI argument parsing and model construction."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from pathlib import Path

from ..generation import GenerationError
from ..model_api import OpenAICompatibleModel
from ..model_config import ModelConfigStore


def _paths(args: argparse.Namespace) -> tuple[Path, Path]:
    library = Path(args.library).resolve()
    index = Path(args.index).resolve() if args.index else library / "index"
    return library, index


def _command_model(command: str, timeout: int):
    if timeout <= 0:
        raise GenerationError("model timeout 必须大于 0")
    argv = shlex.split(command, posix=False)
    def call(stage: str, payload: dict):
        try:
            completed = subprocess.run(
                argv, input=json.dumps({"stage": stage, "payload": payload}, ensure_ascii=False),
                text=True, encoding="utf-8", capture_output=True, check=False, timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise GenerationError(f"模型命令超时（{timeout} 秒）") from exc
        except OSError as exc:
            raise GenerationError(f"无法启动模型命令: {exc}") from exc
        if completed.returncode:
            raise GenerationError(completed.stderr.strip() or f"模型命令失败: {completed.returncode}")
        output = completed.stdout.strip()
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return output
    return call


def _model_from_args(args: argparse.Namespace):
    if args.model_command:
        return _command_model(args.model_command, args.model_timeout)
    store = ModelConfigStore(getattr(args, "model_config", None))
    if not args.api_model:
        return store.build_model(getattr(args, "api_profile", None))
    stored = store.get(getattr(args, "api_profile", None))
    no_auth = args.api_no_auth or bool(stored and stored.no_auth)
    api_key = None if no_auth else ((stored.api_key if stored else None) or os.environ.get(args.api_key_env))
    if not api_key and not no_auth:
        raise GenerationError("当前本地模型 profile 没有 API key；请运行 api-config set，"
                              "或对无鉴权本地服务使用 --api-no-auth")
    return OpenAICompatibleModel(
        base_url=args.api_base or (stored.base_url if stored else "https://api.openai.com/v1"),
        model=args.api_model, api_key=api_key,
        mode=args.api_mode or (stored.mode if stored else "responses"),
        timeout=args.model_timeout, retries=args.api_retries,
        max_output_tokens=args.api_max_output_tokens if args.api_max_output_tokens is not None
        else (stored.max_output_tokens if stored else None),
    )


def _add_model_arguments(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group(required=False)
    source.add_argument("--model-command", help="从 stdin 接收 JSON、向 stdout 返回 JSON/正文的模型命令")
    source.add_argument("--api-model", help="OpenAI 兼容 API 的模型名称")
    parser.add_argument("--model-timeout", type=int, default=300, help="单次模型调用超时秒数")
    parser.add_argument("--api-base")
    parser.add_argument("--api-mode", choices=["responses", "chat"],
                        default=None)
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--api-no-auth", action="store_true")
    parser.add_argument("--api-retries", type=int, default=2)
    parser.add_argument("--api-max-output-tokens", type=int)
    parser.add_argument("--api-profile", help="本地 model-api.json 中的 profile；默认使用 active")