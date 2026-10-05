"""TxtExporter 单元测试：Markdown 排版、知识板块与答案页。

导出会在目标目录写文件，用 pytest 的 ``tmp_path`` 作为导出目录。

依赖：pytest、app.application.score_calculator、
      app.infrastructure.exporters.txt_exporter
被使用：python -m pytest tests/test_txt_exporter.py
"""

from pathlib import Path

from app.application.score_calculator import ScoreCalculator
from app.domain.entities.configs import ExportOptions
from app.domain.entities.criteria import PaperCriteria, TypeRequirement
from app.domain.entities.paper import Paper, Section
from app.domain.entities.question import Option, Question
from app.domain.enums import Difficulty, QuestionType, SectionKind
from app.infrastructure.exporters.txt_exporter import TxtExporter


def _single_question(section: str) -> Question:
    """构造一道用于导出的单选题。"""
    return Question(
        id="q-1",
        subject="数学",
        section=section,
        knowledge_points=["一元二次方程"],
        type=QuestionType.SINGLE,
        stem="下列方程是一元二次方程的是？",
        options=[Option("A", "x+1=0"), Option("B", "x^2-1=0")],
        answer=["B"],
        solution="含二次项",
        difficulty=Difficulty.EASY,
    )


def _paper(question: Question) -> Paper:
    """构造只含一道单选题（统一 2 分）的试卷，并生成答案页数据。"""
    section = Section(
        section_kind=SectionKind.CHOICE,
        question_type=QuestionType.SINGLE,
        questions=[question],
        per_question_score=2.0,
    )
    paper = Paper(
        criteria=PaperCriteria(
            choice_enabled=True,
            subject="数学",
            choice_items=[
                TypeRequirement(QuestionType.SINGLE, "数学", Difficulty.EASY, 1)
            ],
        ),
        sections=[section],
    )
    calculator = ScoreCalculator()
    calculator.build_answer_page(paper)
    paper.total_score = calculator.total_score(paper)
    return paper


def _read(path: str) -> str:
    """读取导出文件全文。"""
    return Path(path).read_text(encoding="utf-8")


def test_export_writes_markdown_with_knowledge_section(tmp_path) -> None:
    """导出文件为 Markdown 文本，并带上题面的知识板块（用户需求）。"""
    path = TxtExporter().export(_paper(_single_question("代数")), str(tmp_path))
    text = _read(path)

    assert path.endswith(".txt")
    assert text.startswith("# 试卷")
    assert "**总分：2 分**" in text
    assert "知识板块：代数" in text
    assert "1. 下列方程是一元二次方程的是？" in text
    assert "   - B. x^2-1=0" in text
    assert "# 答案页" in text
    assert "1. B" in text


def test_export_without_section_omits_the_line(tmp_path) -> None:
    """题目未填知识板块时不输出板块行。"""
    path = TxtExporter().export(
        _paper(_single_question("")), str(tmp_path), ExportOptions()
    )
    assert "知识板块：" not in _read(path)
