"""SQLiteTaskRepository：组卷任务仓储的 SQLite 实现。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.domain.entities.criteria import PaperCriteria, TypeRequirement
from app.domain.entities.task import ExportRecord, GenerationTask
from app.domain.enums import Difficulty, ExportFormat, QuestionType
from app.infrastructure.database.connection import DatabaseConnection
from app.interfaces.repositories import TaskRepository


def _criteria_to_dict(c: PaperCriteria) -> dict:
    return {
        "choice_enabled": c.choice_enabled,
        "solution_enabled": c.solution_enabled,
        "fill_enabled": c.fill_enabled,
        "subject": c.subject,
        "choice_items": [
            {"question_type": i.question_type.value, "subject": i.subject,
             "difficulty": i.difficulty.value, "count": i.count,
             "knowledge_points": i.knowledge_points, "section": i.section}
            for i in c.choice_items
        ],
        "fill_items": [
            {"question_type": i.question_type.value, "subject": i.subject,
             "difficulty": i.difficulty.value, "count": i.count,
             "knowledge_points": i.knowledge_points, "section": i.section}
            for i in c.fill_items
        ],
        "solution_items": [
            {"question_type": i.question_type.value, "subject": i.subject,
             "difficulty": i.difficulty.value, "count": i.count,
             "knowledge_points": i.knowledge_points, "section": i.section}
            for i in c.solution_items
        ],
    }

def _dict_to_criteria(data: dict) -> PaperCriteria:
    def _items(key: str) -> list[TypeRequirement]:
        res = []
        for raw in data.get(key) or []:
            try:
                res.append(TypeRequirement(
                    question_type=QuestionType(raw["question_type"]),
                    subject=raw["subject"],
                    difficulty=Difficulty(raw["difficulty"]),
                    count=raw["count"],
                    knowledge_points=raw.get("knowledge_points", []),
                    section=raw.get("section", ""),
                ))
            except Exception:
                pass
        return res

    return PaperCriteria(
        choice_enabled=data.get("choice_enabled", False),
        solution_enabled=data.get("solution_enabled", False),
        fill_enabled=data.get("fill_enabled", False),
        subject=data.get("subject", ""),
        choice_items=_items("choice_items"),
        fill_items=_items("fill_items"),
        solution_items=_items("solution_items"),
    )


class SQLiteTaskRepository(TaskRepository):
    """组卷任务仓储 SQLite 实现。"""

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    def save_task(self, task: GenerationTask) -> None:
        """保存或更新任务及其导出记录。"""
        with self._db.transaction() as conn:
            # 1. 保存主任务
            conn.execute(
                "INSERT INTO generation_tasks (id, criteria, question_ids, total_score, created_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "criteria=excluded.criteria, question_ids=excluded.question_ids, "
                "total_score=excluded.total_score",
                (
                    task.id,
                    json.dumps(_criteria_to_dict(task.criteria), ensure_ascii=False),
                    json.dumps(task.question_ids, ensure_ascii=False),
                    task.total_score,
                    task.created_at.isoformat() if task.created_at else datetime.now().isoformat(),
                )
            )

            # 2. 更新导出记录（先清理旧的，再插入新的）
            conn.execute("DELETE FROM task_exports WHERE task_id = ?", (task.id,))
            for exp in task.export_records:
                conn.execute(
                    "INSERT INTO task_exports (task_id, format, file_path, exported_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        task.id,
                        exp.format.value,
                        exp.file_path,
                        exp.exported_at.isoformat() if exp.exported_at else datetime.now().isoformat(),
                    )
                )

    def get_task(self, task_id: str) -> GenerationTask | None:
        conn = self._db.connect()
        row = conn.execute("SELECT * FROM generation_tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
            
        # 读取导出记录
        exports = []
        exp_rows = conn.execute("SELECT * FROM task_exports WHERE task_id = ?", (task_id,)).fetchall()
        for er in exp_rows:
            exports.append(ExportRecord(
                format=ExportFormat(er["format"]),
                file_path=er["file_path"],
                exported_at=datetime.fromisoformat(er["exported_at"]) if er["exported_at"] else None
            ))

        return GenerationTask(
            id=row["id"],
            criteria=_dict_to_criteria(json.loads(row["criteria"])),
            question_ids=json.loads(row["question_ids"]),
            total_score=row["total_score"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            export_records=exports,
        )

    def list_tasks(self) -> list[GenerationTask]:
        conn = self._db.connect()
        rows = conn.execute("SELECT id FROM generation_tasks ORDER BY created_at DESC").fetchall()
        return [self.get_task(r["id"]) for r in rows if r]
