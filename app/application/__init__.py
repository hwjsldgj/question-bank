"""应用服务层（Application Layer）。

用例编排层：实现"录入建库、难度分析、评分选题、加权随机、AI 补题、
分值汇总、试卷导出、历史记录"等业务流程，对应需求 R1-R14。

组件与职责（依赖均以 app.interfaces 抽象接口注入）：

- ``question_service``      题目 CRUD 与批量粘贴解析（R1 / R2 / R6）
- ``difficulty_service``    AI 难度分析（R4）
- ``cooldown_policy``       冷却窗口策略（R13）
- ``selection_scorer``      选题评分决策（R8）
- ``weighted_sampler``      加权随机抽样（R9）
- ``question_generator``    AI 补题（R10）
- ``paper_composer``        组卷总编排（R7-R10 / R13）
- ``score_calculator``      分值与总分计算（R11）
- ``paper_exporter``        导出编排（R12）
- ``task_history_service``  组卷历史与配置复用（R14）
- ``question_history_service`` 题库操作台账：导入历史 / 编辑历史（用户需求）
- ``prompt_utils``          用户可编辑提示词的安全填充

约束：本层禁止直接依赖 sqlite3 / requests / reportlab / PySide6 等具体实现，
一切外部能力经 app.interfaces 抽象注入。
"""
