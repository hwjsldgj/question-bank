"""评分模型值对象：ScoreFactors / ScoredQuestion / ScoringContext。

对应设计文档 "Components and Interfaces -> SelectionScorer" 的评分公式::

    score = w1*difficulty_match + w2*knowledge_coverage + w3*quality
            - w4*use_count_penalty - w5*recency_penalty

依赖：app.domain.entities.question、app.domain.enums
被使用：app.application.selection_scorer、app.application.weighted_sampler、
        app.application.cooldown_policy（读取上下文）
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.entities.question import Question
from app.domain.enums import Difficulty


@dataclass
class ScoreFactors:
    """单道候选题的分项因子值对象（便于调试与界面展示评分依据）。"""

    difficulty_match: float = 0.0
    """难度匹配度（正向）：与目标难度越接近越高。"""

    knowledge_coverage: float = 0.0
    """知识点覆盖（正向）：覆盖尚未覆盖知识点时 > 0。"""

    quality: float = 0.0
    """人工质量（正向）：优质 > 0，低质 < 0，普通为 0。"""

    use_count_penalty: float = 0.0
    """使用频次惩罚（负向项，取正值参与减法）：历史被选次数越多越大。"""

    recency_penalty: float = 0.0
    """最近使用惩罚（负向项，取正值参与减法）：距上次使用越近越大。"""


@dataclass
class ScoredQuestion:
    """带评分的候选题值对象：WeightedSampler 的输入单元。"""

    question: Question
    """候选题目本体。"""

    score: float
    """综合选题评分，作为加权随机抽样的权重。"""

    factors: ScoreFactors = field(default_factory=ScoreFactors)
    """分项因子，用于调试与"评分依据"展示。"""


@dataclass
class ScoringContext:
    """一次评分计算的上下文。

    :param target_difficulty: 目标难度（来自 TypeRequirement）
    :param covered_knowledge_points: 当前试卷已覆盖的知识点集合，
        随选题进行动态增长，用于知识点覆盖因子
    :param now: 评分时刻，冷却窗口与最近使用惩罚以此为基准
    """

    target_difficulty: Difficulty
    covered_knowledge_points: set[str] = field(default_factory=set)
    now: datetime | None = None
