"""MdExporter 单元测试：Markdown 格式（对齐参考稿）、答案分页与 PDF 的 HTML 方案。

导出会在目标目录写文件，用 pytest 的 ``tmp_path`` 作为导出目录。

依赖：pytest、app.application.score_calculator、
      app.infrastructure.exporters.md_exporter、app.infrastructure.exporters.pdf_exporter
被使用：python -m pytest tests/test_md_exporter.py
"""

from pathlib import Path

import pytest

from app.application.score_calculator import ScoreCalculator
from app.domain.entities.configs import ExportOptions
from app.domain.entities.criteria import PaperCriteria, TypeRequirement
from app.domain.entities.paper import Paper, Section
from app.domain.entities.question import Option, Question
from app.domain.enums import Difficulty, QuestionType, SectionKind
from app.infrastructure.exporters.md_exporter import PAGE_BREAK, MdExporter
from app.infrastructure.exporters.pdf_exporter import render_html, resolve_browser


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
    """导出文件为同名 .md，格式与参考稿一致（用户需求）。"""
    path = MdExporter().export(_paper(_single_question("代数")), str(tmp_path))
    lines = _read(path).splitlines()

    assert path.endswith(".md")
    assert lines[0] == "# 试卷"
    assert lines[2] == "**总分：2 分**"
    assert lines[4] == "## 一、选择题部分（单选题）"
    assert lines[6] == "共 1 题，每题 2 分，小计 2 分。  "  # 两个空格 = Markdown 硬换行
    assert lines[7] == "知识点板块：代数。"
    assert lines[9] == "1. 下列方程是一元二次方程的是？  "
    assert lines[10] == "   A. x+1=0  "
    assert lines[11] == "   B. x^2-1=0"  # 块内末行不加硬换行
    assert "# 答案页" in lines
    assert "1. B  " in lines
    assert "   解析：含二次项" in lines


def test_export_without_section_omits_the_line(tmp_path) -> None:
    """题目未填知识点板块时不输出板块行。"""
    path = MdExporter().export(
        _paper(_single_question("")), str(tmp_path), ExportOptions()
    )
    assert "知识点板块：" not in _read(path)


def test_export_creates_default_dir_when_missing(tmp_path) -> None:
    """导出目录由程序创建：目录不存在时自动建好（用户需求）。"""
    target = tmp_path / "exports"
    assert not target.exists()
    path = MdExporter().export(_paper(_single_question("代数")), str(target))
    assert target.is_dir()
    assert Path(path).parent == target


def test_answer_page_starts_on_new_page(tmp_path) -> None:
    """答案页前插入单独一行的分页标记（参考稿格式，用户需求：答案分页）。"""
    paper = _paper(_single_question("代数"))
    path = MdExporter().export(paper, str(tmp_path))
    lines = _read(path).splitlines()

    assert lines.count(PAGE_BREAK) == 1  # 只在答案页前分页
    index = lines.index(PAGE_BREAK)
    assert lines[index - 1] == "" and lines[index + 1] == ""  # 独占一行
    assert lines[index + 2] == "# 答案页"
    # 答案页内不再重复分页
    assert PAGE_BREAK not in lines[index + 2 :]


def test_html_render_has_mathjax_and_pagebreak_css(tmp_path) -> None:
    """PDF 走参考实现的 HTML 方案：MathJax、中文字体与 .pagebreak 分页 CSS 齐备。"""
    html = render_html(_read(MdExporter().export(_paper(_single_question("代数")), str(tmp_path))))
    assert "<!DOCTYPE html>" in html
    assert "mathjax" in html.lower()          # 公式渲染
    assert "Microsoft YaHei" in html          # 中文字体（CSS 指定，不会乱码）
    assert ".pagebreak" in html               # 分页规则
    assert "page-break-after: always" in html


def test_pdf_browser_is_resolved_or_reported() -> None:
    """能定位到 Edge 可执行文件；找不到时由导出流程给出可读提示。"""
    browser = resolve_browser()
    if browser is None:
        pytest.skip("本机未安装 Edge，跳过浏览器路径断言")
    assert Path(browser).is_file()
    assert browser.lower().endswith("msedge.exe")
