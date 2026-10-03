"""界面视图包。

- ``question_bank_view``   题库管理：录入 / 编辑 / 删除 / 批量粘贴 / 检索
- ``paper_generation_view`` 组卷：条件配置 / 评分随机选题 / 分值 / 导出
- ``history_settings_view`` 历史任务与设置：历史复用 / AI 配置 / 评分配置

约定：视图只依赖 app.container.Container 提供的应用服务，
禁止直接构造仓储或访问 SQLite。
"""
