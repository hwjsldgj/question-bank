"""题目服务：题库 CRUD、批量粘贴解析与可用量统计（需求 R1 / R2 / R6）。

依赖（构造注入）：
- app.interfaces.repositories.QuestionRepository（题目持久化）
- app.domain.validators.question_validator.QuestionValidator（入库前校验）
- app.application.difficulty_service.DifficultyService（入库后触发难度分析）

被使用：app.presentation.views.question_bank_view、app.container
"""

from app.domain.entities.question import Question, QuestionFilter
from app.domain.enums import Difficulty, QualityFlag, QuestionType
from app.domain.validators.question_validator import QuestionValidator
from app.interfaces.repositories import QuestionRepository

from app.application.difficulty_service import DifficultyService


class QuestionService:
    """题目服务：题库维护的统一入口。

    职责对应需求：

    - R1：题目手工录入与维护（保存 / 编辑 / 删除）
    - R2：批量粘贴录入（解析预览 -> 确认提交）
    - R6：题库检索与命中量统计
    - R5：人工质量标记
    """

    def __init__(
        self,
        repository: QuestionRepository,
        validator: QuestionValidator,
        difficulty_service: DifficultyService,
    ) -> None:
        """注入仓储、校验器与难度分析服务。"""
        self._repository = repository
        self._validator = validator
        self._difficulty_service = difficulty_service

    def create_question(self, draft: Question) -> Question:
        """新增题目：校验通过后落库并触发 AI 难度分析（需求 R1 / R4）。

        :param draft: 待保存的题目草稿（id 可为空，由仓储分配）
        :return: 已落库并带唯一标识的题目
        :raises app.domain.errors.QuestionValidationError: 题型规则不满足
        """
        raise NotImplementedError("TODO(R1/R4): 实现新增题目流程")

    def update_question(self, question_id: str, patch: dict) -> Question:
        """编辑题目：合并字段、校验后更新，保留 id 与使用记录（需求 R1 第 3 条）。

        :param question_id: 目标题目 id
        :param patch: 待更新的字段字典（键为 Question 字段名）
        :return: 更新后的题目
        """
        raise NotImplementedError("TODO(R1): 实现编辑题目流程")

    def delete_question(self, question_id: str) -> None:
        """删除题目，使其不再参与后续组卷（需求 R1 第 4 条）。"""
        raise NotImplementedError("TODO(R1): 实现删除题目")

    def set_quality_flag(self, question_id: str, flag: QualityFlag) -> None:
        """设置人工质量标记，参与后续选题评分（需求 R5 第 3 条 / R8 第 8 条）。"""
        raise NotImplementedError("TODO(R5): 实现质量标记设置")

    def batch_parse(self, raw_text: str) -> list[Question]:
        """把粘贴的多题文本拆分为候选题目列表（需求 R2 第 1 条）。

        无法解析必填字段的条目以"待修正"状态返回，交由界面预览突出显示
        （需求 R2 第 2 / 4 条）。

        :param raw_text: 用户粘贴的原始文本
        :return: 候选题目列表（未落库）
        """
        raise NotImplementedError("TODO(R2): 实现粘贴文本解析")

    def batch_commit(self, drafts: list[Question]) -> list[Question]:
        """批量写入确认后的候选题目（需求 R2 第 3 条），逐题触发难度分析。

        :param drafts: 预览确认后的候选题目
        :return: 已落库的题目列表
        """
        raise NotImplementedError("TODO(R2): 实现批量入库")

    def search(self, question_filter: QuestionFilter) -> list[Question]:
        """按条件检索题库（需求 R6 第 1 条），透传仓储查询。"""
        raise NotImplementedError("TODO(R6): 实现题库检索")

    def count_available(
        self, subject: str, difficulty: Difficulty, question_type: QuestionType
    ) -> int:
        """统计某组卷条件的命中题数量（需求 R6 第 2 / 3 条）。"""
        raise NotImplementedError("TODO(R6): 实现命中量统计")
