"""选题评分器：算法评分决策（需求 R8，系统核心算法组件）。

对候选题集合逐题计算综合评分::

    score = w1*difficulty_match + w2*knowledge_coverage + w3*quality
            - w4*use_count_penalty - w5*recency_penalty

各因子方向（需求 R8）：

- 难度匹配度：与目标难度越接近越高（正向）
- 知识点覆盖：覆盖试卷尚未覆盖的知识点时加分（正向，动态因子）
- 人工质量：优质加分、低质减分（正向 / 负向）
- 使用频次惩罚：历史被选次数越多扣分越多（负向）
- 最近使用惩罚：距上次使用越近扣分越多，冷却窗口内加重（负向）

依赖（构造注入）：
- app.interfaces.repositories.UsageRepository（批量读取使用记录）
- app.application.cooldown_policy.CooldownPolicy（惩罚分计算）
- app.domain.entities.configs.ScoringConfig（权重配置）

被使用：app.application.paper_composer、app.container
"""

from datetime import datetime

from app.domain.entities.configs import ScoringConfig
from app.domain.entities.question import Question
from app.domain.entities.scoring import ScoreFactors, ScoredQuestion, ScoringContext
from app.domain.entities.usage_record import UsageRecord
from app.domain.enums import Difficulty, QualityFlag
from app.interfaces.repositories import UsageRepository

from app.application.cooldown_policy import CooldownPolicy

#: 难度 -> 有序索引（仅用于计算"相差几级"；PENDING 不参与排序）
_DIFFICULTY_RANK: dict[Difficulty, int] = {
    Difficulty.EASY: 0,
    Difficulty.MEDIUM: 1,
    Difficulty.HARD: 2,
}

#: 难度中性的匹配分（目标或实际为 PENDING 时使用，避免误判）
_NEUTRAL_FACTOR = 0.5

#: 质量标记 -> 质量因子得分
_QUALITY_FACTOR: dict[QualityFlag, float] = {
    QualityFlag.QUALITY: 1.0,
    QualityFlag.NORMAL: 0.0,
    QualityFlag.LOW: -1.0,
}


class SelectionScorer:
    """选题评分器：评分决策的唯一实现位置。"""

    def __init__(
        self,
        usage_repository: UsageRepository,
        cooldown_policy: CooldownPolicy,
        config: ScoringConfig,
    ) -> None:
        """注入使用记录仓储、冷却策略与评分配置。"""
        self._usage_repository = usage_repository
        self._cooldown_policy = cooldown_policy
        self._config = config

    def score(
        self, candidates: list[Question], context: ScoringContext
    ) -> list[ScoredQuestion]:
        """为候选集合逐题评分（需求 R8 第 2 条）。

        :param candidates: 满足组卷条件的命中题候选集合
        :param context: 评分上下文（目标难度 / 已覆盖知识点 / 当前时刻）
        :return: 按评分降序排列的带评分候选列表
        """
        if not candidates:
            return []
        now = context.now or datetime.now()
        ids = [q.id for q in candidates]
        records = self._usage_repository.get_many(ids)

        scored: list[ScoredQuestion] = []
        for question in candidates:
            record = records.get(question.id) or UsageRecord(question_id=question.id)
            factors = self._compute_factors(question, record, context, now)
            total = (
                self._config.weight_difficulty * factors.difficulty_match
                + self._config.weight_knowledge_coverage * factors.knowledge_coverage
                + self._config.weight_quality * factors.quality
                - self._config.weight_use_count * factors.use_count_penalty
                - self._config.weight_recency * factors.recency_penalty
            )
            scored.append(
                ScoredQuestion(question=question, score=total, factors=factors)
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored

    def _compute_factors(
        self,
        question: Question,
        record: UsageRecord,
        context: ScoringContext,
        now: datetime,
    ) -> ScoreFactors:
        """计算单题五个因子（score 内部使用，避免重复遍历）。"""
        return ScoreFactors(
            difficulty_match=self.difficulty_match_factor(question, context),
            knowledge_coverage=self.knowledge_coverage_factor(question, context),
            quality=self.quality_factor(question),
            use_count_penalty=self._cooldown_policy.use_count_penalty(record),
            recency_penalty=self._cooldown_policy.recency_penalty(record, now),
        )

    def difficulty_match_factor(
        self, question: Question, context: ScoringContext
    ) -> float:
        """计算难度匹配度因子（需求 R8 第 3 条：越接近目标难度越高）。

        映射：目标 / 实际任一侧为 PENDING 时返回中性 0.5；
        否则 ``1 - |idx(target) - idx(question)| / 2``，取值 {0, 0.5, 1}。
        """
        target_rank = _DIFFICULTY_RANK.get(context.target_difficulty)
        actual_rank = _DIFFICULTY_RANK.get(question.difficulty)
        if target_rank is None or actual_rank is None:
            return _NEUTRAL_FACTOR
        return 1.0 - abs(target_rank - actual_rank) / 2.0

    def knowledge_coverage_factor(
        self, question: Question, context: ScoringContext
    ) -> float:
        """计算知识点覆盖因子（需求 R8 第 4 条：覆盖未覆盖知识点时加分）。

        = 本题知识点中未被试卷覆盖的比例；无知识点时返回中性 0.5。
        """
        points = [p for p in question.knowledge_points if p]
        if not points:
            return _NEUTRAL_FACTOR
        covered = context.covered_knowledge_points
        uncovered = sum(1 for p in points if p not in covered)
        return uncovered / len(points)

    def quality_factor(self, question: Question) -> float:
        """计算人工质量因子（需求 R5 第 3 条 / R8 第 8 条：优质加分、低质减分）。

        取值：quality=+1.0 / normal=0.0 / low=-1.0。
        """
        return _QUALITY_FACTOR.get(question.quality_flag, 0.0)