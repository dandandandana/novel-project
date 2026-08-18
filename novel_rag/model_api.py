from __future__ import annotations

import json
import socket
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from email.message import Message
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ModelAPIError(RuntimeError):
    """A safe, user-facing error from a model HTTP endpoint."""


_JSON_STAGES = {
    "normalize",
    "reference_profile",
    "derive_result",
    "polish",
    "validate",
    "repair",
}


def _endpoint(base_url: str, mode: str) -> str:
    base = base_url.rstrip("/")
    suffix = "/responses" if mode == "responses" else "/chat/completions"
    if base.endswith(suffix):
        return base
    return base + suffix


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _response_text(payload: Mapping[str, Any], mode: str) -> str:
    if mode == "responses":
        direct = payload.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct
        parts: list[str] = []
        for output in payload.get("output", []) if isinstance(payload.get("output"), list) else []:
            if not isinstance(output, Mapping):
                continue
            for content in output.get("content", []) if isinstance(output.get("content"), list) else []:
                if isinstance(content, Mapping) and content.get("type") in {"output_text", "text"}:
                    text = content.get("text")
                    if isinstance(text, str):
                        parts.append(text)
        if parts:
            return "".join(parts)
    else:
        choices = payload.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
            message = choices[0].get("message")
            if isinstance(message, Mapping):
                text = _content_text(message.get("content"))
                if text:
                    return text
            text = choices[0].get("text")
            if isinstance(text, str) and text:
                return text
    raise ModelAPIError("模型 API 响应中没有可用文本")


def _model_value(text: str) -> str | Mapping[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        first_newline = stripped.find("\n")
        if first_newline >= 0:
            stripped = stripped[first_newline + 1:-3].strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if isinstance(value, Mapping):
        return value
    raise ModelAPIError("模型返回的 JSON 必须是对象，不能是数组、null 或标量")


def _retry_after(headers: Message | Mapping[str, str] | None, attempt: int) -> float:
    value = headers.get("Retry-After") if headers is not None else None
    try:
        return min(max(float(value), 0.0), 10.0) if value is not None else min(0.5 * 2 ** attempt, 4.0)
    except (TypeError, ValueError):
        return min(0.5 * 2 ** attempt, 4.0)


@dataclass(slots=True)
class OpenAICompatibleModel:
    base_url: str
    model: str
    api_key: str | None = field(default=None, repr=False)
    mode: str = "responses"
    timeout: float = 300.0
    retries: int = 2
    max_output_tokens: int | None = None
    max_response_bytes: int = 8 * 1024 * 1024
    opener: Callable[..., Any] = urlopen
    sleeper: Callable[[float], None] = time.sleep

    def __post_init__(self) -> None:
        if self.mode not in {"responses", "chat"}:
            raise ModelAPIError("api mode 必须是 responses 或 chat")
        if not self.base_url.strip() or not self.model.strip():
            raise ModelAPIError("模型 API 地址和模型名称不能为空")
        if self.timeout <= 0 or self.retries < 0 or self.max_response_bytes <= 0:
            raise ModelAPIError("模型 API timeout、retries 或响应大小配置无效")

    def _body(self, stage: str, payload: dict[str, Any]) -> dict[str, Any]:
        instruction = str(payload.get("instruction") or "")
        request_text = json.dumps(
            {"stage": stage, "payload": payload}, ensure_ascii=False, separators=(",", ":")
        )
        if self.mode == "responses":
            body: dict[str, Any] = {
                "model": self.model,
                "instructions": instruction,
                "input": request_text,
            }
            if self.max_output_tokens is not None:
                body["max_output_tokens"] = self.max_output_tokens
        else:
            body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": request_text},
                ],
                "stream": False,
            }
            if self.max_output_tokens is not None:
                body["max_tokens"] = self.max_output_tokens
            if stage in _JSON_STAGES:
                body["response_format"] = {"type": "json_object"}
        return body

    def __call__(self, stage: str, payload: dict[str, Any]) -> str | Mapping[str, Any]:
        encoded = json.dumps(self._body(stage, payload), ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(_endpoint(self.base_url, self.mode), data=encoded, headers=headers, method="POST")

        for attempt in range(self.retries + 1):
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    raw = response.read(self.max_response_bytes + 1)
                    if len(raw) > self.max_response_bytes:
                        raise ModelAPIError("模型 API 响应过大")
                    try:
                        outer = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise ModelAPIError("模型 API 返回了无效 JSON") from exc
                    if not isinstance(outer, Mapping):
                        raise ModelAPIError("模型 API 外层响应必须是 JSON 对象")
                    return _model_value(_response_text(outer, self.mode))
            except HTTPError as exc:
                retryable = exc.code in {408, 409, 429} or 500 <= exc.code < 600
                if not retryable or attempt >= self.retries:
                    raise ModelAPIError(f"模型 API 请求失败（HTTP {exc.code}，stage={stage}）") from exc
                self.sleeper(_retry_after(exc.headers, attempt))
            except (URLError, TimeoutError, socket.timeout) as exc:
                if attempt >= self.retries:
                    raise ModelAPIError(f"模型 API 连接失败（stage={stage}）") from exc
                self.sleeper(_retry_after(None, attempt))
        raise ModelAPIError(f"模型 API 请求失败（stage={stage}）")
