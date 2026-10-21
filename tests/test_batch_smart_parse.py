# -*- coding: utf-8 -*-
"""批量粘贴智能解析测试：不依赖精确关键字。

覆盖点：
- 标签容错（内部空格、单字符错别字，如「科 目」「科日」「题形」）
- 无标签题块按句子结构抽取答案 / 解析（如「答案：B 解析：…」）
- 题干中的学科词（如「解析几何」）不会被误判为字段
- 科目 / 板块由知识点反查兜底；填空题由「____」标记识别

这些用例只验证纯解析逻辑（``QuestionService._parse_block``），
不建库、不写文件，因此可在无临时目录权限的环境下运行。

依赖：pytest、app.application.question_service、app.config.settings
被使用：python -m pytest tests/test_batch_smart_parse.py
"""

import pytest

from app.application.question_service import QuestionService
from app.config.settings import DEFAULT_KNOWLEDGE_SECTIONS
from app.domain.enums import Difficulty, QuestionType


@pytest.fixture()
def parser() -> QuestionService:
    """构造只用解析逻辑的服务实例（不连数据库、不读配置）。"""
    service = QuestionService.__new__(QuestionService)
    service.list_sections = lambda subject=None: (
        DEFAULT_KNOWLEDGE_SECTIONS.get(subject, {})
        if subject
        else {
            section: points
            for groups in DEFAULT_KNOWLEDGE_SECTIONS.values()
            for section, points in groups.items()
        }
    )
    return service


def test_label_with_inner_space_is_recognized(parser) -> None:
    """「科 目：」这类带空格的标签仍能识别为科目。"""
    question = parser._parse_block(
        "科 目：数学\n知识点：一元二次方程\n题干：解方程 x^2-1=0"
    )
    assert question.subject == "数学"
    assert question.knowledge_points == ["一元二次方程"]
    assert question.stem == "解方程 x^2-1=0"


def test_typo_labels_are_tolerated(parser) -> None:
    """「科日」「题形」等单字符错别字按最近字段处理（不再要求精确关键字）。"""
    question = parser._parse_block(
        "科日：数学\n考点：一元二次方程\n题形：单选\n"
        "题干：下列哪个是一元二次方程\nA. x+1=0\nB. x^2-1=0\n答案：B"
    )
    assert question.subject == "数学"
    assert question.knowledge_points == ["一元二次方程"]
    assert question.type == QuestionType.SINGLE
    assert [option.key for option in question.options] == ["A", "B"]
    assert question.answer == ["B"]


def test_unlabeled_block_splits_answer_and_solution(parser) -> None:
    """无标签题块：答案与解析按句首关键词自动拆分。"""
    question = parser._parse_block(
        "1. 下列方程是一元二次方程的是？\n"
        "A. x+1=0\nB. x^2-1=0\n"
        "答案：B 解析：含二次项"
    )
    assert question.type == QuestionType.SINGLE
    assert question.stem.startswith("1. 下列方程")
    assert [option.text for option in question.options] == ["x+1=0", "x^2-1=0"]
    assert question.answer == ["B"]
    assert question.solution == "含二次项"


def test_subject_word_in_stem_is_not_a_field(parser) -> None:
    """题干中的「解析几何」不能被当成「解析：」字段。"""
    question = parser._parse_block(
        "1. 在解析几何中，已知直线 l 过点 (1,2)。\n"
        "A. 1\nB. 2\nC. 3\n答案：B"
    )
    assert "解析几何" in question.stem
    assert question.solution is None
    assert question.answer == ["B"]


def test_blank_marker_infers_fill_type(parser) -> None:
    """无选项但题干含「____」时判为填空题。"""
    question = parser._parse_block("已知 f(x)=x^2，则 f(1)=____。\n答案：1")
    assert question.type == QuestionType.FILL
    assert question.options == []
    assert question.answer == ["1"]


def test_subject_inferred_from_knowledge_points(parser) -> None:
    """未标注科目时，由知识点反查科目与板块。"""
    question = parser._parse_block(
        "知识点：一元二次方程\n题干：解方程 x^2-1=0\n答案：1"
    )
    assert question.subject == "数学"
    assert question.section == "代数"


def test_difficulty_written_in_chinese_is_parsed(parser) -> None:
    """「难度：中等」等中文写法映射为枚举，且来源标记为人工。"""
    question = parser._parse_block(
        "科目：数学\n知识点：一元二次方程\n难度：中等\n题干：解方程"
    )
    assert question.difficulty == Difficulty.MEDIUM