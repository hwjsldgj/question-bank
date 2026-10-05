"""组卷引擎：一次组卷请求的总编排（需求 R7-R10 / R13，系统核心组件）。

当前实现（用户需求：顺序读取题目作为占位）：

1. 校验组卷条件（至少启用一个部分，数量为正整数，需求 R7）
2. 逐题型按条件（科目 / 难度 / 知识点）检索题库，**按题库顺序取前 N 道**作为选题占位
3. 组卷分区（选择题 / 填空题 / 解答题），按题型写入默认单题分值
4. 更新使用记录（需求 R13 第 1 条）
5. 生成答案页数据并汇总总分（需求 R11 / R12）

选题算法（评分决策 / 加权随机抽样 / AI 补题）尚未实现，注入的
SelectionScorer / WeightedSampler / QuestionGenerator 暂时不参与流程，
``allow_ai_supplement`` 参数被保留但不生效。

依赖（构造注入）：
- app.interfaces.repositories.QuestionRepository / UsageRepository
- app.application.selection_scorer.SelectionScorer（预留）
- app.application.weighted_sampler.WeightedSampler（预留）
- app.application.question_generator.QuestionGenerator（预留）
- app.application.score_calculator.ScoreCalculator
- app.domain.entities.configs.ScoringConfig
- app.config.settings.DEFAULT_TYPE_SCORES

被使用：app.presentation.views.paper_generation_view、app.container
"""

from datetime import datetime

from app.config.settings import DEFAULT_TYPE_SCORES
from app.domain.entities.configs import ScoringConfig
from app.domain.entities.criteria import PaperCriteria, TypeRequirement
from app.domain.entities.paper import Paper, Section
from app.domain.entities.question import Question, QuestionFilter
from app.domain.enums import QuestionType, SectionKind
from app.domain.errors import CriteriaValidationError
from app.interfaces.repositories import QuestionRepository, UsageRepository

from app.application.question_generator import QuestionGenerator
from app.application.score_calculator import ScoreCalculator
from app.application.selection_scorer import SelectionScorer
from app.application.weighted_sampler import WeightedSampler

#: 题型 -> 提示用中文名（校验失败信息里使用）
_TYPE_LABELS: dict[QuestionType, str] = {
    QuestionType.SINGLE: "单选题",
    QuestionType.MULTIPLE: "多选题",
    QuestionType.FILL: "填空题",
    QuestionType.SOLUTION: "解答题",
}

#: 题型 -> 所属试卷部分（需求 R7 / R12 分区依据）
_SECTION_KINDS: dict[QuestionType, SectionKind] = {
    QuestionType.SINGLE: SectionKind.CHOICE,
    QuestionType.MULTIPLE: SectionKind.CHOICE,
    QuestionType.FILL: SectionKind.FILL,
    QuestionType.SOLUTION: SectionKind.SOLUTION,
}


class PaperComposer:
    """组卷引擎：按组卷条件顺序读取题库并组装试卷。"""

    def __init__(
        self,
        question_repository: QuestionRepository,
        usage_repository: UsageRepository,
        selection_scorer: SelectionScorer,
        weighted_sampler: WeightedSampler,
        question_generator: QuestionGenerator,
        score_calculator: ScoreCalculator,
        config: ScoringConfig,
    ) -> None:
        """注入组卷所需的全部协作组件。"""
        self._question_repository = question_repository
        self._usage_repository = usage_repository
        self._selection_scorer = selection_scorer
        self._weighted_sampler = weighted_sampler
        self._question_generator = question_generator
        self._score_calculator = score_calculator
        self._config = config

    def generate(
        self, criteria: PaperCriteria, allow_ai_supplement: bool = False
    ) -> Paper:
        """执行一次组卷并返回试卷实体（需求 R7-R10 / R13）。

        题库不足时按实际可提供数量出卷，不做 AI 补题；
        ``allow_ai_supplement`` 暂未生效（AI 补题属后续选题算法范围）。

        :param criteria: 组卷条件（各部分均可选，至少启用一个）
        :param allow_ai_supplement: 用户是否已确认允许 AI 补题（当前忽略）
        :return: 已完成选题与分值汇总的试卷
        :raises app.domain.errors.CriteriaValidationError: 组卷条件非法
        """
        self._validate_criteria(criteria)

        # 同一题型的多条要求（知识点 × 难度）合并为一个分区，同卷按 id 去重
        collected: dict[QuestionType, list[Question]] = {}
        for requirement in criteria.enabled_requirements():
            bucket = collected.setdefault(requirement.question_type, [])
            for question in self._select_for_requirement(requirement):
                if any(existing.id == question.id for existing in bucket):
                    continue
                bucket.append(question)

        sections: list[Section] = []
        for question_type, questions in collected.items():
            if not questions:
                continue
            section = Section(
                section_kind=_SECTION_KINDS[question_type],
                question_type=question_type,
                questions=questions,
            )
            self._score_calculator.set_type_score(
                section, DEFAULT_TYPE_SCORES[question_type]
            )
            sections.append(section)

        paper = Paper(criteria=criteria, sections=sections)
        self._record_usage(paper.questions())
        self._score_calculator.build_answer_page(paper)
        paper.total_score = self._score_calculator.total_score(paper)
        return paper

    def _validate_criteria(self, criteria: PaperCriteria) -> None:
        """校验组卷条件（需求 R7 第 4 / 5 条），非法时抛出异常。"""
        requirements = criteria.enabled_requirements()
        if not requirements:
            raise CriteriaValidationError(
                "请至少启用一个题型，并为其中一个「知识点 / 难度」配置大于 0 的题数。"
            )
        for requirement in requirements:
            label = _TYPE_LABELS.get(requirement.question_type, "题目")
            if requirement.count <= 0:
                raise CriteriaValidationError(f"{label}数量必须为正整数。")
            if not str(requirement.subject).strip():
                raise CriteriaValidationError(f"{label}必须指定科目。")

    def _select_for_requirement(self, requirement: TypeRequirement) -> list[Question]:
        """为单个题型要求顺序读取题目（占位实现：不评分、不抽样、不补题）。

        :param requirement: 单题型出题要求（题型 / 科目 / 难度 / 数量）
        :return: 按题库顺序截取的前 ``count`` 道题；不足时返回实际可提供的全部
        """
        questions = self._question_repository.search(
            QuestionFilter(
                subject=requirement.subject.strip(),
                difficulty=requirement.difficulty,
                question_type=requirement.question_type,
            )
        )
        points = [str(p).strip() for p in requirement.knowledge_points if str(p).strip()]
        if points:
            questions = [
                q for q in questions if any(p in q.knowledge_points for p in points)
            ]
        return questions[: requirement.count]

    def _record_usage(self, questions: list[Question]) -> None:
        """把本次入选题目写入使用记录（需求 R13 第 1 条）。"""
        if not questions:
            return
        self._usage_repository.record_usage([q.id for q in questions], datetime.now())
