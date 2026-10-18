import sqlite3
import pytest
from app.infrastructure.database.schema import ensure_schema

@pytest.fixture()
def db_conn():
    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)
    yield conn
    conn.close()

def test_trigger_blocks_invalid_single_choice(db_conn):
    """触发器拦截：单选题选项少于2个时，应报错"""
    with pytest.raises(sqlite3.IntegrityError, match="choice questions require at least 2 options"):
        db_conn.execute(
            "INSERT INTO questions (id, subject, type, stem, options, answer, quality_flag) "
            "VALUES ('test1', '数学', 'single', '测试', '[]', '[]', 'normal')"
        )

def test_trigger_allows_invalid_if_low_quality(db_conn):
    """触发器豁免：如果是 low 质量，允许插入残缺数据（防历史数据死锁）"""
    db_conn.execute(
        "INSERT INTO questions (id, subject, type, stem, options, answer, quality_flag) "
        "VALUES ('test2', '数学', 'single', '测试', '[]', '[]', 'low')"
    )
    row = db_conn.execute("SELECT id FROM questions WHERE id='test2'").fetchone()
    assert row is not None

def test_trigger_blocks_options_for_fill(db_conn):
    """触发器拦截：填空题不应包含选项"""
    with pytest.raises(sqlite3.IntegrityError, match="fill/solution questions must not have options"):
        db_conn.execute(
            "INSERT INTO questions (id, subject, type, stem, options, answer, quality_flag) "
            "VALUES ('test3', '数学', 'fill', '测试', '[{\"key\":\"A\",\"text\":\"x\"}]', '[\"1\"]', 'normal')"
        )
