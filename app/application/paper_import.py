#!/usr/bin/env python3
"""试卷文件导入：.typ（Typst）与 .pdf 试卷解析为题库草稿。

Typst 试卷（如高考数学试卷，gaokaomath 等项目）源码形如::

    #show: exam.with(
      subject: "数学",
      year: 2026,
      type: "普通高等学校招生全国统一考试",
      name: "全国一卷",
    )
    #section[选择题：本题共 8 小题…]
    #question(
      "single-choice",
      stem: [样本数据 $6, 8, 4, 5, 12$ 的中位数为#choice-placeholder()],
      choices: ([$5$], [$6$], [$8$], [$9$]),
      answers: ([B],),
      explanation: [将数据从小到大排列…],
    )
    #question(
      "solution",
      score: 13,
      stem: […],
      parts: (
        subquestion(
          stem: [证明：…],
          answers: ([…],),
          explanation: […],
        ),
      ),
    )

本模块做**结构解析**：识别 ``#question(...)`` 调用，提取题型 / 题干 / 选项 /
答案 / 解析，并把 Typst 标记文本（``$…$`` 数学、``#…`` 调用、``*强调*`` 等）
转换为可读纯文本；科目优先取 ``exam.with(subject: …)`` 元数据。解析结果
直接进入"批量粘贴 -> 预览 -> 确认提交"流程。

PDF 试卷为排版后导出的文档，文本结构不再保留源码语义，本模块只提供
:func:`extract_pdf_text` 提取全文，由出题者编辑后复用既有"批量粘贴解析"
流程入库（PDF 中的公式 / 图形无法可靠还原）。

依赖：app.domain.entities.question、app.domain.enums、pypdf（可选，PDF 用）
被使用：app.presentation.views.question_bank_view
"""

from __future__ import annotations

import re

from app.domain.entities.question import Option, Question
from app.domain.enums import Difficulty, QuestionType

#: Typst 题型取值 -> 领域题型
_TYPST_TYPE_WORDS: dict[str, QuestionType] = {
    "single-choice": QuestionType.SINGLE,
    "single_choice": QuestionType.SINGLE,
    "multiple-choice": QuestionType.MULTIPLE,
    "multiple_choice": QuestionType.MULTIPLE,
    "fill-in": QuestionType.FILL,
    "fill_in": QuestionType.FILL,
    "solution": QuestionType.SOLUTION,
    "single": QuestionType.SINGLE,
    "multiple": QuestionType.MULTIPLE,
    "fill": QuestionType.FILL,
}

#: 忽略其内容块、不进入题目文本的调用名（排版 / 占位 / 图形）
_IGNORED_CALLS = {
    "choice-placeholder",
    "fill-placeholder",
    "figure",
    "cetz",
    "canvas",
    "space-axes",
    "grid",
    "import",
    "show",
    "set",
    "let",
    "range",
    "circle",
    "line",
    "plot",
    "content",
    "align",
    "text",
    "table",
}

#: 需要把内容块当正文提取的调用名（标题化结构，如 #step[…][…]）
_TEXT_CALLS = {"step", "subquestion"}


def _find_matching(text: str, start: int, open_ch: str, close_ch: str) -> int:
    """从 ``start`` 起找到与 ``open_ch`` 配对的 ``close_ch`` 位置（考虑嵌套与字符串）。"""
    depth = 0
    in_str: str | None = None
    for index in range(start, len(text)):
        ch = text[index]
        if in_str:
            if ch == in_str:
                in_str = None
            continue
        if ch in ('"', "'"):
            in_str = ch
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return index
    return -1


def _split_top_level(text: str, sep: str = ",") -> list[str]:
    """按顶层分隔符拆分（括号 / 内容块 / 字符串内的分隔符不计入）。"""
    parts: list[str] = []
    depth = 0
    in_str: str | None = None
    current: list[str] = []
    for ch in text:
        if in_str:
            current.append(ch)
            if ch == in_str:
                in_str = None
            continue
        if ch in ('"', "'"):
            in_str = ch
            current.append(ch)
            continue
        if ch in "([{":
            depth += 1
            current.append(ch)
        elif ch in ")]}":
            depth -= 1
            current.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return [part for part in parts if part]


