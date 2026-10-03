"""SQLiteUsageRepository：使用记录仓储的 SQLite 实现。

实现接口：app.interfaces.repositories.UsageRepository
依赖：app.infrastructure.database.connection.DatabaseConnection、
      app.infrastructure.database.schema（question_usage 表）、
      app.domain.entities.usage_record
被使用：app.container（装配给 PaperComposer / SelectionScorer）
"""

from datetime import datetime

from app.domain.entities.usage_record import UsageRecord
from app.infrastructure.database.connection import DatabaseConnection
from app.interfaces.repositories import UsageRepository


class SQLiteUsageRepository(UsageRepository):
    """使用记录仓储 SQLite 实现：question_usage 表（UPSERT 语义）。"""

    def __init__(self, db: DatabaseConnection) -> None:
        """注入数据库连接管理器。"""
        self._db = db

    def record_usage(self, question_ids: list[str], used_at: datetime) -> None:
        """批量记录一次入卷：use_count 加一、last_used_at 更新（需求 R13 第 1 条）。

        必须在单事务内完成，保证与组卷结果一致（需求 R16 第 2 条）。
        """
        raise NotImplementedError("TODO(R13): 实现使用记录批量更新")

    def get(self, question_id: str) -> UsageRecord:
        """读取单题使用记录；无记录时返回零值记录。"""
        raise NotImplementedError("TODO(R13): 实现单题使用记录读取")

    def get_many(self, question_ids: list[str]) -> dict[str, UsageRecord]:
        """批量读取使用记录（评分器一次性取全量候选的使用数据）。"""
        raise NotImplementedError("TODO(R13): 实现批量使用记录读取")
