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

import re

from datetime import datetime
from pathlib import Path

from app.config.settings import DEFAULT_EXPORT_DIR
from app.domain.entities.configs import ExportOptions
from app.domain.entities.paper import Paper, Section
from app.domain.entities.question import split_sections
from app.domain.enums import QuestionType, SectionKind
from app.domain.errors import ExportError
from app.interfaces.exporters import BaseExporter, ProgressCallback

try:
    from app.infrastructure.exporters.typst_renderer import TypstRenderer
except Exception:  # noqa: BLE001
    TypstRenderer = None


_TYPST_GREEK = {
    "alpha": r"\\alpha", "beta": r"\\beta", "gamma": r"\\gamma",
    "delta": r"\\delta", "epsilon": r"\\epsilon", "varepsilon": r"\\varepsilon",
    "zeta": r"\\zeta", "eta": r"\\eta", "theta": r"\\theta",
    "vartheta": r"\\vartheta", "iota": r"\\iota", "kappa": r"\\kappa",
    "lambda": r"\\lambda", "mu": r"\\mu", "nu": r"\\nu",
    "xi": r"\\xi", "pi": r"\\pi", "varpi": r"\\varpi",
    "rho": r"\\rho", "varrho": r"\\varrho", "sigma": r"\\sigma",
    "varsigma": r"\\varsigma", "tau": r"\\tau", "upsilon": r"\\upsilon",
    "phi": r"\\phi", "varphi": r"\\varphi", "chi": r"\\chi",
    "psi": r"\\psi", "omega": r"\\omega",
    # 大写
    "Gamma": r"\\Gamma", "Delta": r"\\Delta", "Theta": r"\\Theta",
    "Lambda": r"\\Lambda", "Xi": r"\\Xi", "Pi": r"\\Pi",
    "Sigma": r"\\Sigma", "Upsilon": r"\\Upsilon", "Phi": r"\\Phi",
    "Psi": r"\\Psi", "Omega": r"\\Omega",
}

_TYPST_OTHER = {
    "infinity": r"\\infty",
    "plus.minus": r"\\pm",
    "dots.h": r"\\cdots",
    "dots.c": r"\\cdots",
    "dots.v": r"\\vdots",
    "dot": r"\\cdot",
    "because": r"\\because",
    "therefore": r"\\therefore",
    "times": r"\\times",
    "div": r"\\div",
    "leq": r"\\le",
    "geq": r"\\ge",
    "neq": r"\\ne",
    "arrow": r"\\to",
    "RR": r"\\mathbb{R}",
    "NN": r"\\mathbb{N}",
    "ZZ": r"\\mathbb{Z}",
    "QQ": r"\\mathbb{Q}",
    "CC": r"\\mathbb{C}",
}



