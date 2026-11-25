"""标准库原生模型 HTTP fixture；只服务本地测试，不记录认证头。"""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time
from typing import Any, Iterator
from urllib.request import urlopen


# WHATWG Fetch Standard §2.9, https://fetch.spec.whatwg.org/#bad-port.
FETCH_BAD_PORTS = frozenset({
    0, 1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53,
    69, 77, 79, 87, 95, 101, 102, 103, 104, 109, 110, 111, 113, 115, 117,
    119, 123, 135, 137, 139, 143, 161, 179, 389, 427, 465, 512, 513, 514,
    515, 526, 530, 531, 532, 540, 548, 554, 556, 563, 587, 601, 636, 989,
    990, 993, 995, 1719, 1720, 1723, 2049, 3659, 4045, 4190, 5060, 5061,
    6000, 6566, 6665, 6666, 6667, 6668, 6669, 6679, 6697, 10080,
})


@contextmanager
def workspace_server(app, timeout: float = 8.0) -> Iterator[str]:
    """启动使用真实loopback listener的测试工作区服务。

    依赖：Uvicorn、loopback socket、Fetch bad-port集合及无模型harness握手。
    输入：实际ASGI app和readiness等待秒数。
    输出：监听中的HTTP base URL；端口无效或服务未ready时抛出RuntimeError。
    实现：最多绑定32次随机端口，关闭Fetch禁用端口并保留最终同一socket给Uvicorn，退出时停止服务并join。
    """
    import uvicorn
    listener = None
    port = None
    for _ in range(32):
        candidate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            candidate.bind(("127.0.0.1", 0))
        except BaseException:
            try:
                candidate.close()
            except BaseException:
                pass
            raise
        candidate_port = candidate.getsockname()[1]
        if candidate_port in FETCH_BAD_PORTS:
            candidate.close()
            continue
        listener = candidate
        port = candidate_port
        break
    if listener is None or port is None:
        raise RuntimeError("无法在32次随机绑定内取得非Fetch禁用端口")
    listener.listen(128)
    listener.setblocking(False)
    base_url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                         log_level="error", access_log=False, lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]},
                              name="v3-workspace-uvicorn", daemon=True)
    thread.start()
    last_error = None
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not thread.is_alive():
                raise RuntimeError("Uvicorn线程在readiness前退出") from last_error
            if server.started:
                try:
                    with urlopen(base_url + "/api/v1/harness/bootstrap", timeout=0.5) as response:
                        body = json.loads(response.read().decode("utf-8"))
                    if response.status == 200 and isinstance(body.get("token"), str):
                        break
                except (OSError, ValueError) as exc:
                    last_error = exc
            threading.Event().wait(0.025)
        else:
            raise RuntimeError(f"Uvicorn workspace未ready：{last_error}")
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            server.force_exit = True
            thread.join(timeout=3)
        listener.close()
        if thread.is_alive():
            raise RuntimeError("测试拥有的Uvicorn线程未退出")


