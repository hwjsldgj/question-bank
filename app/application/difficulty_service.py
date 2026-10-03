"""难度分析服务：通过 AI API 为题目标注三级难度（需求 R4）。

失败降级策略（需求 R4 第 3 条）：API 调用失败 / 超时 / 返回无效结果时，
题目难度置为 PENDING（待确认），允许出题者手动设置且不被 AI 覆盖。

依赖（构造注入）：
- app.interfaces.ai_client.AIClient（AI API 客户端抽象）

被使用：app.application.question_service（入库触发）、
        app.container、app.presentation.views.question_bank_view
"""

from app.domain.entities.question import Question
from app.domain.enums import Difficulty
from app.interfaces.ai_client import AIClient


class DifficultyService:
    """难度分析服务：唯一的 AI 难度判定入口。"""

    def __init__(self, ai_client: AIClient) -> None:
        """注入 AI 客户端抽象。"""
        self._ai_client = ai_client

    def analyze(self, question: Question) -> Difficulty:
        """分析单道题目的难度（需求 R4 第 1 条）。

        :param question: 待分析题目（题干 / 选项 / 答案参与提示词）
        :return: 分析得到的难度（easy / medium / hard）
        :raises app.domain.errors.AIServiceError: 调用失败或结果非法；
            调用方捕获后应将题目难度置为 PENDING
        """
        raise NotImplementedError("TODO(R4): 实现单题难度分析")

    def analyze_silent(self, question: Question) -> Difficulty:
        """analyze 的降级包装：任何失败均返回 PENDING 而不抛出异常。

        供题目入库主流程使用，保证 AI 故障不阻塞录入（需求 R4 第 3 条）。
        """
        raise NotImplementedError("TODO(R4): 实现静默难度分析")

    def batch_reanalyze(self, question_ids: list[str]) -> None:
        """对存量题目批量重新分析难度（设计文档预留的开放项，非本期必做）。

        仅分析难度来源为 AI 的题目；人工难度保持不变（需求 R5 第 4 条）。
        """
        raise NotImplementedError("TODO(开放项): 实现存量题批量重分析")
