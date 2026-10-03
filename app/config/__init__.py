"""应用配置包。

``settings`` 集中存放默认配置常量；用户修改后的值经 ConfigStore
持久化（app.infrastructure.config_store），启动时由 container 加载。
"""
