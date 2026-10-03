"""题型规则校验器测试计划（业务实现后补充实际用例）。

对应需求 R3，规划用例：

- 单选题：2 个选项 + 恰 1 个答案 -> 通过
- 单选题：答案为 2 个选项 -> 拒绝并说明原因
- 多选题：答案为 1 个及以上选项 -> 通过
- 多选题：无选项 -> 拒绝
- 解答题：含参考答案、无选项 -> 通过；缺参考答案 -> 拒绝
- 通用：科目 / 题干为空 -> 拒绝
"""

import pytest


@pytest.mark.skip(reason="框架阶段：待 QuestionValidator 业务实现后启用")
def test_question_validator_placeholder() -> None:
    raise AssertionError("占位用例不应被执行")
