"""界面视图包。

- ``question_bank_view``     题库管理：录入 / 编辑 / 删除 / 批量粘贴 / 检索
                              （科目下拉、题目图片导入、AI 辨识）
- ``paper_generation_view``  组卷：条件配置 / 评分随机选题 / 分值 / 导出
- ``history_view``           历史：组卷历史 / 导入历史 / 编辑历史（与设置分开）
- ``settings_view``          设置：AI 配置与提示词 / 评分与冷却 / 科目管理

约定：视图只依赖 app.container.Container 提供的应用服务，
禁止直接构造仓储或访问 SQLite。
"""
