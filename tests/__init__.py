"""测试包。

测试策略对应设计文档 "Test Strategy"：

- ``test_smoke``             冒烟测试：框架可导入、核心类型存在（已启用）
- ``test_question_validator`` 题型规则校验用例（业务实现后补充）
- ``test_selection_scorer``   评分因子单调性用例（业务实现后补充）
- ``test_cooldown_policy``    冷却窗口判定与放宽用例（业务实现后补充）
- ``test_weighted_sampler``   加权抽样去重与概率用例（业务实现后补充）
- ``test_paper_composer``     组卷主路径集成用例（业务实现后补充）

运行方式::

    python -m pytest tests/ -v
"""
