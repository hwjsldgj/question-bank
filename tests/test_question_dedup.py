"""题库自动去重测试：题干指纹、重复分组、入库拦截与全库清理。

覆盖用户需求：题库自动去重（题干归一化后相同即视为重复题）——

- 录入 / 编辑保存前查重，命中时拒绝入库（用户确认后可"仍然保存"）
- 批量粘贴导入时先给出预检结果，入库时自动跳过重复题（含批次内重复）
- 检索页"全库去重"扫描重复分组，每组保留最早录入的一道并删除其余

依赖：pytest、app.application.question_service、app.domain.entities.duplicate、
      app.domain.entities.question、app.infrastructure.database.schema
被使用：python -m pytest tests/test_question_dedup.py
"""

from datetime import datetime

import pytest

from app.application.difficulty_service import DifficultyService
from app.application.question_service import QuestionService
from app.container import build_container
from app.domain.entities.duplicate import group_duplicates
from app.domain.entities.question import (
    Option,
    Question,
    QuestionFilter,
    stem_fingerprint,
)
from app.domain.enums import Difficulty, QuestionOpAction, QuestionType
from app.domain.errors import DuplicateQuestionError, QuestionValidationError
from app.domain.validators.question_validator import QuestionValidator
from app.infrastructure.database.schema import ensure_schema


@pytest.fixture()
def container(tmp_path):
    """临时库上的完整对象图（含建表）。"""
    graph = build_container(str(tmp_path / "dedup.db"))
    ensure_schema(graph.db.connect())
    yield graph
    graph.db.close()


@pytest.fixture()
def service(container) -> QuestionService:
    """题目服务（含操作台账，验证去重删除会写入历史）。"""
    return QuestionService(
        container.question_repository,
        QuestionValidator(),
        DifficultyService(container.ai_client, container.config_store),
        op_repository=container.question_op_repository,
        config_store=container.config_store,
    )


def _choice(stem: str, points: list[str] | None = None) -> Question:
    """构造一道合法单选题（只关心题干时用，其余字段固定）。"""
    return Question(
        id="",
        subject="数学",
        knowledge_points=points or ["集合"],
        type=QuestionType.SINGLE,
        stem=stem,
        options=[Option("A", "1"), Option("B", "2")],
        answer=["A"],
        difficulty=Difficulty.MEDIUM,
    )


# ------------------------------------------------------------------ 题干指纹


def test_stem_fingerprint_ignores_whitespace_punctuation_and_width() -> None:
    """题干指纹忽略空白、标点、全角半角与大小写差异（用户需求）。"""
    reference = stem_fingerprint("x^2-1=0 的解是？")
    assert stem_fingerprint("x^2 - 1 = 0的解是?") == reference
    assert stem_fingerprint("Ｘ^2-1=0的解是!") == reference
    assert stem_fingerprint("  x^2-1=0。的解是  ") == reference


def test_stem_fingerprint_keeps_math_symbols_and_content() -> None:
    """数学符号不参与忽略，题干内容不同则指纹不同（避免误判重复）。"""
    assert stem_fingerprint("x+1") != stem_fingerprint("x1")
    assert stem_fingerprint("甲的年龄") != stem_fingerprint("乙的年龄")
    assert stem_fingerprint("   ") == ""


# ------------------------------------------------------------------ 重复分组


def test_group_duplicates_keeps_earliest_entry() -> None:
    """分组保留最早录入的一道，其余按录入时间排序为待删除项。"""
    newest = _choice("1+1=?")
    newest.id = "new"
    newest.created_at = datetime(2026, 1, 2, 10, 0, 0)
    oldest = _choice("1+1=?")
    oldest.id = "old"
    oldest.created_at = datetime(2026, 1, 1, 10, 0, 0)
    unique = _choice("唯一的题干")
    unique.id = "unique"

    # 传入顺序与 repository.search 一致（新 -> 旧）
    groups = group_duplicates([newest, oldest, unique])
    assert len(groups) == 1
    assert groups[0].keeper.id == "old"
    assert [question.id for question in groups[0].duplicates] == ["new"]
    assert groups[0].size == 2


def test_group_duplicates_same_second_keeps_first_inserted() -> None:
    """同秒入库时（search 为倒序）保留列表中靠后的那道，即先入库的题目。"""
    same_time = datetime(2026, 1, 2, 10, 0, 0)
    later = _choice("2+2=?")
    later.id = "later"
    later.created_at = same_time
    earlier = _choice("2+2=?")
    earlier.id = "earlier"
    earlier.created_at = same_time

    groups = group_duplicates([later, earlier])
    assert groups[0].keeper.id == "earlier"


