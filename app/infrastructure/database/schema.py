"""数据库建表语句与迁移。

定义设计文档 "存储表（SQLite）" 章节的全部表结构，应用启动时执行
``ensure_schema`` 完成幂等建表（CREATE TABLE IF NOT EXISTS）。

表清单：

- questions        题目主表
- knowledge_points 知识点字典
- question_usage   题目使用记录（需求 R13）
- generation_tasks 组卷任务（需求 R14）
- task_questions   任务与题目的关联
- task_exports     任务导出记录
- settings         键值配置（AIConfig / ScoringConfig / PromptConfig / 科目列表，需求 R15）
- question_operations 题库操作台账（导入历史 / 编辑历史）

依赖：app.infrastructure.database.connection
被使用：app.container（启动时初始化）
"""

import sqlite3

SCHEMA_STATEMENTS: tuple[str, ...] = (
    # 题目主表：题型 / 难度 / 来源 / 质量标记与需求枚举取值一致
    """
    CREATE TABLE IF NOT EXISTS questions (
        id                TEXT PRIMARY KEY,
        subject           TEXT NOT NULL,
        knowledge_points  TEXT NOT NULL DEFAULT '[]',
        type              TEXT NOT NULL CHECK (type IN ('single', 'multiple', 'solution')),
        stem              TEXT NOT NULL,
        options           TEXT NOT NULL DEFAULT '[]',
        answer            TEXT NOT NULL DEFAULT '[]',
        solution          TEXT,
        difficulty        TEXT NOT NULL DEFAULT 'pending',
        difficulty_source TEXT NOT NULL DEFAULT 'ai',
        quality_flag      TEXT NOT NULL DEFAULT 'normal',
        source            TEXT NOT NULL DEFAULT 'bank',
        image_path        TEXT,
        created_at        TEXT,
        updated_at        TEXT
    )
    """,
    # 知识点字典：科目 -> 知识点，供录入界面下拉与 AI 补题取材
    """
    CREATE TABLE IF NOT EXISTS knowledge_points (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT NOT NULL,
        name    TEXT NOT NULL,
        UNIQUE (subject, name)
    )
    """,
    # 使用记录：近期重复抑制（需求 R13）的数据基础
    """
    CREATE TABLE IF NOT EXISTS question_usage (
        question_id  TEXT PRIMARY KEY REFERENCES questions (id) ON DELETE CASCADE,
        use_count    INTEGER NOT NULL DEFAULT 0,
        last_used_at TEXT
    )
    """,
    # 组卷任务：历史与配置复用（需求 R14）
    """
    CREATE TABLE IF NOT EXISTS generation_tasks (
        id          TEXT PRIMARY KEY,
        criteria    TEXT NOT NULL,
        question_ids TEXT NOT NULL DEFAULT '[]',
        total_score REAL NOT NULL DEFAULT 0,
        created_at  TEXT
    )
    """,
    # 任务导出记录
    """
    CREATE TABLE IF NOT EXISTS task_exports (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id     TEXT NOT NULL REFERENCES generation_tasks (id) ON DELETE CASCADE,
        format      TEXT NOT NULL CHECK (format IN ('txt', 'pdf')),
        file_path   TEXT NOT NULL,
        exported_at TEXT
    )
    """,
    # 键值配置：AIConfig / ScoringConfig 的 JSON 序列化存储（需求 R15）
    """
    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    # 题库操作台账：导入历史 / 编辑历史（用户需求）
    """
    CREATE TABLE IF NOT EXISTS question_operations (
        id           TEXT PRIMARY KEY,
        action       TEXT NOT NULL CHECK (action IN ('create', 'update', 'delete', 'import')),
        question_id  TEXT NOT NULL DEFAULT '',
        subject      TEXT NOT NULL DEFAULT '',
        stem_excerpt TEXT NOT NULL DEFAULT '',
        batch_id     TEXT,
        detail       TEXT NOT NULL DEFAULT '',
        created_at   TEXT
    )
    """,
)

#: 幂等列迁移：(表名, 列名, 列定义)
COLUMN_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    # 题目图片列为后加字段，旧库需补列（用户需求：题目图片导入）
    ("questions", "image_path", "TEXT"),
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """执行幂等建表与补列迁移（应用启动时调用一次）。

    :param conn: 已打开的 SQLite 连接
    """
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    for table, column, definition in COLUMN_MIGRATIONS:
        if not _has_column(conn, table, column):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.commit()


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """判断表中是否已存在某列（旧库兼容用）。"""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)
