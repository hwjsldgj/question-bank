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

from app.domain.entities.configs import ScoringConfig
from app.domain.entities.question import Question
from app.domain.entities.scoring import ScoredQuestion, ScoringContext
from app.interfaces.repositories import UsageRepository

from app.application.cooldown_policy import CooldownPolicy


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
        raise NotImplementedError("TODO(R8): 实现候选题评分")

    def difficulty_match_factor(self, question: Question, context: ScoringContext) -> float:
        """计算难度匹配度因子（需求 R8 第 3 条：越接近目标难度越高）。"""
        raise NotImplementedError("TODO(R8): 实现难度匹配因子")

    def knowledge_coverage_factor(
        self, question: Question, context: ScoringContext
    ) -> float:
        """计算知识点覆盖因子（需求 R8 第 4 条：覆盖未覆盖知识点时加分）。"""
        raise NotImplementedError("TODO(R8): 实现知识点覆盖因子")

    def quality_factor(self, question: Question) -> float:
        """计算人工质量因子（需求 R5 第 3 条 / R8 第 8 条：优质加分、低质减分）。"""
        raise NotImplementedError("TODO(R8): 实现质量因子")
