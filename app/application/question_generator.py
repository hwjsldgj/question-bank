"""AI 补题服务：候选不足时按知识点生成新题（需求 R10）。

通过 AI API 依据科目 / 知识点 / 题型 / 难度生成题目；生成结果必须通过
题型规则校验，非法题目丢弃并重试，重试耗尽后由调用方上报实际可提供
数量（需求 R10 第 2 / 4 / 6 条）。生成题目以 source=AI 入库（R10 第 5 条）。

依赖（构造注入）：
- app.interfaces.ai_client.AIClient（AI API 抽象）
- app.domain.validators.question_validator.QuestionValidator（生成结果校验）
- app.interfaces.repositories.QuestionRepository（AI 生成题入库）

被使用：app.application.paper_composer、app.container
"""

from app.domain.entities.question import Question
from app.domain.enums import Difficulty, QuestionType
from app.domain.validators.question_validator import QuestionValidator
from app.interfaces.ai_client import AIClient
from app.interfaces.repositories import QuestionRepository


class QuestionGenerator:
    """AI 补题服务：题库数量不足时的兜底出题能力。"""

    def __init__(
        self,
        ai_client: AIClient,
        validator: QuestionValidator,
        repository: QuestionRepository,
        max_retries: int = 2,
    ) -> None:
        """注入 AI 客户端、校验器、题目仓储与重试上限。"""
        self._ai_client = ai_client
        self._validator = validator
        self._repository = repository
        self._max_retries = max_retries

    def generate_questions(
        self,
        subject: str,
        knowledge_points: list[str],
        question_type: QuestionType,
        difficulty: Difficulty,
        count: int,
    ) -> list[Question]:
        """生成并入库 count 道符合要求的题目（需求 R10 第 2-5 条）。

        :param subject: 科目（生成依据）
        :param knowledge_points: 知识点列表（生成依据）
        :param question_type: 目标题型
        :param difficulty: 目标难度
        :param count: 需要生成的数量（差额）
        :return: 实际成功生成并入库的题目列表；数量可能少于 count
        :raises app.domain.errors.AIConfigMissingError: AI 服务未配置
        """
        raise NotImplementedError("TODO(R10): 实现 AI 补题流程")

    def _build_prompt(
        self,
        subject: str,
        knowledge_points: list[str],
        question_type: QuestionType,
        difficulty: Difficulty,
    ) -> str:
        """拼装补题提示词（私有方法：包含题型结构要求与输出格式约定）。"""
        raise NotImplementedError("TODO(R10): 实现补题提示词拼装")
