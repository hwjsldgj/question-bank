"""AI 客户端基础设施：OpenAI 兼容 HTTP API 实现。

实现接口：app.interfaces.ai_client.AIClient
依赖：标准库 urllib / json（不引入第三方 HTTP 依赖）、
      app.domain.entities.configs.AIConfig、app.domain.errors
被使用：app.container（装配给 DifficultyService / QuestionService / QuestionGenerator）

配置来源（需求 R15）：接口地址 / API Key / 模型名称 / 超时 / 重试次数
均由用户在本机设置界面提供，密钥仅存本机 ConfigStore；构造时传入
"配置提供者"（callable 或 ConfigStore.load_ai_config），保证设置保存后
后续调用立即使用新配置（需求 R15 第 3 条）。
"""

import json
import threading
import urllib.error
import urllib.request
from typing import Callable
from urllib.response import addinfourl

from app.domain.entities.configs import AIConfig
from app.domain.errors import AIConfigMissingError, AIServiceError
from app.interfaces.ai_client import AIClient


class OpenAICompatibleAIClient(AIClient):
    """OpenAI 兼容 AI API 客户端（/chat/completions 协议）。"""

    def __init__(self, config: AIConfig | Callable[[], AIConfig]) -> None:
        """注入 AI 配置或配置提供者（每次调用前重新读取，需求 R15 第 5 条）。"""
        self._provider = config if callable(config) else (lambda: config)

    def complete(self, prompt: str, response_schema: dict | None = None) -> dict:
        """调用 /chat/completions 并解析结构化响应。

        失败语义（需求 R4 第 3 条 / R15 第 4 条）：超时、网络错误、
        非 2xx 响应、重试耗尽、JSON 解析失败均抛出 AIServiceError。
        """
        config = self._provider()
        self._ensure_configured(config)
        last_error: Exception | None = None
        for _attempt in range(max(0, int(config.max_retries)) + 1):
            try:
                content = self._request(config, prompt, response_schema)
                return self._parse(content, response_schema)
            except AIServiceError as exc:
                last_error = exc
            except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
                last_error = AIServiceError(f"AI 服务调用失败：{exc}")
        raise AIServiceError(f"AI 服务调用失败（已重试）：{last_error}")

    def is_configured(self) -> bool:
        """配置完整性判断（base_url / api_key / model 均非空）。"""
        return self._provider().is_configured()

    # ------------------------------------------------------------------ 内部

    def _ensure_configured(self, config: AIConfig) -> None:
        """未配置时抛出 AIConfigMissingError（需求 R15 第 2 条降级依据）。"""
        if not config.is_configured():
            raise AIConfigMissingError("AI 服务未配置，请先在设置中填写 API 信息")

    @staticmethod
    def _request(
        config: AIConfig, prompt: str, response_schema: dict | None
    ) -> str:
        """发起一次 HTTP 请求，返回模型回复的文本内容。

        超时约束（需求 R15 第 4 条）分两阶段，且**不修改全局 socket 默认超时**，
        以免在 GUI 主线程里临时干扰 Qt 事件循环与其他 socket 连接：

        - 连接阶段：交给 ``urllib.request.urlopen(timeout=...)``，超时抛出
          ``URLError``（原因值为 ``socket.timeout``）；
        - 响应体读取阶段：服务端已接受连接却迟迟不返回 body 时，
          ``urlopen`` 的 ``timeout`` 不起作用，会永久阻塞 GUI，因此改为在
          守护线程里读取，主线程用 ``join(timeout)`` 等待，超时后关闭
          socket 并抛出 ``AIServiceError``。
        """
        url = config.base_url.rstrip("/") + "/chat/completions"
        payload: dict = {
            "model": config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }
        if response_schema is not None:
            payload["response_format"] = {"type": "json_object"}
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.api_key}",
            },
        )
        timeout = max(1.0, float(config.timeout_ms) / 1000.0)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = self._read_body(response, timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            raise AIServiceError(f"AI 服务返回 HTTP {exc.code}：{detail}") from exc
        try:
            parsed = json.loads(body)
            return str(parsed["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AIServiceError(f"AI 服务响应格式非法：{exc}") from exc

    @staticmethod
    def _read_body(response: "addinfourl", timeout: float) -> str:
        """在守护线程里读取 body，主线程用 ``join`` 控制读取阶段超时。

        :param response: 已拿到 status / headers 的响应对象
        :param timeout: 读取阶段超时（秒）
        :return: 响应体解码后的文本
        :raises AIServiceError: 读取超时或读取失败
        """
        container: dict[str, object] = {}

        def target() -> None:
            try:
                container["body"] = response.read().decode("utf-8", errors="replace")
            except Exception as exc:  # noqa: BLE001 - 跨线程传递，上层统一归类
                container["error"] = exc

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            # 服务端接受连接后不发 body，关闭 socket 迫使读取端失败并释放资源。
            try:
                response.close()
            except Exception:
                pass
            raise AIServiceError(f"AI 响应体读取超时（{timeout:g}s），请检查 AI 服务可用性")
        if "error" in container:
            raise AIServiceError(f"AI 响应体读取失败：{container['error']}")
        return container["body"]  # type: ignore[no-any-return]

    @staticmethod
    def _parse(content: str, response_schema: dict | None) -> dict:
        """把模型回复解析为字典（容忍 ```json 代码块包裹）。"""
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if "\n" in text:
                text = text.split("\n", 1)[1]
        text = text.strip()
        try:
            data = json.loads(text)
        except ValueError:
            if response_schema is None:
                return {"text": content}
            raise AIServiceError(f"AI 返回内容不是合法 JSON：{content[:200]}")
        if isinstance(data, dict):
            return data
        return {"data": data}