def _iter_call_sites(source: str, name: str):
    """迭代源码中 ``#name(...)`` 调用的完整文本（词边界匹配，跳过注释）。"""
    pattern = re.compile(r"#\b" + re.escape(name) + r"\b")
    search_from = 0
    while True:
        match = pattern.search(source, search_from)
        if match is None:
            return
        index = match.start()
        # 跳过注释行（// …）
        line_start = source.rfind("\n", 0, index) + 1
        if source[line_start:index].lstrip().startswith("//"):
            search_from = match.end()
            continue
        cursor = match.end()
        while cursor < len(source) and source[cursor] in " \t\n":
            cursor += 1
        if cursor < len(source) and source[cursor] == "(":
            end = _find_matching(source, cursor, "(", ")")
            if end >= 0:
                yield source[index : end + 1]
                search_from = end + 1
                continue
        search_from = match.end()


def _parse_call(call_text: str) -> tuple[list[str], dict[str, str]]:
    """解析 ``#name(...)`` / ``name(...)`` 调用：返回 (位置参数, 命名参数字典)。"""
    open_at = call_text.find("(")
    if open_at < 0:
        return [], {}
    end = _find_matching(call_text, open_at, "(", ")")
    if end < 0:
        end = len(call_text) - 1
    inner = call_text[open_at + 1 : end]
    positional: list[str] = []
    named: dict[str, str] = {}
    for part in _split_top_level(inner):
        colon = part.find(":")
        if colon > 0 and part[:colon].strip().isidentifier():
            named[part[:colon].strip()] = part[colon + 1 :].strip()
        else:
            positional.append(part)
    return positional, named


def _content_value(value: str) -> str:
    """取 ``[...]`` 内容块的内部文本；非内容块原样返回。"""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        end = _find_matching(value, 0, "[", "]")
        if end == len(value) - 1:
            return value[1:end]
    return value


def _tuple_values(value: str) -> list[str]:
    """把 ``(a, b, c)`` 拆为元素列表；非元组按单元素处理。"""
    value = value.strip()
    if value.startswith("(") and value.endswith(")"):
        end = _find_matching(value, 0, "(", ")")
        if end == len(value) - 1:
            return [part.strip() for part in _split_top_level(value[1:end]) if part.strip()]
    return [value]


def _typ_text(content: str) -> str:
    """把 Typst 内容块转换为可读纯文本（数学 / 调用 / 强调逐类处理）。"""
    out: list[str] = []
    index = 0
    length = len(content)
    while index < length:
        ch = content[index]
        if ch == "$":
            # 数学块：保留内部文本，去掉 # 调用与空白压缩
            end = content.find("$", index + 1)
            if end < 0:
                out.append(content[index:])
                break
            out.append(_math_text(content[index + 1 : end]))
            index = end + 1
        elif ch == "#":
            match = re.match(r"#([A-Za-z_][A-Za-z0-9_\-]*)", content[index:])
            if match is None:
                out.append(ch)
                index += 1
                continue
            name = match.group(1)
            # match 基于 content[index:] 子串，位置需换算回原串绝对下标
            pieces, cursor = _consume_call_args(content, index + match.end())
            if name in ("linebreak", "parbreak"):
                out.append("\n")
            elif name in _IGNORED_CALLS:
                out.append("")
            elif name in _TEXT_CALLS:
                out.append("".join(pieces))
            elif pieces:
                out.append("".join(pieces))
            index = cursor
        elif ch == "*":
            end = content.find("*", index + 1)
            if end < 0:
                out.append(ch)
                index += 1
            else:
                out.append(content[index + 1 : end])
                index = end + 1
        elif ch == "`":
            end = content.find("`", index + 1)
            if end < 0:
                out.append(ch)
                index += 1
            else:
                out.append(content[index + 1 : end])
                index = end + 1
        else:
            out.append(ch)
            index += 1
    text = "".join(out)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _consume_call_args(source: str, cursor: int) -> tuple[list[str], int]:
    """从 ``cursor`` 起消费 ``#name`` 的全部后缀参数 ``(…)`` / ``[…]``。

    :return: (提取到的内容块文本片段列表, 消费后的游标)
    """
    length = len(source)
    pieces: list[str] = []
    while True:
        while cursor < length and source[cursor] in " \t\n":
            cursor += 1
        if cursor >= length:
            break
        if source[cursor] == "(":
            end = _find_matching(source, cursor, "(", ")")
            if end < 0:
                break
            for part in _split_top_level(source[cursor + 1 : end]):
                stripped = part.strip()
                if stripped.startswith("["):
                    pieces.append(_typ_text(_content_value(stripped)))
            cursor = end + 1
        elif source[cursor] == "[":
            end = _find_matching(source, cursor, "[", "]")
            if end < 0:
                break
            pieces.append(_typ_text(source[cursor + 1 : end]))
            cursor = end + 1
        else:
            break
    return pieces, cursor


