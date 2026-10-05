"""接口层（端口层，Ports）。

定义应用服务层所依赖的全部抽象接口；具体实现位于基础设施层。
本层是"依赖倒置"的枢纽::

    application --依赖--> interfaces <--实现-- infrastructure

- ``repositories`` 仓储与配置存储接口（SQLite 实现于 infrastructure/repositories）
- ``ai_client``    AI API 客户端接口（OpenAI 兼容实现于 infrastructure/ai）
- ``exporters``    试卷导出器接口（MD / PDF 实现于 infrastructure/exporters）

约束：接口方法只允许引用 domain 实体，禁止暴露任何实现细节
（如 sqlite3.Connection、requests.Session）。
"""
