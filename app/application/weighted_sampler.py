"""加权随机抽样器：评分决策之后的随机环节（需求 R9）。

以选题评分为权重执行不放回加权随机抽样：

- 权重取 max(score, epsilon)，保证权重恒正（设计文档 Correctness #6）
- 每抽中一题即将其移出候选集合，实现同卷去重（需求 R9 第 2 / 3 条）
- 随机数发生器可注入，便于测试复现

依赖：app.domain.entities.scoring.ScoredQuestion
被使用：app.application.paper_composer、app.container、
        tests.test_weighted_sampler
"""

import random

from app.domain.entities.scoring import ScoredQuestion


class WeightedSampler:
    """加权随机抽样器：纯算法组件，无副作用。"""

    def __init__(self, rng: random.Random | None = None, epsilon: float = 1e-6) -> None:
        """注入随机数发生器与权重下限。

        :param rng: 随机数发生器；None 时使用模块级默认实例
        :param epsilon: 权重下限（评分 <= 0 的候选仍保留极小中选概率）
        """
        self._rng = rng if rng is not None else random.Random()
        self._epsilon = epsilon

    def sample(self, scored: list[ScoredQuestion], k: int) -> list[ScoredQuestion]:
        """不放回加权随机抽取 k 个候选（需求 R9 第 1 条）。

        :param scored: 已评分候选集合
        :param k: 需要抽取的数量（k 不得大于候选数量，由调用方保证）
        :return: 抽中的候选列表（保持抽取顺序即卷面顺序）
        """
        raise NotImplementedError("TODO(R9): 实现不放回加权随机抽样")