def _math_text(math: str) -> str:
    """把数学块简化为可读文本：去命令调用，压缩空白。"""
    text = re.sub(r"#\w+(\([^()]*\)|\[[^\[\]]*\])?", "", math)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def extract_show_metadata(source: str) -> dict:
    """提取 ``#show: exam.with(subject: …, year: …, …)`` 的试卷元数据。

    :return: 包含 subject / year / type / name / regions 等字段的字典（缺失字段为空）
    """
    metadata: dict = {}
    match = re.search(r"exam\.with\s*\(", source)
    if not match:
        return metadata
    open_at = match.start() + match.group(0).rfind("(")
    end = _find_matching(source, open_at, "(", ")")
    if end < 0:
        return metadata
    _, named = _parse_call("exam.with" + source[open_at : end + 1])
    for key in ("subject", "year", "type", "name", "regions", "source"):
        if key in named:
            raw = named[key]
            if key == "regions":
                metadata[key] = [
                    item.strip().strip('"').strip("'")
                    for item in _tuple_values(raw)
                    if item.strip()
                ]
            else:
                metadata[key] = raw.strip().strip('"').strip("'")
    return metadata


def parse_typ_source(source: str, subject_hint: str = "") -> list[Question]:
    """解析 Typst 试卷源码为题目草稿列表。

    :param source: ``.typ`` 文件文本
    :param subject_hint: 科目兜底值（界面可从文件名或元数据预填）；
        优先级：题目自带 < ``exam.with`` 元数据 < ``subject_hint``
    """
    metadata = extract_show_metadata(source)
    default_subject = metadata.get("subject") or subject_hint
    drafts: list[Question] = []
    for call_text in _iter_call_sites(source, "question"):
        draft = _parse_question_call(call_text, default_subject)
        if draft is not None:
            drafts.append(draft)
    return drafts