# ------------------------------------------------------------------ 入库拦截


def test_create_question_rejects_duplicate(service) -> None:
    """新增题目时题干与题库已有题目重复 -> 拒绝入库并给出定位信息。"""
    saved = service.create_question(_choice("x^2-1=0 的解是？"))

    with pytest.raises(DuplicateQuestionError) as excinfo:
        # 仅空白 / 标点不同，仍判定为重复题
        service.create_question(_choice("x^2 - 1 = 0的解是?"))
    assert saved.id in str(excinfo.value)
    assert service.statistics()["total"] == 1


def test_create_question_allows_duplicate_when_confirmed(service) -> None:
    """用户在"仍然保存"弹窗中确认后（allow_duplicate=True）可保留重复题。"""
    service.create_question(_choice("x^2-1=0 的解是？"))
    service.create_question(_choice("x^2-1=0 的解是？"), allow_duplicate=True)
    assert service.statistics()["total"] == 2


def test_update_question_rejects_duplicate_but_allows_itself(service) -> None:
    """编辑为他人题干 -> 拦截；题干未变（与自身相同）不算重复。"""
    first = service.create_question(_choice("第一题的题干"))
    second = service.create_question(_choice("第二题的题干"))

    with pytest.raises(DuplicateQuestionError):
        service.update_question(second.id, {"stem": "第一题的题干"})

    same = service.update_question(second.id, {"stem": "第二题的题干"})
    assert same.stem == "第二题的题干"
    assert same.id == second.id
    assert first.id != second.id


def test_duplicate_drafts_reports_batch_and_bank_duplicates(service) -> None:
    """批量导入预检：既报出与题库重复的候选题，也报出批次内重复的候选题。"""
    existing = service.create_question(_choice("题库已有题"))

    drafts = [
        _choice("新题甲"),
        _choice("新题甲"),  # 与第 1 道候选题重复
        _choice("题库已有题"),  # 与题库重复
    ]
    duplicates = service.duplicate_drafts(drafts)
    assert [item[0] for item in duplicates] == [2, 3]
    assert duplicates[0][2] is None  # 批次内重复
    assert duplicates[1][2].id == existing.id  # 命中题库题目


def test_batch_commit_skips_duplicates(service) -> None:
    """批量入库自动跳过重复题（批次内 + 与题库重复），只写入新题。"""
    service.create_question(_choice("题库已有题"))
    drafts = [
        _choice("新题甲"),
        _choice("新题甲"),
        _choice("题库已有题"),
        _choice("新题乙"),
    ]

    committed = service.batch_commit(drafts)
    assert [question.stem for question in committed] == ["新题甲", "新题乙"]
    assert service.statistics()["total"] == 3
    assert service.scan_duplicates() == []
    # 跳过项不写台账，只有真正入库的两道记录导入历史
    assert len(service.list_operations([QuestionOpAction.IMPORT])) == 2


# ------------------------------------------------------------------ 全库清理


def test_scan_and_deduplicate_keeps_earliest(service) -> None:
    """全库扫描 + 清理：每组保留最早录入的一道，其余删除。"""
    kept = service.create_question(_choice("重复题干"))
    service.create_question(_choice("重复题干"), allow_duplicate=True)
    service.create_question(_choice("重复题干  "), allow_duplicate=True)
    unique = service.create_question(_choice("唯一题干"))

    groups = service.scan_duplicates()
    assert len(groups) == 1
    assert groups[0].size == 3
    assert groups[0].keeper.id == kept.id

    report = service.deduplicate(groups, confirmed=True)
    assert report.group_count == 1
    assert report.deleted_count == 2
    remaining = {question.id for question in service.search(QuestionFilter())}
    assert remaining == {kept.id, unique.id}
    assert service.scan_duplicates() == []


def test_deduplicate_requires_confirmation(service) -> None:
    """全库去重是破坏性操作，未经确认拒绝执行。"""
    service.create_question(_choice("重复题干"))
    service.create_question(_choice("重复题干"), allow_duplicate=True)

    with pytest.raises(QuestionValidationError):
        service.deduplicate()
    assert service.statistics()["total"] == 2


def test_deduplicate_records_operation(service) -> None:
    """去重删除写入题库操作台账，便于事后追溯（用户需求：操作历史）。"""
    kept = service.create_question(_choice("重复题干"))
    service.create_question(_choice("重复题干"), allow_duplicate=True)

    service.deduplicate(service.scan_duplicates(), confirmed=True)
    deletions = service.list_operations([QuestionOpAction.DELETE])
    assert len(deletions) == 1
    assert "自动去重" in deletions[0].detail
    assert kept.id in deletions[0].detail
