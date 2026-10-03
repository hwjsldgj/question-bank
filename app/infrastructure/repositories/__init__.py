"""仓储实现：SQLite 版题目 / 使用记录 / 组卷任务仓储。

实现方与接口对应关系：

- ``question_repository.SQLiteQuestionRepository`` -> interfaces.repositories.QuestionRepository
- ``usage_repository.SQLiteUsageRepository``       -> interfaces.repositories.UsageRepository
- ``task_repository.SQLiteTaskRepository``         -> interfaces.repositories.TaskRepository

被使用：app.container（装配）、tests（以接口契约驱动测试）
"""

from app.infrastructure.database.connection import DatabaseConnection  # noqa: F401