def _parse_question_call(call_text: str, default_subject: str) -> Question | None:
    """解析单个 ``#question(...)`` 调用为题目草稿。"""
    positional, named = _parse_call(call_text)
    type_raw = ""
    if positional:
        type_raw = positional[0]
    else:
        type_raw = named.get("type", "")
    question_type = _TYPST_TYPE_WORDS.get(type_raw.strip().strip('"').strip("'"))
    if question_type is None:
        return None

    stem = _typ_text(_content_value(named.get("stem", "")))
    choices = [
        Option(
            key=chr(ord("A") + index),
            text=_typ_text(_content_value(item)),
        )
        for index, item in enumerate(_tuple_values(named.get("choices", "")))
        if _content_value(item).strip()
    ]
    answer_values = [
        _typ_text(_content_value(item))
        for item in _tuple_values(named.get("answers", ""))
        if _content_value(item).strip()
    ]
    explanation = _typ_text(_content_value(named.get("explanation", "")))

    parts_raw = named.get("parts", "")
    sub_questions: list[tuple[str, list[str], str]] = []
    for item in _tuple_values(parts_raw):
        if not item.strip().startswith("subquestion"):
            continue
        sub = _parse_subquestion(item)
        if sub is not None:
            sub_questions.append(sub)

    if question_type in (QuestionType.SINGLE, QuestionType.MULTIPLE):
        if len(choices) < 2:
            return None
        answers = [value.upper() for value in answer_values]
        stem_text = stem
    elif question_type is QuestionType.FILL:
        choices = []
        answers = answer_values
        stem_text = stem
    else:  # SOLUTION
        choices = []
        sub_stems = [sub[0] for sub in sub_questions]
        if sub_stems:
            stem_text = stem + ("\n" if stem else "") + "\n".join(
                f"（{index}）{text}" for index, text in enumerate(sub_stems, start=1)
            )
        else:
            stem_text = stem
        sub_answers = [sub[1] for sub in sub_questions if sub[1]]
        if sub_answers:
            answers = [
                f"（{index}）" + "；".join(values)
                for index, values in enumerate(sub_answers, start=1)
            ]
        else:
            answers = answer_values
        sub_solutions = [sub[2] for sub in sub_questions if sub[2]]
        if sub_solutions and not explanation:
            explanation = "\n".join(
                f"（{index}）{text}" for index, text in enumerate(sub_solutions, start=1)
            )

    subject = _extract_subject(stem) or default_subject or ""
    return Question(
        id="",
        subject=subject,
        type=question_type,
        stem=stem_text,
        options=choices,
        answer=answers,
        solution=explanation or None,
        difficulty=Difficulty.PENDING,
    )


def _parse_subquestion(call_text: str) -> tuple[str, list[str], str] | None:
    """解析 ``subquestion(stem: […], answers: (…), explanation: […])``。"""
    _, named = _parse_call(call_text)
    if not named.get("stem"):
        return None
    stem = _typ_text(_content_value(named["stem"]))
    answers = [
        _typ_text(_content_value(item))
        for item in _tuple_values(named.get("answers", ""))
        if _content_value(item).strip()
    ]
    explanation = _typ_text(_content_value(named.get("explanation", "")))
    return stem, answers, explanation


#: 题干内常见的科目线索（组卷界面按科目过滤）
_SUBJECT_HINTS = ("数学", "物理", "化学", "生物", "英语", "语文", "地理", "历史", "政治")


def _extract_subject(stem: str) -> str:
    """尝试从题干开头识别科目（如"已知椭圆…"难以识别时返回空串）。"""
    for subject in _SUBJECT_HINTS:
        if stem.startswith(subject):
            return subject
    return ""


def extract_pdf_text(pdf_path: str) -> str:
    """提取 PDF 试卷全文（供编辑后走批量粘贴解析）。

    :param pdf_path: 本地 PDF 文件路径
    :return: 按页拼接的纯文本；加密 / 无文本层 / 解析失败时抛可读异常
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - 依赖未安装时给出可读提示
        raise RuntimeError(
            "解析 PDF 需要 pypdf 库，请先安装：pip install pypdf"
        ) from exc

    try:
        reader = PdfReader(pdf_path)
    except Exception as exc:
        raise ValueError(f"无法打开 PDF 文件：{exc}") from exc
    if reader.is_encrypted:
        raise ValueError("PDF 已加密，无法提取文本，请先解密后再导入")
    pages: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - 单页失败不影响其他页
            text = ""
        pages.append(text)
    joined = "\n".join(pages)
    if not joined.strip():
        raise ValueError("PDF 中没有可提取的文本层（可能是扫描件），请改用图片或手动录入")
    return joined
