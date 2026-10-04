#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fake_ai_server.py —— 本地假 AI 接口（人工手动回复）

仿照 DeepSeek / OpenAI 的 Chat Completions 接口。
收到请求后把对话打印到控制台，由你手动输入 AI 的回复，
再按标准 JSON 格式返回给调用方。非流式，串行处理，无并发。

接口：
    GET  /v1/models
    POST /v1/chat/completions

运行：
    python fake_ai_server.py

默认监听：http://127.0.0.1:8000
Base URL：http://127.0.0.1:8000/v1
API Key：不校验，随便填
"""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "127.0.0.1"
PORT = 8000

_id_counter = 0


def next_id() -> str:
    global _id_counter
    _id_counter += 1
    return f"chatcmpl-fake-{_id_counter:04d}"


def format_message(msg: dict) -> str:
    """把一条 message 转成控制台可读的文本。"""
    role = msg.get("role", "unknown")
    content = msg.get("content", "")

    # 兼容 content 为数组的情况（多模态格式）
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            else:
                parts.append(json.dumps(item, ensure_ascii=False))
        content = "\n".join(parts)

    return f"[{role}] {content}"


def ask_human(messages: list) -> str:
    """打印对话，等待手动输入回复。"""
    print("\n" + "=" * 70)
    for m in messages:
        if isinstance(m, dict):
            print(format_message(m))
        else:
            print(f"[?] {m}")
    print("-" * 70)
    print("请输入 AI 回复（直接回车 = 空回复，输入 /quit 退出服务）：")

    try:
        reply = input("AI 回复 > ")
    except (EOFError, KeyboardInterrupt):
        reply = ""

    if reply.strip() == "/quit":
        raise SystemExit(0)
    return reply


class Handler(BaseHTTPRequestHandler):
    server_version = "FakeAI/1.0"

    # ---------- 工具方法 ----------
    def _send_json(self, obj: dict, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, message: str,
                         err_type: str = "invalid_request_error") -> None:
        self._send_json(
            {"error": {"message": message, "type": err_type, "code": None}},
            status=status,
        )

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def log_message(self, fmt, *args) -> None:
        # 屏蔽默认访问日志，保持控制台干净
        pass

    # ---------- GET ----------
    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/") or "/"

        if path in ("/v1/models", "/models"):
            self._send_json({
                "object": "list",
                "data": [{
                    "id": "deepseek-chat",
                    "object": "model",
                    "created": 0,
                    "owned_by": "human",
                }],
            })
            return

        if path in ("/", "/health"):
            self._send_json({"status": "ok", "service": "fake-ai"})
            return

        self._send_error_json(404, f"未知路径: {self.path}", "not_found")

    # ---------- POST ----------
    def do_POST(self) -> None:
        path = self.path.split("?")[0].rstrip("/")
        if path not in ("/v1/chat/completions", "/chat/completions"):
            self._send_error_json(404, f"未知路径: {self.path}", "not_found")
            return

        try:
            data = self._read_json()
        except (ValueError, UnicodeDecodeError) as exc:
            self._send_error_json(400, f"请求体不是合法 JSON: {exc}")
            return

        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            self._send_error_json(400, "'messages' 必须是非空数组")
            return

        model = data.get("model") or "deepseek-chat"

        # 忽略 stream=true（本服务不支持流式），一律按非流式返回
        content = ask_human(messages)

        self._send_json({
            "id": next_id(),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        })


def main() -> None:
    server = HTTPServer((HOST, PORT), Handler)
    print(f"假 AI 服务已启动： http://{HOST}:{PORT}")
    print(f"Base URL： http://{HOST}:{PORT}/v1")
    print("等待调用…… 按 Ctrl+C 退出，或在提示符输入 /quit 退出\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在退出……")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()