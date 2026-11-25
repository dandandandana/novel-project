from __future__ import annotations

import asyncio
import json
import socket
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from email.message import Message
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ModelAPIError(RuntimeError):
    """A safe, user-facing error from a model HTTP endpoint."""


def validate_context_policy(*, context_window_tokens=None, output_reserve_tokens=None,
                            max_turns=None, prompt_cache_key=None, prompt_cache_retention=None,
                            provider_compaction=False) -> None:
    """依赖：纯配置值。输入：显式窗口/预留/轮数及可选端点能力。输出：None或安全配置错误。实现：不猜型号容量，未验收compaction拒绝启用。"""
    for name, value, minimum in (("context_window_tokens", context_window_tokens, 1),
                                 ("output_reserve_tokens", output_reserve_tokens, 0),
                                 ("max_turns", max_turns, 1)):
        if value is not None and (type(value) is not int or value < minimum):
            raise ModelAPIError(f"capability: {name} 必须是显式整数或None")
    if context_window_tokens is not None and output_reserve_tokens is not None and output_reserve_tokens > context_window_tokens:
        raise ModelAPIError("capability: output_reserve_tokens 不能超过context_window_tokens")
    if prompt_cache_key is not None and (not isinstance(prompt_cache_key, str) or not prompt_cache_key.strip()):
        raise ModelAPIError("capability: prompt_cache_key 必须是非空文本或None")
    if prompt_cache_retention is not None and prompt_cache_retention not in ("in_memory", "24h"):
        raise ModelAPIError("capability: prompt_cache_retention 必须是in_memory、24h或None")
    if type(provider_compaction) is not bool or provider_compaction:
        raise ModelAPIError("capability: provider compaction未验收，当前仅支持关闭")


def provider_usage_totals(usages: Iterable[Mapping[str, Any] | None]) -> dict:
    """依赖：provider原usage。输入：原turn用量序列。输出：累计报告值/覆盖数，缺项为None。实现：兼容两协议，cache与净新增只由完整真实报告计算。"""
    values = {name: [] for name in ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens",
                                   "cache_write_tokens", "net_new_input_tokens")}
    for raw in usages:
        usage = raw if isinstance(raw, Mapping) else {}
        incoming = usage.get("input_tokens", usage.get("prompt_tokens"))
        outgoing = usage.get("output_tokens", usage.get("completion_tokens"))
        incoming = incoming if type(incoming) is int and incoming >= 0 else None
        outgoing = outgoing if type(outgoing) is int and outgoing >= 0 else None
        details = usage.get("input_tokens_details", usage.get("prompt_tokens_details"))
        details = details if isinstance(details, Mapping) else {}
        cached = details.get("cached_tokens")
        cached = cached if type(cached) is int and cached >= 0 and (incoming is None or cached <= incoming) else None
        writes = details.get("cache_write_tokens")
        writes = writes if type(writes) is int and writes >= 0 else None
        total = usage.get("total_tokens")
        values["input_tokens"].append(incoming)
        values["output_tokens"].append(outgoing)
        values["total_tokens"].append(total if type(total) is int and total >= 0 else None)
        values["cached_input_tokens"].append(cached)
        values["cache_write_tokens"].append(writes)
        values["net_new_input_tokens"].append(incoming - cached if incoming is not None and cached is not None else None)
    requests = len(values["input_tokens"])
    result = {name: sum(rows) if rows and all(value is not None for value in rows) else None for name, rows in values.items()}
    result.update(requests=requests, reported_requests={name: sum(value is not None for value in rows)
                                                       for name, rows in values.items()},
                  source="provider_reported_usage", scope="cumulative")
    return result


_CONTEXT_CAPACITY_CODES = frozenset({"context_length_exceeded", "max_context_length_exceeded", "context_window_exceeded"})


def _native_error_category(payload: Any, *, fallback: str) -> str:
    """依赖：明确provider错误代码。输入：JSON错误对象与原错误类别。输出：具名类别。实现：只识别已知code/type，忽略自由message和坏类型。"""
    error = payload.get("error", payload) if isinstance(payload, Mapping) else {}
    if isinstance(error, Mapping):
        for name in ("code", "type"):
            value = error.get(name)
            if isinstance(value, str) and value in _CONTEXT_CAPACITY_CODES:
                return "context_limit"
    return fallback


