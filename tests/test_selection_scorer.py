"""选题评分器测试计划（业务实现后补充实际用例）。

对应需求 R8 与设计文档 Correctness Properties #11，规划用例：

- 难度匹配：与目标难度相同的候选评分高于相差一级的候选（单调性）
- 知识点覆盖：覆盖未覆盖知识点的候选评分高于重复知识点的候选
- 质量：优质题加分、低质题减分
- 频次惩罚：use_count 越大评分越低
- 最近使用：last_used_at 越近评分越低；冷却窗口内进一步加重
- 权重可配置：修改 ScoringConfig 权重后评分随之变化
"""

import pytest


@pytest.mark.skip(reason="框架阶段：待 SelectionScorer 业务实现后启用")
def test_selection_scorer_placeholder() -> None:
    raise AssertionError("占位用例不应被执行")