def _strip_typst_layout(text: str) -> str:
    """清除 Typst 布局指令：#grid / #root-frame / #root-section / #(...) 等。"""
    if not text:
        return text

    # 1. #grid(...) / #block(...) / #box(...) / #align(...) / #(...) 整段删
    def _strip_paren_call(s: str, keyword: str) -> str:
        while True:
            i = s.find(keyword)
            if i < 0:
                return s
            j = i + len(keyword)
            # 找 (
            while j < len(s) and s[j] not in "(\n":
                j += 1
            if j >= len(s) or s[j] != "(":
                # 跳过这个关键词
                s = s[:i] + s[i + len(keyword):]
                continue
            depth = 0
            k = j
            while k < len(s):
                if s[k] == "(":
                    depth += 1
                elif s[k] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            if k >= len(s):
                return s
            s = s[:i] + s[k + 1:]

    for kw in ["#grid", "#block", "#box", "#align", "#root-frame",
               "#root-section", "#stack", "#columns", "#table", "#pad",
               "#place", "#move", "#scale"]:
        text = _strip_paren_call(text, kw)

    # 2. #(...) 直接删（无名字的 grid 内容）
    # 比如 #(columns: 8mm, align: center + bottom, ...)
    text = re.sub(r"#\([^()]*\)", "", text)

    # 3. #let xxx = ... 整行删
    text = re.sub(r"#let\s+\w+\s*=\s*[^\n]+", "", text)

    # 4. 清除裸方括号里残留的 [ ... ] 引用（保留内容）
    # 比如 [#root-frame(...)] 已经删了括号，剩下 [ ] 空对
    text = re.sub(r"\[\s*\]", "", text)

    # 5. 清理连续空行
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def typst_to_latex(text: str) -> str:
    """把 Typst 数学符号转成 LaTeX，供 MathJax 渲染。"""
    if not text:
        return text

    # ===== -2. 清理 【图】) 多余括号 =====
    for _ in range(3):
        text = re.sub(r"【图】[\s\)\]\,]+", "【图】", text)

    # ===== -1. 删掉 【图】 后面的 Typst 碎片 =====
    def _clean_fig_tail(m):
        tail = m.group(0)
        marks = ["image(", "roof-diagram", "root-frame", "root-section",
                 "column-gutter", "[图 ", "]))", "#figure", "#grid",
                 "#box", "#block", "#align"]
        if any(mk in tail for mk in marks):
            return "【图】"
        lines = [l.strip() for l in tail.split("\n")[1:] if l.strip()]
        if lines and all(re.match(r'^[\w"\'\s\(\),\[\]\-\/\.]+$', l) for l in lines):
            return "【图】"
        return tail
    text = re.sub(r"【图】(\n[^\n]*){1,5}", _clean_fig_tail, text)

    # ===== 0. 清除 Typst 布局指令 =====
    text = _strip_typst_layout(text)

    # ===== 1. #step[标题][内容] -> 【标题】内容 =====
    while True:
        m = re.search(r"#step\s*\[([^\[\]]*)\]\s*\[([^\[\]]*)\]", text)
        if not m:
            break
        text = text[:m.start()] + "【" + m.group(1) + "】" + m.group(2) + text[m.end():]

    # 2. #text(size:...)[内容] -> 内容
    text = re.sub(r"#text\([^)]*\)\[([^\[\]]*)\]", r"\1", text)
    # 3. #v(...) / #h(...) 删掉
    text = re.sub(r"#(v|h)\([^)]*\)", "", text)
    # 4. 【图】) 多余括号
    text = re.sub(r"【图】[\s\)]+", "【图】", text)

    def _conv(s: str) -> str:
        # ===== 5. 组合函数优先 =====
        s = re.sub(r'op\("([^"]*)"\)', r"\\text{\1}", s)
        s = re.sub(r"abs\(([^()]*)\)", r"|\1|", s)
        s = re.sub(r"upright\(([a-zA-Z])\)", r"\1", s)
        s = re.sub(r"root\((\d+),\s*([^()]+)\)", r"\\sqrt[\1]{\2}", s)
        s = re.sub(r"sqrt\(([^()]*)\)", r"\\sqrt{\1}", s)
        s = re.sub(r"overparen\(([^()]*)\)", r"\\overparen{\1}", s)
        s = re.sub(r"overline\(([^()]*)\)", r"\\overline{\1}", s)
        s = re.sub(r"vec\(([^()]*)\)", r"\\vec{\1}", s)
        s = re.sub(r"bold\(([^()]*)\)", r"\\mathbf{\1}", s)
        s = re.sub(r"mathbf\(([^()]*)\)", r"\\mathbf{\1}", s)
        s = re.sub(r"boldsymbol\(([^()]*)\)", r"\\boldsymbol{\1}", s)
        s = re.sub(r"frac\(([^,()]+),\s*([^,()]+)\)", r"\\frac{\1}{\2}", s)
        s = re.sub(r"cases\(([^()]*)\)", r"\\begin{cases}\1\\end{cases}", s)
        # angle 后跟字母序列
        s = re.sub(r"angle\s*([A-Z]+)", r"\\angle \1", s)
        s = re.sub(r"\bangle\b", r"\\angle ", s)

        # ===== 6. 符号词（保证词边界） =====
        # degree -> ^\circ
        s = re.sub(r"(?<![a-zA-Z])degree", r"^\\circ", s)
        s = re.sub(r"(?<![a-zA-Z])perp", r"\\perp ", s)
        s = re.sub(r"(?<![a-zA-Z])parallel", r"\\parallel ", s)
        s = re.sub(r"(?<![a-zA-Z])because", r"\\because ", s)
        s = re.sub(r"(?<![a-zA-Z])therefore", r"\\therefore ", s)
        s = re.sub(r"(?<![a-zA-Z])in\b", r"\\in ", s)
        s = re.sub(r"(?<![a-zA-Z])notin\b", r"\\notin ", s)
        s = re.sub(r"(?<![a-zA-Z])subset", r"\\subset ", s)
        s = re.sub(r"(?<![a-zA-Z])approx", r"\\approx ", s)
        s = re.sub(r"(?<![a-zA-Z])pm", r"\\pm ", s)
        s = re.sub(r"(?<![a-zA-Z])mp", r"\\mp ", s)
        s = re.sub(r"(?<![a-zA-Z])to\b", r"\\to ", s)
        s = re.sub(r"(?<![a-zA-Z])quad", r"\\quad ", s)
        s = re.sub(r"(?<![a-zA-Z])qquad", r"\\qquad ", s)

        for k, v in sorted(_TYPST_OTHER.items(), key=lambda x: -len(x[0])):
            s = re.sub(r"(?<![a-zA-Z])" + re.escape(k), v + " ", s)
        for k, v in sorted(_TYPST_GREEK.items(), key=lambda x: -len(x[0])):
            s = re.sub(r"(?<![a-zA-Z])" + re.escape(k), v + " ", s)

        s = re.sub(r"\s+", " ", s)
        return s.strip()

    def _replace_math(m):
        return "$" + _conv(m.group(1)) + "$"

    text = re.sub(r"\$([^$]+)\$", _replace_math, text)

    # 处理 $ 外的 because/therefore
    text = re.sub(r"\bbecause\b", "", text)
    text = re.sub(r"\btherefore\b", "", text)
    return text

