"""OpenAI 兼容的云端 AI 客户端（纯净版，不包含任何本地推理）。"""
import json
import socket
import urllib.request
import urllib.error
from typing import Callable

from app.domain.entities.configs import AIConfig
from app.domain.errors import AIServiceError, AIConfigMissingError
from app.interfaces.ai_client import AIClient

class OpenAICompatibleAIClient(AIClient):
    """OpenAI 兼容格式的 AI 客户端。"""

    def __init__(self, config_provider: Callable[[], AIConfig] | AIConfig) -> None:
        # 兼容直接传实例，或传一个获取配置的函数
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
            raise AIConfigMissingError("AI 服务未配置，请前往设置填写 API 地址、Key 和模型名称。")

    def complete(self, prompt: str, response_schema: dict | None = None) -> dict:
        """发送请求并返回 JSON 字典。"""
        config = self._config_provider()
        self._ensure_configured(config)
        
        content = self._request(config, prompt, response_schema)
        
        # 尝试解析返回的 JSON
        try:
            # 处理可能的 markdown 代码块包裹
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
                
            return json.loads(content.strip())
        except json.JSONDecodeError:
            # 非 JSON 内容，走 fallback 返回纯文本
            return {"text": content.strip()}

    def _request(self, config: AIConfig, prompt: str, response_schema: dict | None) -> str:
        """执行底层的 HTTP 请求，带异常捕获和错误翻译。"""
        url = f"{config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}"
        }
        payload = {
            "model": config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1
        }
        
        req = urllib.request.Request(
            url, 
            data=json.dumps(payload).encode("utf-8"), 
            headers=headers,
            method="POST"
        )
        
        timeout = getattr(config, "timeout_ms", 60000) / 1000.0
        
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                # 读取阶段可能超时（比如服务端挂起）
                try:
                    raw_data = resp.read().decode("utf-8")
                except socket.timeout as e:
                    raise AIServiceError("响应体读取超时") from e
                
                res_data = json.loads(raw_data)
                return res_data["choices"][0]["message"]["content"]
                
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            raise AIServiceError(f"HTTP {e.code}: {body[:200]}") from e
        except urllib.error.URLError as e:
            if isinstance(e.reason, socket.timeout):
                raise AIServiceError("连接超时") from e
            raise AIServiceError(f"网络请求失败: {e.reason}") from e
        except AIServiceError:
            raise
        except Exception as e:
            raise AIServiceError(f"AI 调用失败: {e}") from e