@dataclass(frozen=True)
class ToolCall:
    """provider原调用ID及已完整解析的参数；不执行任何副作用。"""
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelTurn:
    """完整公开响应、原生继续项与用量；隐藏reasoning不作为text。"""
    content_blocks: list[dict]
    text: str
    tool_calls: list[ToolCall]
    finish_reason: str
    continuation: list[dict]
    usage: dict

    def as_dict(self) -> dict:
        """依赖：dataclasses。输入：完整turn。输出：持久化JSON映射。实现：保留真实call_id及continuation，不改写协议身份。"""
        return asdict(self)


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


_MODE_ALIASES = {
    "chat": "chat",
    "completions": "chat",
    "openai-completions": "chat",
    "openai_completions": "chat",
    "responses": "responses",
    "openai-responses": "responses",
    "openai_responses": "responses",
}
DEFAULT_MODE = "chat"


def normalize_mode(value: Any) -> str:
    """归一化模型协议名；空值取默认 ``chat``（OpenAI chat/completions）。

    唯一入口：ModelProfile 存储校验与 OpenAICompatibleModel 运行时校验都经
    此处，别名（completions/openai-completions 等）统一映射到规范值，
    规范值只有 ``chat`` 与 ``responses``。
    """

    text = "" if value is None else str(value).strip().lower().replace(" ", "")
    if not text:
        return DEFAULT_MODE
    canonical = _MODE_ALIASES.get(text)
    if canonical is None:
        known = ", ".join(sorted(set(_MODE_ALIASES)))
        raise ModelAPIError(f"api mode 必须是 {known} 之一")
    return canonical


