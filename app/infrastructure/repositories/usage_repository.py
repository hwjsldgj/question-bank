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
        """批量记录一次入卷：use_count 加一、last_used_at 更新（需求 R13 第 1 条）。"""
        if not question_ids:
            return
        stamp = used_at.isoformat(timespec="seconds")
        with self._db.transaction() as conn:
            for question_id in question_ids:
                conn.execute(
                    "INSERT INTO question_usage (question_id, use_count, last_used_at) "
                    "VALUES (?, 1, ?) "
                    "ON CONFLICT(question_id) DO UPDATE SET "
                    "use_count = use_count + 1, last_used_at = excluded.last_used_at",
                    (question_id, stamp),
                )

    def get(self, question_id: str) -> UsageRecord:
        """读取单题使用记录；无记录时返回零值记录。"""
        row = self._db.connect().execute(
            "SELECT * FROM question_usage WHERE question_id = ?", (question_id,)
        ).fetchone()
        if row is None:
            return UsageRecord(question_id=question_id, use_count=0, last_used_at=None)
        return self._row_to_record(row)

    def get_many(self, question_ids: list[str]) -> dict[str, UsageRecord]:
        """批量读取使用记录（评分器一次性取全量候选的使用数据）。"""
        if not question_ids:
            return {}
        placeholders = ", ".join("?" for _ in question_ids)
        rows = self._db.connect().execute(
            f"SELECT * FROM question_usage WHERE question_id IN ({placeholders})",
            list(question_ids),
        ).fetchall()
        return {row["question_id"]: self._row_to_record(row) for row in rows}

    @staticmethod
    def _row_to_record(row) -> UsageRecord:
        """行数据 -> UsageRecord 实体。"""
        last_used = None
        if row["last_used_at"]:
            try:
                last_used = datetime.fromisoformat(row["last_used_at"])
            except (TypeError, ValueError):
                last_used = None
        return UsageRecord(
            question_id=row["question_id"],
            use_count=int(row["use_count"]),
            last_used_at=last_used,
        )