def notify_progress(progress: ProgressCallback | None, message: str) -> None:
    """向进度回调上报一行进度（无回调时忽略）。"""
    if progress is not None:
        progress(message)

#: 分区 -> 部分标题
_SECTION_TITLES: dict[SectionKind, str] = {
    SectionKind.CHOICE: "选择题部分",
    SectionKind.FILL: "填空题部分",
    SectionKind.SOLUTION: "解答题部分",
}

#: 题型 -> 大题标题
_TYPE_TITLES: dict[QuestionType, str] = {
    QuestionType.SINGLE: "单选题",
    QuestionType.MULTIPLE: "多选题",
    QuestionType.FILL: "填空题",
    QuestionType.SOLUTION: "解答题",
}

#: 中文序号（试卷部分编号）
_ORDINALS = "一二三四五六七八九十"

#: 分页标记：必须单独成行；渲染成 HTML 后由 ``.pagebreak`` 规则分页
#: （用户需求：答案分页，格式与参考稿 exports/试卷_20261005_223259.md 一致）
PAGE_BREAK = '<div class="pagebreak"></div>'


class MdExporter(BaseExporter):
    """MD 格式导出器：Markdown 源文件排版实现。"""

    def __init__(self, renderer=None) -> None:
        """可选注入 Typst 渲染器；未注入时不渲染含图题。"""
        self._renderer = renderer
        self._current_dir = None

    def export(
        self,
        paper: Paper,
        target_dir: str | None = None,
        options: ExportOptions | None = None,
        progress: ProgressCallback | None = None,
    ) -> str:
        """渲染 Markdown 试卷并写入导出目录，返回文件完整路径。

        :param target_dir: 目标目录；None 时用工作区根目录下的固定导出目录
            （用户需求：导出目录由程序指定，不再由用户选择）
        :param progress: 进度回调（界面在后台线程调用，显示"进行中"状态）
        :raises ExportError: 目录不可写或写盘失败时抛出（需求 R18 第 3 条）
        """
        options = options or ExportOptions()
        notify_progress(progress, "正在写入 Markdown 源文件…")
        directory = self._ensure_target_dir(target_dir or DEFAULT_EXPORT_DIR)
        self._current_dir = directory
        path = directory / f"试卷_{datetime.now():%Y%m%d_%H%M%S}.md"
        try:
            path.write_text(self._render(paper, options), encoding="utf-8")
        except OSError as exc:
            raise ExportError(f"写入试卷文件失败：{path}（{exc}）") from exc
        notify_progress(progress, f"Markdown 已生成：{path}")
        return str(path)

    def _render(self, paper: Paper, options: ExportOptions) -> str:
        """把 Paper 渲染为全文 Markdown 文本（分区 / 小计 / 总分 / 答案页）。"""
        lines = ["# 试卷", "", f"**总分：{paper.total_score:g} 分**", ""]
        number = 0
        for index, section in enumerate(paper.sections, start=1):
            lines.extend(self._render_section(section, index, number + 1))
            number += len(section.questions)
        if options.include_answer_page:
            lines.extend(MdExporter._render_answer_page(paper))
        return "\n".join(lines).rstrip() + "\n"

    def _render_section(self, section: Section, index: int, start_number: int) -> list[str]:
        """渲染一个分区：标题（数量 / 分值 / 知识点板块）+ 逐题题面。

        格式与参考稿 ``exports/试卷_20261005_223259.md`` 一致：
        分区标题用全角括号标注题型，题面块内除末行外都以两个空格结尾（Markdown 硬换行）。
        """
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
        lines = [f"## {ordinal}、{title}（{type_title}）", ""]
        summary = [
            f"共 {len(section.questions)} 题，{score_hint}小计 {subtotal:g} 分。"
        ]
        if sections_used:
            # 知识点板块随题面导出（用户需求：导出内容带板块）
            summary.append(f"知识点板块：{'、'.join(sections_used)}。")
        lines.extend(["  \n".join(summary), ""])

        qs = section.questions
        i = 0
        while i < len(qs):
            question = qs[i]
            number = start_number + i

            # ---- 1. 渲染当前题题干 + 选项（Typst 符号转 LaTeX） ----
            block = [f"{number}. {typst_to_latex(question.stem)}"]
            block.extend(
                f"   {option.key}. {typst_to_latex(option.text)}"
                for option in question.options
            )
            lines.extend(["  \n".join(block), ""])

            typst_src = getattr(question, "typst_source", None)
            has_fig = bool(typst_src) and self._renderer is not None

            if has_fig:
                next_q = qs[i + 1] if i + 1 < len(qs) else None
                next_src = getattr(next_q, "typst_source", None) if next_q else None
                next_has_fig = bool(next_src) and self._renderer is not None

                # 用户需求：当前题或下一题有选项图时，禁用相邻合并
                has_opt_fig = any("【图】" in o.text for o in question.options)
                next_has_opt_fig = (
                    next_q is not None
                    and any("【图】" in o.text for o in next_q.options)
                )
                if has_opt_fig or next_has_opt_fig:
                    next_has_fig = False

                if next_has_fig:
                    # ---- 2a. 两题都有图：合并渲染，插在当前题题干下面 ----
                    group_id = f"g_{question.id}_{next_q.id}"
                    items = [
                        (question.id, typst_src, f"第 {number} 题"),
                        (next_q.id, next_src, f"第 {number + 1} 题"),
                    ]
                    rendered_path = self._renderer.render_group(
                        group_id, items, output_dir=self._current_dir
                    )
                    if rendered_path:
                        lines.extend([f"   ![题目图片]({rendered_path})", ""])
                    else:
                        # 合并失败 -> 分别渲染
                        fig_opts = [o for o in question.options if "【图】" in o.text]
                        opt_labels = [o.key for o in fig_opts] if fig_opts else None
                        r1 = self._renderer.render(
                            question.id, typst_src,
                            output_dir=self._current_dir,
                            label=f"第 {number} 题",
                            option_labels=opt_labels,
                        )
                        if r1:
                            lines.extend([f"   ![题目图片]({r1})", ""])

                    # ---- 3. 关键：把下一题题干也输出（之前被吞） ----
                    next_number = number + 1
                    next_block = [f"{next_number}. {typst_to_latex(next_q.stem)}"]
                    next_block.extend(
                        f"   {option.key}. {typst_to_latex(option.text)}"
                        for option in next_q.options
                    )
                    lines.extend(["  \n".join(next_block), ""])

                    # 若合并失败，需要给下一题单独渲染图
                    if not rendered_path:
                        r2 = self._renderer.render(
                            next_q.id, next_src,
                            output_dir=self._current_dir,
                            label=f"第 {next_number} 题",
                        )
                        if r2:
                            lines.extend([f"   ![题目图片]({r2})", ""])

                    i += 2
                    continue
                else:
                    # ---- 2b. 分离题干图与选项图 ----
                    fig_options = [o for o in question.options if "【图】" in o.text]
                    n_opt_figs = len(fig_options)
                    n_total = self._renderer.count_figures(typst_src)
                    n_stem_figs = n_total - n_opt_figs

                    # 1. 题干图（前 n_stem_figs 个）
                    if n_stem_figs > 0:
                        stem_path = self._renderer.render(
                            question.id, typst_src,
                            output_dir=self._current_dir,
                            label=f"第 {number} 题",
                            only_first_n=n_stem_figs,
                        )
                        if stem_path:
                            lines.extend([f"   ![题目图片]({stem_path})", ""])

                    # 2. 选项图（后 n_opt_figs 个，每个单独渲染，HTML 横排）
                    if n_opt_figs > 0:
                        option_figs = self._renderer.render_option_figures(
                            question.id, typst_src,
                            [o.key for o in fig_options],
                            self._current_dir,
                        )
                        if option_figs:
                            lines.append('<div class="fig-row">')
                            for lbl, path in option_figs:
                                lines.append(
                                    f'  <div class="fig-item">'
                                    f'<img src="{path}" alt="{lbl}">'
                                    f'<div class="fig-label">{lbl}</div>'
                                    f'</div>'
                                )
                            lines.append('</div>')
                            lines.append("")
                        else:
                            # 选项图渲染失败，退回到普通合并渲染
                            fallback = self._renderer.render(
                                question.id, typst_src,
                                output_dir=self._current_dir,
                                label=f"第 {number} 题",
                            )
                            if fallback:
                                lines.extend([f"   ![题目图片]({fallback})", ""])
            elif question.image_path:
                lines.extend([f"   ![题目图片]({question.image_path})", ""])

            i += 1

        return lines

    @staticmethod
    def _render_answer_page(paper: Paper) -> list[str]:
        """渲染卷末答案页：逐题答案与解析，编号与题面一致。

        答案页前插入独立一行的 ``<div class="pagebreak"></div>``（参考稿格式），
        转为 HTML/CSS 后由 ``.pagebreak`` 规则分页（用户需求：答案分页）。
        """
        lines = [PAGE_BREAK, "", "# 答案页", ""]
        number = 0
        for index, section in enumerate(paper.sections, start=1):
            ordinal = _ORDINALS[index - 1] if index <= len(_ORDINALS) else str(index)
            title = _SECTION_TITLES.get(section.section_kind, "试题")
            lines.extend([f"## {ordinal}、{title}", ""])
            answers = {entry.question_id: entry for entry in section.answer_page}
            for question in section.questions:
                number += 1
                entry = answers.get(question.id)
                ans_text = entry.answer if entry else "（缺答案）"
                block = [f"{number}. {typst_to_latex(ans_text)}"]
                if entry is not None and entry.solution:
                    block.append(f"   解析：{typst_to_latex(entry.solution)}")
                lines.extend(["  \n".join(block), ""])
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
