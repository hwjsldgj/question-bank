"""云端 AI 客户端接口定义。"""
from abc import ABC, abstractmethod

class AIClient(ABC):
    """云端 AI API 客户端抽象接口（支持 OpenAI 兼容格式）。"""

    @abstractmethod
    def complete(self, prompt: str, response_schema: dict | None = None) -> dict:
        """发送 Prompt 并获取结构化返回。

        :param prompt: 输入的提示词
        :param response_schema: 期望的 JSON Schema（可选，用于约束输出）
        :return: 解析后的字典
        :raises AIServiceError: 网络失败 / 超时 / 返回格式不合规
        """
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """检查 API Key、Base URL 和模型名称是否已配置。"""
        pass
