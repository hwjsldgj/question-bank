"""AI 客户端读取超时测试：服务端接受连接但不返回 body 时应在 timeout 内失败。

对应需求 R15 第 4 条：单次请求的超时同时约束连接与响应体读取阶段，
避免 AI 服务卡住时 GUI 主线程永久阻塞。

本测试不依赖 PySide6：仅使用 http.server 与 urllib 标准库，
可在无显示环境下跑通。
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.domain.entities.configs import AIConfig
from app.domain.errors import AIServiceError
from app.infrastructure.ai.ai_client import OpenAICompatibleAIClient


#: 响应体读取超时测试的宽松上界（秒）；远大于配置的 2s 超时，
#: 仅用于证明"没有永久阻塞"，不用于校准超时精度。
_READ_TIMEOUT_UPPER_BOUND = 6.0


class HangingHandler(BaseHTTPRequestHandler):
    """接受连接后休眠，永不返回 body（模拟 AI 服务读取阶段卡死）。"""

    def do_POST(self) -> None:
        time.sleep(10)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"choices": [{"message": {"content": "too late"}}]}')

    def log_message(self, *args) -> None:
        pass


class EchoHandler(BaseHTTPRequestHandler):
    """把收到的 prompt 原样作为 AI 回复返回（正常响应路径）。"""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        reply = "pong"
        try:
            payload = json.loads(body)
            reply = (payload.get("messages") or [{}])[-1].get("content", "pong")
        except (ValueError, UnicodeDecodeError, AttributeError):
            pass
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps({"choices": [{"message": {"content": reply}}]}).encode("utf-8")
        )

    def log_message(self, *args) -> None:
        pass


@pytest.fixture(params=[("HangingHandler", HangingHandler), ("EchoHandler", EchoHandler)])
def server(request):
    """在随机端口启动局部 HTTP 服务，yield base_url，结束后关闭。

    参数名随 fixture 暴露给测试，便于区分卡死与正常两种行为。
    """
    name, handler = request.param
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        yield name, base_url
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _client(base_url: str, timeout_ms: int = 2_000) -> OpenAICompatibleAIClient:
    return OpenAICompatibleAIClient(
        AIConfig(
            base_url=base_url,
            api_key="fake",
            model="fake",
            timeout_ms=timeout_ms,
            max_retries=0,
        )
    )


def test_read_timeout_raises(server) -> None:
    """服务端接受连接后不发 body，应在 timeout 内抛出 AIServiceError，而非永久阻塞。"""
    name, base_url = server
    if name != "HangingHandler":
        pytest.skip("仅卡死服务端需要检查超时行为")

    client = _client(base_url)
    start = time.time()
    with pytest.raises(AIServiceError, match="响应体读取超时"):
        client.complete("hello")
    elapsed = time.time() - start
    assert elapsed < _READ_TIMEOUT_UPPER_BOUND, (
        f"应在 {_READ_TIMEOUT_UPPER_BOUND}s 内失败，实际耗时 {elapsed:.2f}s"
    )


def test_normal_response_parsed_as_text(server) -> None:
    """正常响应下，非 JSON 内容走 fallback 返回 {'text': ...}。"""
    name, base_url = server
    if name != "EchoHandler":
        pytest.skip("仅正常服务端需要检查解析行为")

    client = _client(base_url)
    assert client.complete("hello") == {"text": "hello"}


def test_normal_response_parsed_as_json(server) -> None:
    """正常响应下，合法 JSON 内容被解析为字典。"""
    name, base_url = server
    if name != "EchoHandler":
        pytest.skip("仅正常服务端需要检查解析行为")

    client = _client(base_url)
    assert client.complete('{"subject": "数学"}') == {"subject": "数学"}


def test_unconfigured_client_rejects_call() -> None:
    """未配置时不调用网络，直接给出引导提示（需求 R15 第 2 条）。"""
    client = OpenAICompatibleAIClient(AIConfig())
    with pytest.raises(AIServiceError, match="AI 服务未配置"):
        client.complete("hello")