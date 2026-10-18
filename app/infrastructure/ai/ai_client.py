"""OpenAI 兼容的云端 AI 客户端（纯净版，不包含任何本地推理）。

职责：
- 仅负责云端 HTTP（/chat/completions）调用
- 按 ``AIConfig.max_retries`` 执行重试，全部失败后抛 ``AIServiceError``
- ``response_schema`` 非空时开启 ``response_format: json_object``，要求模型输出 JSON
- 连接阶段与响应体读取阶段都受 ``timeout_ms`` 约束，避免 GUI 主线程永久阻塞
"""

import json
import socket
import urllib.error
import urllib.request
from typing import Callable

from app.domain.entities.configs import AIConfig
from app.domain.errors import AIConfigMissingError, AIServiceError
from app.interfaces.ai_client import AIClient


class OpenAICompatibleAIClient(AIClient):
    """OpenAI 兼容格式的 AI 客户端。"""

    def __init__(self, config_provider: Callable[[], AIConfig] | AIConfig) -> None:
        if callable(config_provider):
            self._config_provider = config_provider
        else:
            self._config_provider = lambda: config_provider

    def is_configured(self) -> bool:
        """检查 AI 配置是否完整。"""
        config = self._config_provider()
        return bool(config.base_url and config.api_key and config.model)

    def _ensure_configured(self, config: AIConfig) -> None:
        """检查配置，缺失则抛出异常。"""
        if not config.base_url or not config.api_key or not config.model:
            raise AIConfigMissingError(
                "AI 服务未配置，请前往设置填写 API 地址、Key 和模型名称。"
            )

    def complete(self, prompt: str, response_schema: dict | None = None) -> dict:
        """发送请求并返回 JSON 字典；失败按 max_retries 重试。"""
        config = self._config_provider()
        self._ensure_configured(config)

        retries = max(0, int(getattr(config, "max_retries", 0) or 0))
        last_error: Exception | None = None
        for _attempt in range(retries + 1):
            try:
                content = self._request(config, prompt, response_schema)
                return self._parse(content, response_schema)
            except AIServiceError as exc:
                last_error = exc

        raise AIServiceError(f"AI 服务调用失败（已重试 {retries} 次）：{last_error}")

    @staticmethod
    def _parse(content: str, response_schema: dict | None) -> dict:
        """把模型回复解析为字典（容忍 ```json 代码块包裹）。"""
        text = (content or "").strip()
        if text.startswith("```json"):
            text = text[len("```json"):].strip()
        elif text.startswith("```"):
            text = text[len("```"):].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}
        if isinstance(parsed, dict):
            return parsed
        return {"data": parsed}

    def _request(self, config: AIConfig, prompt: str, response_schema: dict | None) -> str:
        """执行一次 HTTP 请求，返回模型回复的文本内容。"""
        url = f"{config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        }
        payload: dict = {
            "model": config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }
        if response_schema is not None:
            payload["response_format"] = {"type": "json_object"}

        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        timeout = max(1.0, float(getattr(config, "timeout_ms", 30_000)) / 1000.0)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                try:
                    raw_data = resp.read().decode("utf-8", errors="replace")
                except (socket.timeout, TimeoutError) as exc:
                    raise AIServiceError(
                        f"响应体读取超时（{timeout:g}s），请检查 AI 服务可用性"
                    ) from exc
                parsed = json.loads(raw_data)
                return str(parsed["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:200]
            raise AIServiceError(f"AI 服务返回 HTTP {exc.code}：{body}") from exc
        except urllib.error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), (socket.timeout, TimeoutError)):
                raise AIServiceError(f"连接超时（{timeout:g}s）") from exc
            raise AIServiceError(f"网络请求失败：{exc.reason}") from exc
        except AIServiceError:
            raise
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AIServiceError(f"AI 服务响应格式非法：{exc}") from exc
        except Exception as exc:  # noqa: BLE001 - 兜底转译
            raise AIServiceError(f"AI 调用失败：{exc}") from exc