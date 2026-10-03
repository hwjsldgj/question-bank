"""AI 客户端基础设施：OpenAI 兼容 HTTP API 实现。

实现接口：app.interfaces.ai_client.AIClient
依赖：requests（HTTP 访问）、app.domain.entities.configs.AIConfig、
      app.domain.errors.AIServiceError
被使用：app.container（装配给 DifficultyService / QuestionGenerator）

配置来源（需求 R15）：接口地址 / API Key / 模型名称 / 超时 / 重试次数
均由用户在本机设置界面提供，密钥仅存本机 ConfigStore。
HTTP 访问使用 requests 库（见 requirements.txt），在 complete() 实现时引入。
"""

from app.domain.entities.configs import AIConfig
from app.domain.errors import AIConfigMissingError, AIServiceError
from app.interfaces.ai_client import AIClient


class OpenAICompatibleAIClient(AIClient):
    """OpenAI 兼容 AI API 客户端（/chat/completions 协议）。"""

    def __init__(self, config: AIConfig) -> None:
        """注入 AI 配置值对象（请求超时与重试次数取自配置，需求 R15 第 5 条）。"""
        self._config = config

    def complete(self, prompt: str, response_schema: dict | None = None) -> dict:
        """调用 /chat/completions 并解析结构化响应。

        失败语义（需求 R4 第 3 条 / R15 第 4 条）：超时、网络错误、
        非 2xx 响应、重试耗尽、JSON 解析失败均抛出 AIServiceError。
        """
        self._ensure_configured()
        raise NotImplementedError("TODO(R15): 实现 AI API 调用与重试")

    def is_configured(self) -> bool:
        """配置完整性判断（base_url / api_key / model 均非空）。"""
        return self._config.is_configured()

    def _ensure_configured(self) -> None:
        """未配置时抛出 AIConfigMissingError（需求 R15 第 2 条降级依据）。"""
        if not self.is_configured():
            raise AIConfigMissingError("AI 服务未配置，请先在设置中填写 API 信息")
