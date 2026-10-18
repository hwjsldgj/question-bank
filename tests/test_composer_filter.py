import pytest
from app.domain.entities.question import Question, QuestionFilter
from app.domain.enums import QuestionType, Difficulty
from app.infrastructure.repositories.question_repository import SQLiteQuestionRepository
from app.infrastructure.database.connection import DatabaseConnection
from app.infrastructure.database.schema import ensure_schema

@pytest.fixture
def repo(tmp_path):
    db_path = tmp_path / "test_filter.db"
    db = DatabaseConnection(str(db_path))
    ensure_schema(db.connect())
    return SQLiteQuestionRepository(db)

def test_exclude_low_quality(repo):
    """测试在组卷查询时，是否正确排除了 quality_flag='low' 的题目"""
    # 插入一道 normal 题
    q1 = Question(id="A000001", subject="数学", type=QuestionType.FILL, stem="正常题", answer=["1"], quality_flag="normal")
    repo.save(q1)
    
    # 插入一道 low 题
    q2 = Question(id="A000002", subject="数学", type=QuestionType.FILL, stem="残缺题", answer=["1"], quality_flag="low")
    repo.save(q2)

    # 不加过滤条件，应该查出两道
    results_all = repo.search(QuestionFilter(subject="数学"))
    assert len(results_all) == 2

    # 加过滤条件，应该只查出一道（排除 low）
    results_filtered = repo.search(QuestionFilter(subject="数学", exclude_low_quality=True))
    assert len(results_filtered) == 1
    assert results_filtered[0].id == "A000001"
