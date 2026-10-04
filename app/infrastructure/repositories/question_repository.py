"""SQLiteQuestionRepository：题目仓储的 SQLite 实现。

实现接口：app.interfaces.repositories.QuestionRepository
依赖：app.infrastructure.database.connection.DatabaseConnection、
      app.infrastructure.database.schema（questions / knowledge_points 表）、
      app.domain.entities.question
被使用：app.container（装配给 QuestionService / PaperComposer / QuestionGenerator）
"""

import json
import uuid
from datetime import datetime

from app.domain.entities.question import Option, Question, QuestionFilter
from app.domain.enums import (
    Difficulty,
    DifficultySource,
    QualityFlag,
    QuestionSource,
    QuestionType,
)
from app.infrastructure.database.connection import DatabaseConnection
from app.interfaces.repositories import QuestionRepository


class SQLiteQuestionRepository(QuestionRepository):
    """题目仓储 SQLite 实现：questions 表 + knowledge_points 字典表。"""

    def __init__(self, db: DatabaseConnection) -> None:
        """注入数据库连接管理器。"""
        self._db = db

    # ------------------------------------------------------------------ 写

    def save(self, question: Question) -> Question:
        """新增题目（需求 R1 第 1 条），并同步知识点字典表。"""
        now = datetime.now()
        if not question.id:
            question.id = str(uuid.uuid4())
        question.created_at = question.created_at or now
        question.updated_at = now
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO questions (id, subject, section, knowledge_points, type, stem, "
                "options, answer, solution, difficulty, difficulty_source, quality_flag, "
                "source, image_path, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._to_row(question),
            )
            self._sync_knowledge_points(conn, question)
        return question

    def update(self, question: Question) -> Question:
        """更新题目内容，保留 id 与使用记录（需求 R1 第 3 条）。"""
        question.updated_at = datetime.now()
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE questions SET subject = ?, section = ?, knowledge_points = ?, type = ?, "
                "stem = ?, options = ?, answer = ?, solution = ?, difficulty = ?, "
                "difficulty_source = ?, quality_flag = ?, source = ?, image_path = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    question.subject,
                    question.section,
                    self._dump_json(question.knowledge_points),
                    question.type.value,
                    question.stem,
                    self._dump_json(
                        [{"key": o.key, "text": o.text} for o in question.options]
                    ),
                    self._dump_json(question.answer),
                    question.solution,
                    question.difficulty.value,
                    question.difficulty_source.value,
                    question.quality_flag.value,
                    question.source.value,
                    question.image_path,
                    question.updated_at.isoformat(timespec="seconds"),
                    question.id,
                ),
            )
            self._sync_knowledge_points(conn, question)
        return question

    def delete(self, question_id: str) -> None:
        """删除题目（question_usage 表级联删除，需求 R1 第 4 条）。"""
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM questions WHERE id = ?", (question_id,))

    # ------------------------------------------------------------------ 读

    def get(self, question_id: str) -> Question | None:
        """按 id 读取题目。"""
        row = self._db.connect().execute(
            "SELECT * FROM questions WHERE id = ?", (question_id,)
        ).fetchone()
        return self._row_to_question(row) if row is not None else None

    def search(self, question_filter: QuestionFilter) -> list[Question]:
        """按条件组合检索（需求 R6 第 1 条），动态拼接 WHERE 子句。"""
        clauses: list[str] = []
        params: list[object] = []
        if question_filter.subject:
            clauses.append("subject = ?")
            params.append(question_filter.subject)
        if question_filter.section:
            clauses.append("section = ?")
            params.append(question_filter.section)
        if question_filter.knowledge_point:
            clauses.append("knowledge_points LIKE ?")
            params.append(f"%{question_filter.knowledge_point}%")
        if question_filter.difficulty is not None:
            clauses.append("difficulty = ?")
            params.append(Difficulty(question_filter.difficulty).value)
        if question_filter.question_type is not None:
            clauses.append("type = ?")
            params.append(QuestionType(question_filter.question_type).value)

        sql = "SELECT * FROM questions"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, rowid DESC"
        rows = self._db.connect().execute(sql, params).fetchall()
        return [self._row_to_question(row) for row in rows]

    def count_available(
        self,
        subject: str,
        difficulty: str,
        question_type: str,
        knowledge_points: list[str] | None = None,
    ) -> int:
        """统计命中题数量（需求 R6 第 2 条），供组卷前展示与 AI 补题判断。

        ``knowledge_points`` 非空时按"命中任一指定知识点"过滤（用户需求：
        组卷时可指定知识点）；knowledge_points 列为 JSON 文本，沿用 LIKE 匹配。
        """
        clauses = ["subject = ?", "difficulty = ?", "type = ?"]
        params: list[object] = [
            subject,
            Difficulty(difficulty).value,
            QuestionType(question_type).value,
        ]
        points = [str(point).strip() for point in (knowledge_points or []) if str(point).strip()]
        if points:
            clauses.append(
                "(" + " OR ".join("knowledge_points LIKE ?" for _ in points) + ")"
            )
            params.extend(f"%{point}%" for point in points)
        row = self._db.connect().execute(
            "SELECT COUNT(*) AS total FROM questions WHERE " + " AND ".join(clauses),
            params,
        ).fetchone()
        return int(row["total"]) if row is not None else 0

    def list_subjects(self) -> list[str]:
        """返回题库中已出现过的科目（供设置界面参考，非过滤条件来源）。"""
        rows = self._db.connect().execute(
            "SELECT DISTINCT subject FROM questions ORDER BY subject"
        ).fetchall()
        return [row["subject"] for row in rows]

    def list_knowledge_points(self, subject: str | None = None) -> list[str]:
        """返回知识点字典（可按科目过滤），供录入与检索自动补全。"""
        sql = "SELECT DISTINCT name FROM knowledge_points"
        params: list[object] = []
        if subject:
            sql += " WHERE subject = ?"
            params.append(subject)
        sql += " ORDER BY name"
        rows = self._db.connect().execute(sql, params).fetchall()
        return [row["name"] for row in rows]

    def count_by_type(self) -> dict[str, int]:
        """按题型统计题量（题库概览）。"""
        rows = self._db.connect().execute(
            "SELECT type, COUNT(*) AS total FROM questions GROUP BY type"
        ).fetchall()
        return {row["type"]: int(row["total"]) for row in rows}

    def count_by_image(self, image_path: str) -> int:
        """统计引用同一图片路径的题目数（删除题目时判断图片能否清理）。"""
        row = self._db.connect().execute(
            "SELECT COUNT(*) AS total FROM questions WHERE image_path = ?",
            (image_path,),
        ).fetchone()
        return int(row["total"]) if row is not None else 0

    # ------------------------------------------------------------------ 映射

    def _to_row(self, question: Question) -> tuple:
        """Question 实体 -> questions 表列值元组。

        枚举字段统一经 :meth:`_enum_value` 取值：既接受枚举成员，也接受
        ``"single"`` / ``"easy"`` 这类字符串，避免调用方传入字符串时抛出
        ``'str' object has no attribute 'value'``。
        """
        return (
            question.id,
            question.subject,
            question.section,
            self._dump_json(question.knowledge_points),
            self._enum_value(question.type, QuestionType),
            question.stem,
            self._dump_json(
                [{"key": o.key, "text": o.text} for o in question.options]
            ),
            self._dump_json(question.answer),
            question.solution,
            self._enum_value(question.difficulty, Difficulty),
            self._enum_value(question.difficulty_source, DifficultySource),
            self._enum_value(question.quality_flag, QualityFlag),
            self._enum_value(question.source, QuestionSource),
            question.image_path,
            question.created_at.isoformat(timespec="seconds")
            if question.created_at
            else None,
            question.updated_at.isoformat(timespec="seconds")
            if question.updated_at
            else None,
        )

    @staticmethod
    def _enum_value(value, enum_cls) -> str:
        """枚举成员或等价字符串 -> 数据库存储值。

        :raises ValueError: 取值不在枚举范围内（消息说明字段与合法取值）
        """
        if isinstance(value, enum_cls):
            return value.value
        try:
            return enum_cls(value).value
        except (TypeError, ValueError) as exc:
            allowed = "、".join(member.value for member in enum_cls)
            raise ValueError(
                f"{enum_cls.__name__} 取值非法：{value!r}（可选值：{allowed}）"
            ) from exc

    @staticmethod
    def _row_to_question(row) -> Question:
        """行数据 -> Question 实体（options / answer / knowledge_points 为 JSON 列）。"""
        return Question(
            id=row["id"],
            subject=row["subject"],
            section=row["section"],
            knowledge_points=SQLiteQuestionRepository._load_json(row["knowledge_points"], []),
            type=QuestionType(row["type"]),
            stem=row["stem"],
            options=[
                Option(key=item.get("key", ""), text=item.get("text", ""))
                for item in SQLiteQuestionRepository._load_json(row["options"], [])
            ],
            answer=SQLiteQuestionRepository._load_json(row["answer"], []),
            solution=row["solution"],
            difficulty=Difficulty(row["difficulty"]),
            difficulty_source=DifficultySource(row["difficulty_source"]),
            quality_flag=QualityFlag(row["quality_flag"]),
            source=QuestionSource(row["source"]),
            image_path=row["image_path"],
            created_at=SQLiteQuestionRepository._parse_dt(row["created_at"]),
            updated_at=SQLiteQuestionRepository._parse_dt(row["updated_at"]),
        )

    @staticmethod
    def _load_json(raw, default):
        """JSON 文本 -> Python 对象；解析失败返回默认值（旧数据容错）。"""
        if raw in (None, ""):
            return default
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_dt(raw) -> datetime | None:
        """ISO 文本 -> datetime；解析失败返回 None。"""
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _dump_json(value) -> str:
        """列表字段序列化为 JSON 文本（写入 TEXT 列）。"""
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _sync_knowledge_points(conn, question: Question) -> None:
        """把题目的知识点写入字典表（供后续录入下拉与 AI 补题取材）。"""
        for name in question.knowledge_points:
            conn.execute(
                "INSERT OR IGNORE INTO knowledge_points (subject, name) VALUES (?, ?)",
                (question.subject, name),
            )
