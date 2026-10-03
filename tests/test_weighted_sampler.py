"""加权随机抽样器测试计划（业务实现后补充实际用例）。

对应需求 R9 与设计文档 Correctness Properties #6 / #7，规划用例：

- 抽取数量正确，结果不含重复题目（不放回）
- 评分非正的候选仍可能被抽中（epsilon 兜底，权重恒正）
- 注入固定随机数发生器时结果可复现
- 统计性断言：高评分候选的中选概率显著高于低评分候选
"""

import pytest


@pytest.mark.skip(reason="框架阶段：待 WeightedSampler 业务实现后启用")
def test_weighted_sampler_placeholder() -> None:
    raise AssertionError("占位用例不应被执行")