@dataclass(slots=True)
class OpenAICompatibleModel:
    base_url: str
    model: str
    api_key: str | None = field(default=None, repr=False)
    mode: str = DEFAULT_MODE
    timeout: float = 300.0
    retries: int = 2
    max_output_tokens: int | None = None
    max_response_bytes: int = 8 * 1024 * 1024
    opener: Callable[..., Any] = urlopen
    sleeper: Callable[[float], None] = time.sleep
    context_window_tokens: int | None = None
    output_reserve_tokens: int | None = None
    max_turns: int | None = None
    prompt_cache_key: str | None = field(default=None, repr=False)
    prompt_cache_retention: str | None = None
    provider_compaction: bool = False

    def __post_init__(self) -> None:
        """依赖：normalize_mode/共同policy校验。输入：客户端字段。输出：规范协议或配置错误。实现：保留legacy参数，显式新增策略统一检查。"""
        self.mode = normalize_mode(self.mode)
        if not self.base_url.strip() or not self.model.strip():
            raise ModelAPIError("模型 API 地址和模型名称不能为空")
        if self.timeout <= 0 or self.retries < 0 or self.max_response_bytes <= 0:
            raise ModelAPIError("模型 API timeout、retries 或响应大小配置无效")
        validate_context_policy(context_window_tokens=self.context_window_tokens, output_reserve_tokens=self.output_reserve_tokens,
                                max_turns=self.max_turns, prompt_cache_key=self.prompt_cache_key,
                                prompt_cache_retention=self.prompt_cache_retention, provider_compaction=self.provider_compaction)

    def _body(self, stage: str, payload: dict[str, Any]) -> dict[str, Any]:
        """依赖：旧stage payload与模型配置。输入：v2阶段/数据。输出：chat或responses请求体。实现：保留旧分段适配与输出上限；v3使用独立原生turn装配。"""
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
        body.update(self._cache_parameters())
        return body

    def _cache_parameters(self) -> dict:
        """依赖：显式缓存字段。输入：当前客户端。输出：兼容API参数。实现：None不发送，两种协议与legacy委托同一映射。"""
        return {name: getattr(self, name) for name in ("prompt_cache_key", "prompt_cache_retention")
                if getattr(self, name) is not None}

    async def complete_turn(self, messages: list[dict], tool_definitions: list[dict],
                            limits: dict | None = None, cancel_signal=None, on_text_delta=None) -> ModelTurn:
        """依赖：延迟HTTPX/asyncio/原生codec。输入：会话/五工具/限制/取消/delta回调。输出：完整ModelTurn。实现：网络关闭后归一化，回调await持久化；取消等待清理，不自动重发未知响应。"""
        limits = limits or {}
        if cancel_signal and cancel_signal.is_set():
            raise asyncio.CancelledError()
        manifest = self.request_manifest(messages, tool_definitions, limits)
        if manifest["context_fits"] is False:
            raise ModelAPIError("context_limit: 逻辑请求估算超过显式窗口与输出预留，原输入保留")
        try:
            import httpx
        except ImportError as exc:
            raise ModelAPIError("capability: 请安装 novel-rag[model] 以使用原生工具传输") from exc
        body = self.request_body(messages, tool_definitions, limits)

        async def deliver(text):
            """依赖：generation持久化回调。输入：公开增量。输出：None/具名保存错误。实现：await之后才继续网络，不把保存失败伪装协议错误。"""
            if on_text_delta:
                try:
                    await on_text_delta(text)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    raise ModelAPIError("save_failed: 接收内容保存失败，保留已落盘前缀") from exc

        async def perform():
            """依赖：HTTPX资源上下文。输入：闭包固定请求。输出：turn。实现：有界读取原生JSON/SSE，公开增量先交host回调。"""
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = "Bearer " + self.api_key
            streamed_text, blocks, calls, usage, final, finish, total = "", [], {}, {}, None, None, 0
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                async with client.stream("POST", _endpoint(self.base_url, self.mode), json=body, headers=headers) as response:
                    if response.status_code >= 400:
                        fallback = "capability" if response.status_code in {400, 404, 422} else "model_network"
                        raw_error = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw_error.extend(chunk)
                            if len(raw_error) > self.max_response_bytes:
                                break
                        try:
                            error = json.loads(raw_error) if len(raw_error) <= self.max_response_bytes else None
                        except (ValueError, UnicodeError):
                            error = None
                        code = _native_error_category(error, fallback=fallback)
                        raise ModelAPIError(f"{code}: 模型端点HTTP {response.status_code}")
                    if "text/event-stream" not in response.headers.get("content-type", ""):
                        raw = await response.aread()
                        if len(raw) > self.max_response_bytes:
                            raise ModelAPIError("model_protocol: 响应过大")
                        turn = _decode_native_turn(json.loads(raw.decode("utf-8")), self.mode)
                        if turn.text:
                            await deliver(turn.text)
                        return turn
                    async for line in response.aiter_lines():
                        total += len(line.encode("utf-8"))
                        if total > self.max_response_bytes:
                            raise ModelAPIError("model_protocol: 响应过大")
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        if not data:
                            continue
                        event = json.loads(data)
                        delta = ""
                        if self.mode == "chat":
                            usage = event.get("usage") or usage
                            for choice in event.get("choices", []):
                                if choice.get("index", 0) != 0:
                                    continue
                                change = choice.get("delta", {})
                                delta += _content_text(change.get("content", ""))
                                for item in change.get("tool_calls", []):
                                    index = item["index"]
                                    if index not in calls:
                                        calls[index] = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                                        blocks.append({"type": "tool_call", "index": index})
                                    call = calls[index]
                                    if item.get("id"):
                                        call["id"] = item["id"]
                                    for key in ("name", "arguments"):
                                        call["function"][key] += item.get("function", {}).get(key) or ""
                                finish = choice.get("finish_reason") or finish
                        else:
                            if event.get("type") == "response.output_text.delta":
                                delta = event["delta"]
                            elif event.get("type") in {"response.completed", "response.incomplete"}:
                                final = event["response"]
                            elif event.get("type") in {"error", "response.failed"}:
                                code = _native_error_category(event.get("response", event), fallback="model_protocol")
                                raise ModelAPIError(f"{code}: provider响应失败")
                        if delta:
                            streamed_text += delta
                            blocks.append({"type": "text", "text": delta})
                            await deliver(delta)
            if self.mode == "chat":
                if not finish:
                    raise ModelAPIError("model_protocol: 流未完整结束，保留partial")
                final = {"choices": [{"message": {"role": "assistant", "content": streamed_text,
                                                   "tool_calls": [calls[key] for key in sorted(calls)]},
                                      "finish_reason": finish}], "usage": usage}
            if final is None:
                raise ModelAPIError("model_protocol: 流未完整结束，保留partial")
            turn = _decode_native_turn(final, self.mode)
            if turn.text != streamed_text:
                raise ModelAPIError("model_protocol: 公开增量与终稿不一致，保留partial")
            if self.mode == "chat":
                for block in blocks:
                    if block["type"] == "tool_call":
                        original = calls[block.pop("index")]
                        block.update(call_id=original["id"], name=original["function"]["name"])
            return ModelTurn(blocks if self.mode == "chat" else turn.content_blocks,
                             turn.text, turn.tool_calls, turn.finish_reason, turn.continuation, turn.usage)

        task = asyncio.create_task(perform())
        cancelled = asyncio.create_task(cancel_signal.wait()) if cancel_signal else None
        try:
            if cancelled:
                done, _ = await asyncio.wait({task, cancelled}, return_when=asyncio.FIRST_COMPLETED)
                if cancelled in done:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise asyncio.CancelledError()
            return await task
        except (json.JSONDecodeError, UnicodeError, KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ModelAPIError):
                raise
            raise ModelAPIError("model_protocol: 原生响应结构错误，保留partial") from exc
        except httpx.HTTPError as exc:
            raise ModelAPIError("model_network: 连接失败，保留已接收内容") from exc
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if cancelled:
                cancelled.cancel()
                await asyncio.gather(cancelled, return_exceptions=True)

    def request_body(self, messages: list[dict], definitions: list[dict], limits: dict | None = None) -> dict:
        """依赖：既有mode/显式缓存参数。输入：原会话/工具定义/输出限制。输出：原生body。实现：只封装协议，不裁continuation、不发送本地容量策略。"""
        limits = limits or {}
        tools = [dict(type="function", **definition) if self.mode == "responses" else
                 {"type": "function", "function": definition} for definition in definitions]
        body = {"model": self.model, "tools": tools, "stream": limits.get("stream", True)}
        body["input" if self.mode == "responses" else "messages"] = messages
        if self.mode == "responses":
            body.update(store=False, include=["reasoning.encrypted_content"])
        maximum = limits.get("max_output_tokens", self.max_output_tokens)
        if maximum:
            body["max_output_tokens" if self.mode == "responses" else "max_tokens"] = maximum
        body.update(self._cache_parameters())
        return body

    def _turn_body(self, messages: list[dict], definitions: list[dict], limits: dict) -> dict:
        """依赖：公共request_body。输入：旧私有入口参数。输出：同一原生body。实现：委托唯一封装，保留兼容调用。"""
        return self.request_body(messages, definitions, limits)

    def request_manifest(self, messages: list[dict], definitions: list[dict], limits: dict | None = None) -> dict:
        """依赖：request_body/json_text/estimate_tokens。输入：原会话/工具/限制。输出：无全文或凭证的JSON计量。实现：标逻辑估算，窗口/预留任一未知时不猜剩余容量。"""
        from .std.serialization import json_text
        from .retrieval.assembler import estimate_tokens

        body = self.request_body(messages, definitions, limits)
        raw = json_text(body)
        estimated = estimate_tokens(raw)
        counts = {}
        for item in messages:
            kind = item.get("type", item.get("role")) if isinstance(item, Mapping) else None
            kind = kind if isinstance(kind, str) and kind in {"system", "developer", "user", "assistant", "tool",
                                                            "message", "reasoning", "function_call", "function_call_output"} else "other"
            counts[kind] = counts.get(kind, 0) + 1
        remaining = (self.context_window_tokens - self.output_reserve_tokens
                     if self.context_window_tokens is not None and self.output_reserve_tokens is not None else None)
        return {"mode": self.mode, "logical_json_bytes": len(raw.encode("utf-8")), "logical_json_characters": len(raw),
                "estimated_tokens": estimated, "measurement": "logical_native_request_json", "wire_bytes": None,
                "token_estimator": "estimate_tokens", "message_type_counts": counts,
                "context_window_tokens": self.context_window_tokens, "output_reserve_tokens": self.output_reserve_tokens,
                "remaining_input_tokens": remaining, "context_fits": estimated <= remaining if remaining is not None else None,
                "policy": {"max_turns": self.max_turns,
                           "max_output_tokens": body.get("max_output_tokens", body.get("max_tokens")),
                           "prompt_cache_key_configured": self.prompt_cache_key is not None,
                           "prompt_cache_retention": self.prompt_cache_retention},
                "capabilities": {"provider_compaction": "unsupported", "provider_compaction_enabled": False,
                                 "prompt_cache_parameters": "explicit_passthrough", "endpoint_verified": False}}

    def followup_messages(self, messages: list[dict], turn: ModelTurn, results: list[dict]) -> list[dict]:
        """依赖：完整turn原provider继续项。输入：会话及按实际call_id配对结果。输出：下一turn会话。实现：保留reasoning/原调用，结果原生封装，循环仍由generation拥有。"""
        new = list(messages) + turn.continuation
        for result in results:
            output = json.dumps(result["result"], ensure_ascii=False)
            new.append({"type": "function_call_output", "call_id": result["call_id"], "output": output}
                       if self.mode == "responses" else
                       {"role": "tool", "tool_call_id": result["call_id"], "content": output})
        return new

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


