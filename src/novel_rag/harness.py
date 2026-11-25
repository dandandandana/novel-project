"""固定run的薄stdio/HTTP适配；不持有Store、模型、草稿或第二份记忆。"""
from __future__ import annotations

from copy import deepcopy
from http.client import HTTPException
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .identity import validate_identifier


MAX_MESSAGE_BYTES = 4 * 1024 * 1024
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18")


class BackendError(RuntimeError):
    """后端/传输错误；写操作未知结果保留，不自动重发。"""

    def __init__(self, error: dict):
        """依赖：RuntimeError。输入：结构化错误。输出：带error的异常。实现：不包含token或原始HTTP响应。"""
        self.error = error
        super().__init__(error.get("message", error.get("code", "backend_error")))


class _NoRedirect(HTTPRedirectHandler):
    """本地token不随HTTP重定向离开原后端。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """依赖：urllib redirect handler。输入：重定向响应。输出：None。实现：拒绝跳转，不转发本地token。"""
        return None


class BackendClient:
    """CLI/MCP唯一HTTP连接owner；所有小说副作用仍在已有后端。"""

    def __init__(self, backend: str, *, timeout: float = 30.0):
        """依赖：urllib/URL解析。输入：loopback根URL/超时。输出：无凭证client。实现：固定http本机根，禁代理/重定向，不连接或写文件。"""
        parsed = urlsplit(backend)
        try:
            valid = (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                     and parsed.username is None and parsed.password is None and parsed.path in {"", "/"}
                     and not parsed.query and not parsed.fragment and parsed.port != 0)
        except ValueError:
            valid = False
        if not valid or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("scope_denied: backend必须是有效本机http根URL")
        self.backend, self.timeout = backend.rstrip("/"), timeout
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())
        self._token, self._identity = "", {}

    def _send(self, path: str, payload: dict | None = None, *, authenticated: bool = True) -> dict:
        """依赖：有界urllib响应/JSON。输入：固定API路径与可选POST。输出：JSON或BackendError。实现：一次请求无重试，先提交后失败仍标未知，不泄露响应原文。"""
        headers = {"Accept": "application/json"}
        if authenticated:
            headers["x-workspace-token"] = self._token
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.backend + path, data=data, headers=headers)
        status = 200
        try:
            try:
                response = self._opener.open(request, timeout=self.timeout)
            except HTTPError as exc:
                status, response = exc.code, exc
            with response:
                raw = response.read(MAX_MESSAGE_BYTES + 1)
            if len(raw) > MAX_MESSAGE_BYTES:
                raise ValueError("response_limit")
            body = json.loads(raw.decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("response_shape")
        except (HTTPException, URLError, OSError, UnicodeError, ValueError) as exc:
            code = "backend_network" if isinstance(exc, (URLError, OSError)) else "backend_protocol"
            raise BackendError({"code": code, "message": "后端响应不可确认；读取检查点或用原operation_id恢复",
                                "effects_known": payload is None}) from exc
        if status != 200:
            if status in {401, 403}:
                self._token, self._identity = "", {}
            error = body.get("error")
            if not isinstance(error, dict):
                error = {"code": "backend_protocol", "message": f"后端HTTP {status}"}
            raise BackendError({**error, "effects_known": payload is None, "http_status": status})
        return body

    def request(self, path: str, payload: dict | None = None) -> dict:
        """依赖：无模型握手/_send。输入：API路径/可选POST。输出：原后端结果。实现：token仅内存，过期请求不重发；下次显式请求重新握手。"""
        if not self._token:
            identity = self._send("/api/v1/harness/bootstrap", authenticated=False)
            if not isinstance(identity.get("token"), str) or not identity["token"]:
                raise BackendError({"code": "backend_protocol", "message": "本地握手缺少token", "effects_known": True})
            self._token = identity["token"]
            self._identity = {key: identity.get(key) for key in ("library_root", "workspace_root")}
        return self._send(path, payload)

    @property
    def identity(self) -> dict:
        """依赖：已握手元数据。输入：无。输出：库/工作区路径副本。实现：只返回后端身份，token不暴露给CLI或模型。"""
        return dict(self._identity)

    def run_path(self, run_id: str, suffix: str = "") -> str:
        """依赖：已有validate_identifier。输入：固定run ID/host后缀。输出：API路径。实现：安全身份只在transport组装，不开放给模型替换。"""
        validate_identifier(run_id)
        return "/api/v1/runs/" + run_id + suffix


class ProtocolError(ValueError):
    """MCP请求错误，与小说工具业务错误区分。"""

    def __init__(self, code: int, message: str):
        """依赖：ValueError。输入：JSON-RPC错误号/说明。输出：协议异常。实现：保留结构化错误号。"""
        self.code = code
        super().__init__(message)


class McpStdioAdapter:
    """已声明的2025 MCP profile；同步串行短工具调用，不另造agent loop。"""

    def __init__(self, client: BackendClient, run_id: str):
        """依赖：唯一BackendClient/安全run。输入：client和固定run ID。输出：待初始化adapter。实现：无Store/模型或磁盘状态，EOF不结束任务。"""
        self.client, self.run_id = client, run_id
        self.path = client.run_path(run_id)
        self.context_uri = f"novel://runs/{run_id}/context"
        self.phase, self.version = "new", None
        self._definitions = []

    def _tools(self) -> list[dict]:
        """依赖：后端唯一工具定义。输入：缓存的本次登记。输出：MCP schema。实现：字段映射而不复制业务白名单；写工具仅增加稳定操作元数据。"""
        tools = []
        for definition in self._definitions:
            schema = deepcopy(definition["parameters"])
            writable = definition["name"] in {"save_draft", "remember"}
            if writable:
                schema["properties"]["operation_id"] = {"type": "string", "minLength": 1, "maxLength": 128,
                    "description": "每个新写入意图的稳定ID；丢回执后同ID同参数恢复，不能用网络请求编号。"}
                schema["required"].append("operation_id")
            tools.append({"name": definition["name"], "description": definition["description"], "inputSchema": schema,
                          "annotations": {"readOnlyHint": not writable, "destructiveHint": False,
                                          "idempotentHint": True, "openWorldHint": False}})
        return tools

    def _dispatch(self, method: str, params: dict) -> dict:
        """依赖：MCP profile/固定后端。输入：已校验方法及params。输出：标准result或协议错误。实现：声明能力内转换，模型调用只转发五工具。"""
        if method == "ping":
            return {}
        if method == "initialize":
            if self.phase != "new":
                raise ProtocolError(-32600, "Already initialized")
            if not isinstance(params.get("protocolVersion"), str) or not isinstance(params.get("capabilities"), dict) or not isinstance(params.get("clientInfo"), dict):
                raise ProtocolError(-32602, "Invalid initialize parameters")
            contract = self.client.request(self.path + "/harness-tools")
            self._definitions = contract["tools"]
            self.version = params["protocolVersion"] if params["protocolVersion"] in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            self.phase = "initializing"
            return {"protocolVersion": self.version, "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": "novel_mcp", "version": "0.1.0"},
                    "instructions": "先读取当前任务上下文 " + self.context_uri + "\n" + contract["instructions"]}
        if self.phase != "ready":
            raise ProtocolError(-32600, "Initialize and send notifications/initialized first")
        if method in {"tools/list", "resources/list", "resources/templates/list"}:
            if params.get("cursor") is not None:
                raise ProtocolError(-32602, "No pagination cursor is available")
            if method == "tools/list":
                return {"tools": self._tools()}
            if method == "resources/templates/list":
                return {"resourceTemplates": []}
            return {"resources": [{"uri": self.context_uri, "name": "current_novel_context", "mimeType": "application/json",
                                    "description": "固定任务原纲、边界、当前已保存稿件与真实版本；请显式读取。"}]}
        if method == "resources/read":
            if params.get("uri") != self.context_uri:
                raise ProtocolError(-32602, "Unknown resource")
            context = self.client.request(self.path + "/harness-context?view=model")
            return {"contents": [{"uri": self.context_uri, "mimeType": "application/json", "text": json.dumps(context, ensure_ascii=False)}]}
        if method == "tools/call":
            if set(params) - {"name", "arguments", "_meta"} or not isinstance(params.get("name"), str) or params["name"] not in {item["name"] for item in self._definitions}:
                raise ProtocolError(-32602, "Unknown tool or invalid call parameters")
            arguments = params.get("arguments", {})
            if not isinstance(arguments, dict):
                raise ProtocolError(-32602, "Tool arguments must be an object")
            arguments = dict(arguments)
            if "operation_id" in arguments and params["name"] not in {"save_draft", "remember"}:
                raise ProtocolError(-32602, "operation_id is only declared for write tools")
            operation_id = arguments.pop("operation_id", None)
            try:
                result = self.client.request(self.path + "/harness-tool",
                    {"name": params["name"], "arguments": arguments, "operation_id": operation_id, "delivery": "model"})
            except BackendError as exc:
                result = {"ok": False, "error": exc.error, "operation_id": operation_id}
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                    "structuredContent": result, "isError": result.get("ok") is False}
        raise ProtocolError(-32601, "Method not found")

    def handle(self, message) -> dict | None:
        """依赖：JSON-RPC lifecycle/_dispatch。输入：已解码消息。输出：响应或通知None。实现：校验请求身份，通知不回包，协议与业务错误分开。"""
        request_id = message.get("id") if isinstance(message, dict) else None
        try:
            if (not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str)
                    or not isinstance(message.get("params", {}), dict)
                    or "id" in message and type(request_id) not in {str, int}):
                request_id = None
                raise ProtocolError(-32600, "Invalid Request")
            method, params = message["method"], message.get("params", {})
            if "id" not in message:
                if method == "notifications/initialized" and self.phase == "initializing":
                    self.phase = "ready"
                return None
            return {"jsonrpc": "2.0", "id": request_id, "result": self._dispatch(method, params)}
        except ProtocolError as exc:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": exc.code, "message": str(exc)}}
        except (BackendError, ValueError, KeyError, TypeError) as exc:
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": {"code": -32603, "message": "Backend operation could not be confirmed",
                              "data": exc.error if isinstance(exc, BackendError) else {"code": "backend_protocol"}}}

    def run(self) -> int:
        """依赖：stdin/stdout二进制UTF8。输入：宿主逐行JSON-RPC。输出：退出码/协议响应。实现：有界读取，串行转发，无日志到stdout、无EOF完成或自动POST重试。"""
        incoming, outgoing = sys.stdin.buffer, sys.stdout.buffer
        while True:
            raw = incoming.readline(MAX_MESSAGE_BYTES + 1)
            if not raw:
                return 0
            too_large = len(raw) > MAX_MESSAGE_BYTES
            try:
                if too_large:
                    raise ValueError("message_limit")
                response = self.handle(json.loads(raw.decode("utf-8")))
            except (UnicodeError, ValueError):
                response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error or message limit"}}
            if response is not None:
                outgoing.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
                outgoing.flush()
            if too_large:
                return 1
