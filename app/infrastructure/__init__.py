"""基础设施层（Infrastructure Layer）。

实现 app.interfaces 中定义的全部抽象接口，并封装所有外部技术细节：

- ``database``       SQLite 连接管理与建表迁移
- ``repositories``   题目 / 使用记录 / 组卷任务的 SQLite 仓储实现
- ``ai``             OpenAI 兼容 AI API 客户端实现
- ``exporters``      TXT / PDF 导出器实现
- ``config_store``   AI 与评分配置的本机持久化实现

约束：本层只允许被 app.container（组合根）与 main.py 直接构造；
应用服务层与表现层仅通过 app.interfaces 抽象访问本层能力。
"""