def _decode_native_turn(payload: dict, mode: str) -> ModelTurn:
    """依赖：原生JSON/ToolCall。输入：完整provider响应/协议。输出：规范turn。实现：只提公开text、保留有序块/真实调用ID/必要继续项，未完整参数拒绝。"""
    blocks, calls, texts = [], [], []
    if mode == "chat":
        choice = payload["choices"][0]
        message = choice["message"]
        text = _content_text(message.get("content", ""))
        if text:
            texts.append(text)
            blocks.append({"type": "text", "text": text})
        raw_calls = message.get("tool_calls", [])
        raw_calls = [{"call_id": item["id"], "name": item["function"]["name"], "arguments": item["function"]["arguments"]}
                     for item in raw_calls]
        continuation = [dict(message, role="assistant")]
        finish = choice.get("finish_reason") or "stop"
    else:
        if payload.get("status") == "failed" or payload.get("error"):
            code = _native_error_category(payload, fallback="model_protocol")
            raise ModelAPIError(f"{code}: provider响应失败")
        continuation = payload.get("output", [])
        if any(isinstance(item, Mapping) and item.get("type") == "compaction" for item in continuation):
            raise ModelAPIError("capability: provider compaction未验收，不作为正文交付")
        raw_calls = []
        for item in continuation:
            if item["type"] == "function_call":
                raw_calls.append(item)
                blocks.append({"type": "tool_call", "call_id": item["call_id"], "name": item["name"]})
            elif item["type"] == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        texts.append(part["text"])
                        blocks.append({"type": "text", "text": part["text"]})
        finish = "length" if payload.get("status") == "incomplete" else "tool_calls" if raw_calls else "stop"
    for item in raw_calls:
        arguments = json.loads(item["arguments"])
        if not isinstance(arguments, dict) or not item["call_id"] or not item["name"]:
            raise ModelAPIError("model_protocol: 工具调用ID/完整参数缺失")
        calls.append(ToolCall(item["call_id"], item["name"], arguments))
        if mode == "chat":
            blocks.append({"type": "tool_call", "call_id": item["call_id"], "name": item["name"]})
    if len({call.call_id for call in calls}) != len(calls):
        raise ModelAPIError("model_protocol: 同turn调用ID重复")
    return ModelTurn(blocks, "".join(texts), calls, finish, continuation, payload.get("usage") or {})