class NativeEndpoint:
    """可脚本化的本地 chat/responses 端点。

    依赖：标准库 HTTPServer、线程与 JSON。
    输入：依次返回的 JSON 或 SSE 脚本。
    输出：随机 localhost 地址、实际请求记录及可观察服务线程。
    实现：请求按 path 记录；SSE 用逐字节 HTTP chunk 暴露 UTF-8 边界。
    """

    def __init__(self, scripts: list[dict[str, Any]], *, barrier_timeout: float = 3.0):
        """依赖：ThreadingHTTPServer 与测试响应脚本。
        输入：有序脚本及有限 barrier 等待秒数。
        输出：尚未启动的 fixture。
        实现：保留脚本队列、请求记录和线程同步状态。
        """
        self.scripts = list(scripts)
        self.barrier_timeout = barrier_timeout
        self.requests: list[dict[str, Any]] = []
        self.callback_errors: list[Exception] = []
        self.request_threads: list[threading.Thread] = []
        self._lock = threading.RLock()
        self._request_condition = threading.Condition(self._lock)
        self._script_index = 0
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.base_url: str | None = None

    def __enter__(self) -> NativeEndpoint:
        """依赖：ThreadingHTTPServer。
        输入：构造时保存的脚本。
        输出：已启动并绑定随机端口的端点。
        实现：创建安静 handler 并启动 daemon serve 线程。
        """
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            """把一次 POST 对应到 fixture 中的下一个响应脚本。"""

            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:
                """依赖：端点脚本和 HTTP/1.1。
                输入：实际 POST path 与 JSON 请求体。
                输出：脚本指定的 JSON 或 SSE 响应。
                实现：先去掉认证头后记录请求，再消费一个脚本并发送响应。
                """
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                except (ValueError, UnicodeError, json.JSONDecodeError):
                    self.send_error(400)
                    return

                request = endpoint._record_request(self.path, body, threading.current_thread())
                script = endpoint._next_script()
                if script is None:
                    self.send_error(500, "fixture response script exhausted")
                    return

                callback = script.get("callback")
                if callback is not None:
                    try:
                        if not callable(callback):
                            raise TypeError("fixture callback must be callable")
                        dynamic = callback(request)
                        if not isinstance(dynamic, dict):
                            raise TypeError("fixture callback must return a response script")
                        script = {**script, **dynamic}
                    except Exception as exc:
                        endpoint._record_callback_error(exc)
                        self.send_error(500, "fixture callback failed")
                        return

                mode = script.get("mode")
                expected_suffix = "/responses" if mode == "responses" else "/chat/completions"
                if mode and not self.path.endswith(expected_suffix):
                    self.send_error(409, "fixture mode does not match request path")
                    return

                header_gate = script.get("wait_headers")
                if header_gate is not None:
                    waiting_notice = script.get("headers_waiting")
                    if isinstance(waiting_notice, threading.Event):
                        waiting_notice.set()
                    if not header_gate.wait(endpoint.barrier_timeout):
                        self.send_error(504, "fixture header barrier timed out")
                        return

                if "frames" in script:
                    self._send_frames(script["frames"], script.get("after_first"), script.get("first_frame_sent"))
                else:
                    self._send_json(script.get("json", {}))

            def _send_json(self, value: dict[str, Any]) -> None:
                """依赖：JSON encoder 与 HTTP response writer。
                输入：独立手写的 provider-shaped JSON 值。
                输出：一条有 Content-Length 的 JSON 响应。
                实现：UTF-8 编码后一次写入，不记录响应或认证信息。
                """
                data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    # Cancellation before response completion closes the client socket.
                    return

            def _send_frames(self, frames: list[dict[str, Any] | str], after_first: threading.Event | None,
                             first_frame_sent: threading.Event | None) -> None:
                """依赖：SSE data framing 与 HTTP chunked transfer。
                输入：响应事件列表、可选首帧后 barrier 和首帧已发送通知。
                输出：可逐字节拆分的 event-stream。
                实现：逐字节发送 UTF-8；首帧后先通知测试，再进入有限 barrier。
                """
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Transfer-Encoding", "chunked")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    for index, frame in enumerate(frames):
                        if frame == "[DONE]":
                            payload = b"data: [DONE]\n\n"
                        else:
                            encoded = json.dumps(frame, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                            payload = b"data: " + encoded + b"\n\n"
                        self._write_split_chunk(payload)
                        if index == 0:
                            if first_frame_sent is not None:
                                first_frame_sent.set()
                            if after_first is not None:
                                after_first.wait(endpoint.barrier_timeout)
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    # A cancelled client is expected to close the active response.
                    return

            def _write_split_chunk(self, payload: bytes) -> None:
                """依赖：HTTP/1.1 chunk framing。
                输入：完整 SSE frame 字节。
                输出：同一字节流的单字节 transfer chunks。
                实现：保留 UTF-8 字节顺序并在 frame 尾部 flush。
                """
                for byte in payload:
                    self.wfile.write(b"1\r\n" + bytes((byte,)) + b"\r\n")
                self.wfile.flush()

            def log_message(self, _format: str, *_args: Any) -> None:
                """依赖：BaseHTTPRequestHandler。
                输入：stdlib 默认访问日志参数。
                输出：无。
                实现：禁用日志，避免测试输出请求或认证相关信息。
                """
                return

        class Server(ThreadingHTTPServer):
            """允许请求 handler 在单独 daemon 线程中等待测试 barrier。"""

            daemon_threads = True
            block_on_close = False

        self.server = Server(("127.0.0.1", 0), Handler)
        self.server.native_endpoint = self  # type: ignore[attr-defined]
        port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{port}/v1"
        self.thread = threading.Thread(target=self.server.serve_forever, name="native-endpoint", daemon=True)
        self.thread.start()
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        """依赖：server shutdown 与有限 join。
        输入：with 块退出状态。
        输出：所有本地服务线程停止后的 None。
        实现：先释放脚本 barrier，再关闭监听并有界等待 handler。
        """
        self._release_barriers()
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        deadline = time.monotonic() + self.barrier_timeout
        owned_threads = ([self.thread] if self.thread is not None else []) + list(self.request_threads)
        for thread in owned_threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        alive = [thread.name for thread in owned_threads if thread.is_alive()]
        if alive:
            raise RuntimeError(f"NativeEndpoint owned threads did not stop: {alive}")

    def wait_for_requests(self, count: int, timeout: float = 2.0) -> bool:
        """依赖：请求计数 Condition。
        输入：目标请求数与有限等待秒数。
        输出：达到目标时 True，超时时 False。
        实现：使用单调时钟等待，不轮询或长 sleep。
        """
        deadline = time.monotonic() + timeout
        with self._request_condition:
            while len(self.requests) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._request_condition.wait(remaining)
            return True

    def _record_request(self, path: str, body: dict[str, Any], thread: threading.Thread) -> dict[str, Any]:
        """依赖：线程安全请求记录。
        输入：实际 path、解码 body 和 handler thread。
        输出：无认证头的记录对象并唤醒请求等待方。
        实现：不采集 headers，避免保存 Authorization/API key。
        """
        with self._request_condition:
            request = {"method": "POST", "path": path, "body": body}
            self.requests.append(request)
            self.request_threads.append(thread)
            self._request_condition.notify_all()
            return request

    def _record_callback_error(self, error: Exception) -> None:
        """依赖：fixture callback 错误队列。
        输入：响应构造时发生的异常。
        输出：异常可由测试断言读取。
        实现：仅保存错误对象，不写日志或认证信息。
        """
        with self._lock:
            self.callback_errors.append(error)

    def _next_script(self) -> dict[str, Any] | None:
        """依赖：脚本队列锁。
        输入：无。
        输出：下一个响应脚本或 None。
        实现：按请求到达顺序原子消费脚本。
        """
        with self._lock:
            if self._script_index >= len(self.scripts):
                return None
            script = self.scripts[self._script_index]
            self._script_index += 1
            return script

    def _release_barriers(self) -> None:
        """依赖：脚本中的 threading.Event barrier。
        输入：全部响应脚本。
        输出：无仍阻塞的 header 或首帧 barrier。
        实现：在关闭监听前 set 每个可用 gate。
        """
        for script in self.scripts:
            for name in ("wait_headers", "headers_waiting", "after_first", "first_frame_sent"):
                gate = script.get(name)
                if isinstance(gate, threading.Event):
                    gate.set()
