"""难度分析服务：通过 AI API 为题目标注三级难度（需求 R4）。

失败降级策略（需求 R4 第 3 条）：API 调用失败 / 超时 / 返回无效结果时，
题目难度置为 PENDING（待确认），允许出题者手动设置且不被 AI 覆盖。

提示词来自 ConfigStore 的 PromptConfig（用户可在设置界面修改，修改后立即生效）。

依赖（构造注入）：
- app.interfaces.ai_client.AIClient（AI API 客户端抽象）
- app.interfaces.repositories.ConfigStore（提示词配置，可选）

被使用：app.application.question_service（入库触发）、app.container
"""

from app.config.settings import DEFAULT_PROMPT_CONFIG
from app.domain.entities.question import Question
from app.domain.enums import Difficulty, QuestionType
from app.domain.errors import AIServiceError
from app.interfaces.ai_client import AIClient
from app.interfaces.repositories import ConfigStore

from app.application.prompt_utils import load_prompt_config, render

#: AI 返回文本 -> 难度枚举
_DIFFICULTY_WORDS: dict[str, Difficulty] = {
    "easy": Difficulty.EASY,
    "medium": Difficulty.MEDIUM,
    "hard": Difficulty.HARD,
    "易": Difficulty.EASY,
    "中": Difficulty.MEDIUM,
    "难": Difficulty.HARD,
}

_QUESTION_TYPE_TEXT = {
    QuestionType.SINGLE: "单选题",
    QuestionType.MULTIPLE: "多选题",
    QuestionType.SOLUTION: "解答题",
}


class DifficultyService:
    """难度分析服务：唯一的 AI 难度判定入口。"""

    def __init__(self, ai_client: AIClient, config_store: ConfigStore | None = None) -> None:
        """注入 AI 客户端抽象与提示词配置来源。"""
        self._ai_client = ai_client
        self._config_store = config_store

    def analyze(self, question: Question) -> Difficulty:
        """分析单道题目的难度（需求 R4 第 1 条）。

        :raises app.domain.errors.AIServiceError: 调用失败或结果非法
        """
        prompts = load_prompt_config(self._config_store)
        prompt = render(
            prompts.difficulty_prompt,
            DEFAULT_PROMPT_CONFIG.difficulty_prompt,
            type=_QUESTION_TYPE_TEXT.get(question.type, ""),
            stem=question.stem,
            options="；".join(f"{o.key}. {o.text}" for o in question.options) or "无",
            answer="，".join(question.answer) or "无",
        )
        data = self._ai_client.complete(prompt)
        return self._to_difficulty(data)

    def analyze_silent(self, question: Question) -> Difficulty:
        """analyze 的降级包装：任何失败均返回 PENDING 而不抛出异常。

        供题目入库主流程使用，保证 AI 故障不阻塞录入（需求 R4 第 3 条）。
        """
        try:
            return self.analyze(question)
        except Exception:  # noqa: BLE001 - AI 故障不阻塞入库
            return Difficulty.PENDING

    def batch_reanalyze(self, question_ids: list[str]) -> None:
        """对存量题目批量重新分析难度（设计文档预留的开放项，非本期必做）。

        仅分析难度来源为 AI 的题目；人工难度保持不变（需求 R5 第 4 条）。
        """
        raise NotImplementedError("TODO(开放项): 实现存量题批量重分析")

    @staticmethod
    def _to_difficulty(data: dict) -> Difficulty:
        """把 AI 返回的 JSON 转换为难度枚举（非法结果抛 AIServiceError）。"""
        raw = str(data.get("difficulty", "")).strip().lower()
        if raw in _DIFFICULTY_WORDS:
            return _DIFFICULTY_WORDS[raw]
        for word, difficulty in _DIFFICULTY_WORDS.items():
            if word in raw:
                return difficulty
        raise AIServiceError(f"AI 返回的难度无法识别：{data.get('difficulty')!r}")
