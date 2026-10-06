"""难度分析服务：通过 AI API 为题目标注三级难度（需求 R4）。

失败降级策略（需求 R4 第 3 条）：API 调用失败 / 超时 / 返回无效结果时，
题目难度置为 PENDING（待确认），允许出题者手动设置且不被 AI 覆盖。

提示词来自 ConfigStore 的 PromptConfig（用户可在设置界面修改，修改后立即生效）。

依赖（构造注入）：
- app.interfaces.ai_client.AIClient（AI API 客户端抽象）
- app.interfaces.repositories.ConfigStore（提示词配置，可选）

被使用：app.application.question_service（入库触发）、app.container
"""

from app.config.settings import DEFAULT_MODULE_PROMPTS, DIFFICULTY_ANALYSIS_FRAME
from app.domain.entities.question import Question
from app.domain.enums import Difficulty, DifficultySource, QuestionType
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
    QuestionType.FILL: "填空题",
    QuestionType.SOLUTION: "解答题",
}


class DifficultyService:
    """难度分析服务：唯一的 AI 难度判定入口。"""

    def __init__(
        self,
        ai_client: AIClient,
        config_store: ConfigStore | None = None,
        question_repository=None,
        local_classifier=None,
    ) -> None:
        """注入 AI 客户端、提示词配置来源与（可选）题目仓储（批量重分析用）。"""
        self._ai_client = ai_client
        self._config_store = config_store
        self._repository = question_repository
        self._local_classifier = local_classifier

    def analyze(self, question: Question, prefer: str = "auto") -> Difficulty:
        """分析单道题目的难度。

        :param prefer: "auto"（本地优先）/ "ai"（强制走 AI）/ "local"（强制本地）

        提示词 = 固定分析框架 + 用户可编辑的「难度」模块提示词片段：难度只维护
        一处提示词，AI 辨识与难度分析（含批量重析）共用同一段输出要求
        （用户需求：AI 的提示词中难度不要重复）。

        :raises app.domain.errors.AIServiceError: 调用失败或结果非法
        """
        # prefer="ai" 时跳过本地；否则尝试本地
        if prefer != "ai" and self._local_classifier is not None:
            try:
                options_text = " ".join(f"{o.key}. {o.text}" for o in question.options)
                answer_text = " ".join(question.answer)
                result = self._local_classifier.predict(
                    stem=question.stem,
                    options=options_text,
                    answer=answer_text,
                )
                return _DIFFICULTY_WORDS[result]
            except Exception:
                pass

        # prefer="local" 时不允许走远程，直接抛错降级
        if prefer == "local":
            raise AIServiceError("本地模型不可用，无法按 local 优先级分析难度")

        prompts = load_prompt_config(self._config_store)
        default_fragment = DEFAULT_MODULE_PROMPTS.get("difficulty", "")
        fragment = render(
            prompts.module_prompts.get("difficulty") or default_fragment,
            default_fragment,
        )
        prompt = render(
            DIFFICULTY_ANALYSIS_FRAME,
            DIFFICULTY_ANALYSIS_FRAME,
            module=fragment,
            knowledge_points="，".join(question.knowledge_points) or "未标注",
            type=_QUESTION_TYPE_TEXT.get(question.type, ""),
            stem=question.stem,
            options="；".join(f"{o.key}. {o.text}" for o in question.options) or "无",
            answer="，".join(question.answer) or "无",
        )
        data = self._ai_client.complete(prompt)
        return self._to_difficulty(data)

    def analyze_silent(self, question: Question, prefer: str = "auto") -> Difficulty:
        """analyze 的降级包装：任何失败均返回 PENDING 而不抛出异常。

        供题目入库主流程使用，保证 AI 故障不阻塞录入（需求 R4 第 3 条）。
        """
        try:
            return self.analyze(question, prefer=prefer)
        except Exception:  # noqa: BLE001 - AI 故障不阻塞入库
            return Difficulty.PENDING

    def batch_reanalyze(self, question_ids: list[str]) -> dict:
        """对存量题目批量重新分析难度（用户需求：完成题库相关内容）。

        仅分析难度来源为 AI 的题目；人工难度保持不变（需求 R5 第 4 条）。
        单题失败不中断整批，返回统计摘要供界面展示。

        :param question_ids: 待重分析的题目 id 列表
        :return: ``{"total": 总数, "updated": 成功数, "skipped": 人工难度跳过数,
            "failed": 失败数}``
        """
        summary = {"total": len(question_ids), "updated": 0, "skipped": 0, "failed": 0}
        if self._repository is None:
            raise AIServiceError("未接入题目仓储，无法批量重分析难度")

        for question_id in question_ids:
            question = self._repository.get(question_id)
            if question is None:
                summary["failed"] += 1
                continue
            if question.difficulty_source is DifficultySource.MANUAL:
                summary["skipped"] += 1
                continue
            try:
                difficulty = self.analyze(question)
            except Exception:  # noqa: BLE001 - 单题失败不影响其余题目
                summary["failed"] += 1
                continue
            question.difficulty = difficulty
            self._repository.update(question)
            summary["updated"] += 1
        return summary

    @staticmethod
    def _to_difficulty(data: dict) -> Difficulty:
        """把 AI 返回结果转换为难度枚举（非法结果抛 AIServiceError）。

        同时接受三种常见形态（用户需求：AI 返回信息出现问题时要有可读提示）：
        ``{"difficulty": "hard"}``、纯文本 `` {"text": "hard"} ``、
        以及 "difficulty：hard" 这类带字段名的文本；无法识别时抛
        :class:`AIServiceError`，由界面弹窗提示而不是静默降级。
        """
        raw = str(data.get("difficulty") or data.get("text") or "").strip().lower()
        if not raw:
            raise AIServiceError(
                f"AI 返回内容里没有难度信息：{str(data)[:200]}"
            )
        if raw in _DIFFICULTY_WORDS:
            return _DIFFICULTY_WORDS[raw]
        for word, difficulty in _DIFFICULTY_WORDS.items():
            if word in raw:
                return difficulty
        raise AIServiceError(f"AI 返回的难度无法识别：{raw[:60]!r}")
