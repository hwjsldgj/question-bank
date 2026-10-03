"""表现层（Presentation Layer）。

基于 PySide6 的桌面界面，仅通过应用服务层完成业务操作，
不直接访问数据库 / AI / 导出器等基础设施。

- ``main_window`` 主窗口：菜单 / 状态栏 / 标签页容器 / 跨视图信号协调
- ``ui_utils``     共享工具：枚举中文标签、统一对话框、受限服务调用包装
- ``views.question_bank_view``       题库管理视图（需求 R1 / R2 / R5 / R6）
- ``views.paper_generation_view``    组卷视图（需求 R7-R12）
- ``views.history_view``             历史视图：组卷 / 导入 / 编辑历史（需求 R14）
- ``views.settings_view``            设置视图：AI 配置与提示词 / 评分 / 科目（需求 R15）

依赖：PySide6、app.container、app.application.*（只调用，不实现业务）
被使用：main.py
"""
