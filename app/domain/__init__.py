"""领域层（Domain Layer）。

包含系统的核心概念与业务规则中最稳定的部分：

- ``enums``      受限取值枚举（题型 / 难度 / 来源 / 分区 / 导出格式等）
- ``errors``     领域异常体系
- ``entities``   实体与值对象（Question / UsageRecord / PaperCriteria / Paper 等）
- ``validators`` 领域校验器（题型规则、分值规则）

约束：本层不得导入其他任何层（application / infrastructure / presentation /
interfaces），保证可独立测试与复用。
"""
