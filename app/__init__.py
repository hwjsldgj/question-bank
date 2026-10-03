"""自动出题与组卷工具 —— 应用主包。

包结构与分层（依赖方向自上而下）：

- ``presentation``   表现层：PySide6 界面，仅调用应用服务层，不直接访问数据库
- ``application``    应用服务层：组卷编排、评分决策、AI 调用编排等用例逻辑
- ``interfaces``     接口层（端口）：抽象接口；应用层依赖它，基础设施层实现它
- ``domain``         领域层：实体、枚举、校验器与领域异常，被所有层依赖，自身零依赖
- ``infrastructure`` 基础设施层：SQLite 仓储、AI 客户端、导出器、配置存储的具体实现
- ``config``         配置：评分权重、冷却窗口、AI 调用等默认参数
- ``container``      组合根：把各层实现装配成完整对象图的唯一位置

依赖方向规则::

    presentation -> application -> interfaces <- infrastructure
                        \\-> domain <-/

详见 docs/DEPENDENCIES.md（文件级依赖）与 docs/INTERFACES.md（接口契约）。
"""
