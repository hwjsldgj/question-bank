"""SQLiteTaskRepository：组卷任务仓储的 SQLite 实现。

实现接口：app.interfaces.repositories.TaskRepository
依赖：app.infrastructure.database.connection.DatabaseConnection、
      app.infrastructure.database.schema（generation_tasks / task_exports / task_questions 表）、
      app.domain.entities.task
被使用：app.container（装配给 TaskHistoryService）
"""

from app.domain.entities.task import GenerationTask
from app.infrastructure.database.connection import DatabaseConnection
from app.interfaces.repositories import TaskRepository


class SQLiteTaskRepository(TaskRepository):
    """组卷任务仓储 SQLite 实现：generation_tasks + task_exports 表。"""

    def __init__(self, db: DatabaseConnection) -> None:
        """注入数据库连接管理器。"""
        self._db = db

    def save_task(self, task: GenerationTask) -> None:
        """保存或更新任务及其导出记录（需求 R14 第 1 条）。"""
        raise NotImplementedError("TODO(R14): 实现任务保存")

    def get_task(self, task_id: str) -> GenerationTask | None:
        """按 id 读取任务（含导出记录）。"""
        raise NotImplementedError("TODO(R14): 实现任务读取")

    def list_tasks(self) -> list[GenerationTask]:
        """按创建时间倒序返回全部任务（需求 R14 第 2 条）。"""
        raise NotImplementedError("TODO(R14): 实现任务列表")
