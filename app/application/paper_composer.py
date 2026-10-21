"""组卷引擎：一次组卷请求的总编排（需求 R7-R10 / R13，系统核心组件）。

实现流程（需求 R8 / R9 / R13 落地）：

1. 校验组卷条件（至少启用一个部分，数量为正整数，需求 R7）
2. 逐题型按条件（科目 / 板块 / 题型）检索题库（难度作为评分目标而非硬过滤），
   排除 PENDING 难度与 quality_flag='low' 的题
3. 用 SelectionScorer 对候选逐题评分（难度匹配 / 知识点覆盖 / 质量 / 频次 / 最近使用）
4. 用 WeightedSampler 不放回加权抽样抽取目标数量（评分越高越易中选，且保留随机性）
5. 组卷分区（选择题 / 填空题 / 解答题），按题型写入默认单题分值
6. 更新使用记录（需求 R13 第 1 条）
7. 生成答案页数据并汇总总分（需求 R11 / R12）

选题算法中 AI 补题（QuestionGenerator）暂未接入，``allow_ai_supplement``
参数保留但不生效。

依赖（构造注入）：
- app.interfaces.repositories.QuestionRepository / UsageRepository
- app.application.selection_scorer.SelectionScorer
- app.application.weighted_sampler.WeightedSampler
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
from app.domain.entities.scoring import ScoringContext
from app.domain.enums import Difficulty, QuestionType, SectionKind
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
    """组卷引擎：按评分 + 加权抽样组装试卷。"""

    def __init__(
        self,
        question_repository: QuestionRepository,
        usage_repository: UsageRepository,
        selection_scorer: SelectionScorer,
        weighted_sampler: WeightedSampler,
        question_generator: QuestionGenerator | None,
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

        # 同一题型的多条要求（知识点 × 难度）合并为一个分区；
        # 全局 seen_ids 保证整张卷子不出现重复题（用户需求）
        collected: dict[QuestionType, list[Question]] = {}
        seen_ids: set[str] = set()
        covered_points: set[str] = set()
        now = datetime.now()
        for requirement in criteria.enabled_requirements():
            bucket = collected.setdefault(requirement.question_type, [])
            for question in self._select_for_requirement(
                requirement, covered_points, now, exclude_ids=seen_ids
            ):
                if question.id in seen_ids:
                    continue
                bucket.append(question)
                seen_ids.add(question.id)
                covered_points.update(question.knowledge_points)

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

        paper = Paper(
            criteria=criteria,
            sections=sections,
            title=criteria.title,
            notes=criteria.notes,
        )
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

    def _select_for_requirement(
        self,
        requirement: TypeRequirement,
        covered_points: set[str],
        now: datetime,
        exclude_ids: set[str] | None = None,
    ) -> list[Question]:
        """为单个题型要求检索候选、评分并按加权随机抽取（需求 R8 / R9）。

        :param requirement: 单题型出题要求（题型 / 科目 / 知识点板块 / 目标难度 / 数量）
        :param covered_points: 当前试卷已覆盖的知识点集合（用于覆盖度评分）
        :param now: 本次组卷的统一时间基准（使同一卷所有题的惩罚计算一致）
        :param exclude_ids: 已在其他题型中入选的题目 id 集合，跨题型去重
        :return: 最终入选题目列表（保持题库顺序，数量不超过 ``requirement.count``）
        """
        # 难度硬过滤（需求 R7 第 2 条）：目标难度为 PENDING 时视为"不限"，
        # 否则只检索该难度题库，不混入其它难度。
        filter_difficulty = (
            requirement.difficulty
            if requirement.difficulty != Difficulty.PENDING
            else None
        )
        questions = self._question_repository.search(
            QuestionFilter(
                subject=requirement.subject.strip(),
                section=requirement.section.strip() or None,
                difficulty=filter_difficulty,
                question_type=requirement.question_type,
                exclude_low_quality=True,
            )
        )
        # 排除 PENDING 难度（无法判定难度匹配，不参与智能组卷）
        questions = [q for q in questions if q.difficulty != Difficulty.PENDING]
        # 跨题型去重（用户需求：同一张卷不能有重复题）
        if exclude_ids:
            questions = [q for q in questions if q.id not in exclude_ids]
        points = [str(p).strip() for p in requirement.knowledge_points if str(p).strip()]
        if points:
            questions = [
                q for q in questions if any(p in q.knowledge_points for p in points)
            ]
        if not questions:
            return []

        context = ScoringContext(
            target_difficulty=requirement.difficulty,
            covered_knowledge_points=set(covered_points),
            now=now,
        )
        scored = self._selection_scorer.score(questions, context)
        picked = self._weighted_sampler.sample(scored, requirement.count)
        picked_ids = {item.question.id for item in picked}
        # 按题库顺序回填，保证卷面题序与题库自然顺序一致
        return [q for q in questions if q.id in picked_ids]

    def _record_usage(self, questions: list[Question]) -> None:
        """把本次入选题目写入使用记录（需求 R13 第 1 条）。"""
        if not questions:
            return
        self._usage_repository.record_usage([q.id for q in questions], datetime.now())