"""组卷引擎集成测试计划（业务实现后补充实际用例）。

对应需求 R7-R10 / R13 与设计文档 "Test Strategy" 集成测试，规划用例：

- 仅选择题部分 / 仅解答题部分 / 两部分同时（R7、Correctness #3）
- 库内充足：纯库内选组，无 AI 调用，数量守恒（#4）
- 库内不足：AI 补齐差额，AI 题入库且 source=ai（R10、#8）
- AI 补齐仍不足：上报实际数量并请求确认
- 同卷去重（#2）；使用记录更新（R13 第 1 条、#10）
- 全部部分停用 -> 拒绝（R7 第 4 条）
"""

import pytest


@pytest.mark.skip(reason="框架阶段：待 PaperComposer 业务实现后启用")
def test_paper_composer_placeholder() -> None:
    raise AssertionError("占位用例不应被执行")
