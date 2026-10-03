"""SQLite 数据库基础设施。

- ``connection`` 连接管理器（事务上下文）
- ``schema``     建表语句与迁移（应用启动时执行）

被使用：app.infrastructure.repositories.*、app.infrastructure.config_store、
        app.container
"""
