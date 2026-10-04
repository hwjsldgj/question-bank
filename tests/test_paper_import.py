"""试卷文件导入测试：Typst（.typ）结构化解析与 PDF 文本提取。

覆盖用户需求：题库可直接导入读取 .typ 试卷文件与 .pdf 试卷文件。
Typst 用例覆盖题型映射、元数据科目、题干 / 选项 / 答案 / 解析提取、
解答题子问合并与 Typst 标记文本转换；PDF 用例验证文本层提取与错误提示。
"""

from pathlib import Path

import pytest

from app.application.paper_import import (
    extract_pdf_text,
    extract_show_metadata,
    parse_typ_source,
)
from app.domain.enums import QuestionType

#: 一份精简但覆盖四类题型的 Typst 试卷（参考高考数学试卷源码格式）
TYP_SAMPLE = """\
#import "/src/lib.typ": (
  cetz, choice-placeholder, exam, fill-placeholder, question, section, step,
  subquestion,
)
#show: exam.with(
  subject: "数学",
  year: 2026,
  type: "普通高等学校招生全国统一考试",
  name: "全国一卷",
)
#section[选择题：本题共 8 小题，每小题 5 分，共 40 分。]
#question(
  "single-choice",
  stem: [样本数据 $6, 8, 4, 5, 12$ 的中位数为#choice-placeholder()],
  choices: ([$5$], [$6$], [$8$], [$9$]),
  answers: ([B],),
  explanation: [将数据从小到大排列为 $4, 5, 6, 8, 12$，中间的数为 $6$，故选 B。],
)
#question(
  "multiple-choice",
  stem: [设 $z = 3 + 2i$，则#choice-placeholder()],
  choices: (
    [$overline(z) = 3 - 2i$],
    [$abs(z) = 5$],
    [$z^2 = 5 + 12i$],
    [$(z + 3)/(z - i) in RR$],
  ),
  answers: ([ACD],),
  explanation: [故选 ACD。],
)
#question(
  "fill-in",
  stem: [双曲线 $5x^2 - 6y^2 = 1$ 的离心率为#fill-placeholder()。],
  answers: ([$sqrt(66)/6$],),
  explanation: [双曲线的标准方程为 $x^2/(1/5) - y^2/(1/6) = 1$。],
)
#question(
  "solution",
  score: 13,
  stem: [如图，在直三棱柱 $A B C - A_1 B_1 C_1$ 中，$angle A C B = 90 degree$，$A C = B C$。
    #figure(prism-figure())
  ],
  parts: (
    subquestion(
      stem: [证明：$D E parallel$ 平面 $B C C_1 B_1$；],
      answers: ([$D E parallel$ 平面 $B C C_1 B_1$，证明见解析。],),
      explanation: [连接 $B C_1$。$therefore D E parallel B C_1$。],
    ),
    subquestion(
      stem: [设 $C C_1 = 2$，求直线 $D E$ 到平面 $B C C_1 B_1$ 的距离。],
      answers: ([$1$],),
      explanation: [建立空间直角坐标系。],
    ),
  ),
)
"""


def test_extract_show_metadata() -> None:
    """试卷元数据：科目 / 年份 / 考试类型 / 卷名。"""
    meta = extract_show_metadata(TYP_SAMPLE)
    assert meta["subject"] == "数学"
    assert meta["year"] == "2026"
    assert meta["type"] == "普通高等学校招生全国统一考试"
    assert meta["name"] == "全国一卷"


def test_parse_typ_source_returns_four_types() -> None:
    """四类题型全部解析为草稿，科目取自试卷元数据。"""
    drafts = parse_typ_source(TYP_SAMPLE)
    assert [draft.type for draft in drafts] == [
        QuestionType.SINGLE,
        QuestionType.MULTIPLE,
        QuestionType.FILL,
        QuestionType.SOLUTION,
    ]
    assert all(draft.subject == "数学" for draft in drafts)


def test_parse_single_choice() -> None:
    """单选：题干去占位符、选项 A-D、答案标号、解析转纯文本。"""
    draft = parse_typ_source(TYP_SAMPLE)[0]
    assert draft.stem == "样本数据 6, 8, 4, 5, 12 的中位数为"
    assert [(o.key, o.text) for o in draft.options] == [
        ("A", "5"),
        ("B", "6"),
        ("C", "8"),
        ("D", "9"),
    ]
    assert draft.answer == ["B"]
    assert "中间的数为 6" in (draft.solution or "")


def test_parse_multiple_choice() -> None:
    """多选：答案合并为多标号，选项正文来自数学块。"""
    draft = parse_typ_source(TYP_SAMPLE)[1]
    assert draft.answer == ["ACD"]
    assert draft.options[1].text == "abs(z) = 5"


def test_parse_fill_in() -> None:
    """填空：无选项，答案为参考答案文本。"""
    draft = parse_typ_source(TYP_SAMPLE)[2]
    assert draft.options == []
    assert draft.answer == ["sqrt(66)/6"]
    assert "离心率为" in draft.stem


def test_parse_solution_merges_parts() -> None:
    """解答题：子问（subquestion）并入题干与答案，解析同样合并。"""
    draft = parse_typ_source(TYP_SAMPLE)[3]
    assert draft.options == []
    assert "（1）证明：D E parallel 平面" in draft.stem
    assert "（2）设 C C_1 = 2" in draft.stem
    assert draft.answer == [
        "（1）D E parallel 平面 B C C_1 B_1，证明见解析。",
        "（2）1",
    ]
    assert "（1）连接 B C_1" in (draft.solution or "")
    assert "（2）建立空间直角坐标系" in (draft.solution or "")


def test_parse_typ_with_subject_hint() -> None:
    """无元数据时使用科目兜底值；未知题型被跳过。"""
    source = (
        '#show: exam.with(type: "测试")\n'
        '#question("single-choice", stem: [x], choices: ([1], [2]), '
        'answers: ([A],), explanation: [e])\n'
        '#question("unknown-type", stem: [y])\n'
    )
    drafts = parse_typ_source(source, subject_hint="物理")
    assert len(drafts) == 1
    assert drafts[0].subject == "物理"
    assert drafts[0].answer == ["A"]


def test_pdf_text_extraction(tmp_path) -> None:
    """PDF：文本层试卷可提取全文（供编辑后走批量粘贴解析）。"""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    pdf_path = Path(tmp_path) / "paper.pdf"
    c = canvas.Canvas(str(pdf_path))
    c.setFont("STSong-Light", 14)
    c.drawString(72, 720, "科目：数学")
    c.drawString(72, 700, "题型：单选")
    c.save()

    text = extract_pdf_text(str(pdf_path))
    assert "科目：数学" in text
    assert "题型：单选" in text


def test_pdf_missing_file_raises(tmp_path) -> None:
    """PDF：文件不存在 / 无法打开时给出可读错误。"""
    with pytest.raises(ValueError, match="无法打开"):
        extract_pdf_text(str(tmp_path / "missing.pdf"))
