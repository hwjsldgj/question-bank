"""领域校验器。

- ``question_validator``：题型规则校验（需求 R3）
- ``score_validator``：分值完整性校验（需求 R11）

依赖：app.domain.entities、app.domain.errors、app.domain.enums
被使用：app.application.question_service、app.application.question_generator、
        app.application.paper_exporter
"""
