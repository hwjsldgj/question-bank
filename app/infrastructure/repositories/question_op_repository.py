"""SQLiteQuestionOpRepository：题库操作台账（导入历史 / 编辑历史）的 SQLite 实现。

实现接口：app.interfaces.repositories.QuestionOpRepository
依赖：app.infrastructure.database.connection.DatabaseConnection、
      app.infrastructure.database.schema（question_operations 表）、
      app.domain.entities.question_op
被使用：app.container（装配给 QuestionService / QuestionHistoryService）
"""

import uuid
from datetime import datetime

from app.domain.entities.question_op import QuestionOpRecord
from app.domain.enums import QuestionOpAction
from app.infrastructure.database.connection import DatabaseConnection
from app.interfaces.repositories import QuestionOpRepository


class SQLiteQuestionOpRepository(QuestionOpRepository):
    """题库操作台账 SQLite 实现：追加写入 + 按操作类型倒序查询。"""

    def __init__(self, db: DatabaseConnection) -> None:
        """注入数据库连接管理器。"""
        self._db = db

    def record(self, record: QuestionOpRecord) -> None:
        """追加一条题库操作记录（导入 / 编辑 / 删除 / 批量导入）。"""
        if not record.id:
            record.id = str(uuid.uuid4())
        record.created_at = record.created_at or datetime.now()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO question_operations "
                "(id, action, question_id, subject, stem_excerpt, batch_id, detail, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.action.value,
                    record.question_id,
                    record.subject,
                    record.stem_excerpt,
                    record.batch_id,
                    record.detail,
                    record.created_at.isoformat(timespec="seconds"),
                ),
            )

    def list_records(
        self, actions: list[str] | None = None, limit: int | None = None
    ) -> list[QuestionOpRecord]:
        """按操作类型筛选记录，按时间倒序返回。"""
        sql = "SELECT * FROM question_operations"
        params: list[object] = []
        if actions:
            values = [
                action.value if isinstance(action, QuestionOpAction) else str(action)
                for action in actions
            ]
            sql += " WHERE action IN (" + ", ".join("?" for _ in values) + ")"
            params.extend(values)
        sql += " ORDER BY created_at DESC, rowid DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = self._db.connect().execute(sql, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _row_to_record(row) -> QuestionOpRecord:
        """行数据 -> QuestionOpRecord 实体。"""
        created_at = None
        if row["created_at"]:
            try:
                created_at = datetime.fromisoformat(row["created_at"])
            except (TypeError, ValueError):
                created_at = None
        return QuestionOpRecord(
            id=row["id"],
            action=QuestionOpAction(row["action"]),
            question_id=row["question_id"],
            subject=row["subject"],
            stem_excerpt=row["stem_excerpt"],
            batch_id=row["batch_id"],
            detail=row["detail"],
            created_at=created_at,
        )
