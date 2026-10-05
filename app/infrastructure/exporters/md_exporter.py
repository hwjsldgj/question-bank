"""MdExporter：Markdown 试卷导出器（需求 R12 / R18）。

实现接口：app.interfaces.exporters.BaseExporter
依赖：标准库 pathlib、app.config.settings（默认导出目录）、
      app.domain.entities.paper、app.domain.errors.ExportError
被使用：app.container（注册到 PaperExporter 的格式映射）、
        app.infrastructure.exporters.pdf_exporter（PDF 由本导出的 MD 转换）

排版契约：文件内容为 Markdown 文本（``.md`` 后缀，原 TXT 输出改为 .md，内容不变），
分"选择题 / 填空题 / 解答题"三部分，按题型分大题，分区标题含数量与分值小计、
文档标明总分，卷末附独立答案页。默认写入工作区根目录下的固定导出文件夹。
"""

from datetime import datetime
from pathlib import Path

from app.config.settings import DEFAULT_EXPORT_DIR
from app.domain.entities.configs import ExportOptions
from app.domain.entities.paper import Paper, Section
from app.domain.entities.question import split_sections
from app.domain.enums import QuestionType, SectionKind
from app.domain.errors import ExportError
from app.interfaces.exporters import BaseExporter

#: 分区 -> 部分标题
_SECTION_TITLES: dict[SectionKind, str] = {
    SectionKind.CHOICE: "选择题部分",
    SectionKind.FILL: "填空题部分",
    SectionKind.SOLUTION: "解答题部分",
}

#: 题型 -> 大题标题
_TYPE_TITLES: dict[QuestionType, str] = {
    QuestionType.SINGLE: "单项选择",
    QuestionType.MULTIPLE: "多项选择",
    QuestionType.FILL: "填空题",
    QuestionType.SOLUTION: "解答题",
}

#: 中文序号（试卷部分编号）
_ORDINALS = "一二三四五六七八九十"


class MdExporter(BaseExporter):
    """MD 格式导出器：Markdown 源文件排版实现。"""

    def export(
        self,
        paper: Paper,
        target_dir: str | None = None,
        options: ExportOptions | None = None,
    ) -> str:
        """渲染 Markdown 试卷并写入导出目录，返回文件完整路径。

        :param target_dir: 目标目录；None 时用工作区根目录下的固定导出目录
            （用户需求：导出目录由程序指定，不再由用户选择）
        :raises ExportError: 目录不可写或写盘失败时抛出（需求 R18 第 3 条）
        """
        options = options or ExportOptions()
        directory = self._ensure_target_dir(target_dir or DEFAULT_EXPORT_DIR)
        path = directory / f"试卷_{datetime.now():%Y%m%d_%H%M%S}.md"
        try:
            path.write_text(self._render(paper, options), encoding="utf-8")
        except OSError as exc:
            raise ExportError(f"写入试卷文件失败：{path}（{exc}）") from exc
        return str(path)

    @staticmethod
    def _render(paper: Paper, options: ExportOptions) -> str:
        """把 Paper 渲染为全文 Markdown 文本（分区 / 小计 / 总分 / 答案页）。"""
        lines = ["# 试卷", "", f"**总分：{paper.total_score:g} 分**", ""]
        number = 0
        for index, section in enumerate(paper.sections, start=1):
            lines.extend(MdExporter._render_section(section, index, number + 1))
            number += len(section.questions)
        if options.include_answer_page:
            lines.extend(MdExporter._render_answer_page(paper))
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _render_section(section: Section, index: int, start_number: int) -> list[str]:
        """渲染一个分区：标题（数量 / 分值）+ 逐题题面。"""
        ordinal = _ORDINALS[index - 1] if index <= len(_ORDINALS) else str(index)
        title = _SECTION_TITLES.get(section.section_kind, "试题")
        type_title = _TYPE_TITLES.get(section.question_type, "")
        subtotal = sum(section.score_of(q.id) or 0.0 for q in section.questions)
        score_hint = (
            f"每题 {section.per_question_score:g} 分，"
            if section.per_question_score is not None and not section.question_scores
            else ""
        )

        # 一道题可属于多个板块：拆分后去重，导出全部涉及的板块（用户需求）
        sections_used = list(
            dict.fromkeys(
                name for q in section.questions for name in split_sections(q.section)
            )
        )
        lines = [
            f"## {ordinal}、{title} · {type_title}",
            "",
            f"共 {len(section.questions)} 题，{score_hint}小计 {subtotal:g} 分",
        ]
        if sections_used:
            # 知识点板块随题面导出（用户需求：导出内容带板块）
            lines.append(f"知识点板块：{'、'.join(sections_used)}")
        lines.append("")
        for offset, question in enumerate(section.questions):
            number = start_number + offset
            lines.append(f"{number}. {question.stem}")
            for option in question.options:
                lines.append(f"   - {option.key}. {option.text}")
            if question.image_path:
                lines.append(f"   ![题目图片]({question.image_path})")
            lines.append("")
        return lines

    @staticmethod
    def _render_answer_page(paper: Paper) -> list[str]:
        """渲染卷末答案页：逐题答案与解析，编号与题面一致。"""
        lines = ["---", "", "# 答案页", ""]
        number = 0
        for index, section in enumerate(paper.sections, start=1):
            ordinal = _ORDINALS[index - 1] if index <= len(_ORDINALS) else str(index)
            title = _SECTION_TITLES.get(section.section_kind, "试题")
            lines.extend([f"## {ordinal}、{title}", ""])
            answers = {entry.question_id: entry for entry in section.answer_page}
            for question in section.questions:
                number += 1
                entry = answers.get(question.id)
                lines.append(f"{number}. {entry.answer if entry else '（缺答案）'}")
                if entry is not None and entry.solution:
                    lines.append(f"   - 解析：{entry.solution}")
            lines.append("")
        return lines

    @staticmethod
    def _ensure_target_dir(target_dir: str) -> Path:
        """返回可写的导出目录，不存在时创建（用户需求：程序自建导出文件夹）。

        :raises ExportError: 路径被同名的文件占用或无法创建时抛出
        """
        path = Path(str(target_dir)).expanduser()
        if path.is_dir():
            return path
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ExportError(f"无法创建导出目录：{path}（{exc}）") from exc
        return path
