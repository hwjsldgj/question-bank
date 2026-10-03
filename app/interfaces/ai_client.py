"""AI（LLM）API 客户端抽象接口（需求 R4 / R10 / R15）。

系统通过本接口完成两类 AI 能力：难度分析与按知识点补题。
接口只约定"提示词进、结构化结果出"，屏蔽具体协议细节。

依赖：无（标准库 typing）
被使用（调用方）：app.application.difficulty_service、
                  app.application.question_generator
被实现（实现方）：app.infrastructure.ai.ai_client.OpenAICompatibleAIClient
"""

from abc import ABC, abstractmethod


class AIClient(ABC):
    """AI API 客户端抽象接口。"""

    @abstractmethod
    def complete(self, prompt: str, response_schema: dict | None = None) -> dict:
        """调用 AI API 完成一次补全并返回结构化结果。

        :param prompt: 完整提示词（由调用方拼装，包含题目内容或生成要求）
        :param response_schema: 期望的 JSON 结构描述；None 表示纯文本响应
        :return: 解析后的 JSON 字典（如 ``{"difficulty": "medium"}``）
        :raises app.domain.errors.AIServiceError: 超时 / 网络失败 / 重试耗尽 /
            返回内容不符合 schema（需求 R4 第 3 条、R15 第 4 条）
        """

    @abstractmethod
    def is_configured(self) -> bool:
        """返回 AI 服务是否已完成有效配置（需求 R15 第 2 条）。

        未配置时调用方应保持库内功能可用并提示未配置。
        """
