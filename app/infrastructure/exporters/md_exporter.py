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


def _replace_abs_nested(text: str) -> str:
    """替换 abs(...) 为 |...|，支持嵌套括号"""
    result = []
    i = 0
    prefix = "abs("
    while i < len(text):
        if text[i:i+len(prefix)] == prefix:
            depth = 0
            j = i + len(prefix) - 1
            while j < len(text):
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j < len(text):
                inner = text[i+len(prefix):j]
                result.append("|" + inner + "|")
                i = j + 1
                continue
        result.append(text[i])
        i += 1
    return "".join(result)


def _wrap_bare_math(text: str) -> str:
    """$ 外部的 Typst 数学残留 → 包成 $...$ 或转普通文本"""
    if not text:
        return text

    # 1. \mathbb{X} → $\mathbb{X}$
    text = re.sub(r"\\mathbb\{([A-Za-z])\}", r"$\\mathbb{\1}$", text)

    # 2. #中文# → 中文（Typst 强调）
    text = re.sub(r"#([^#\n]{1,50})#", r"\1", text)

    # 3. 独立希腊字母单词
    greek = ["alpha", "beta", "gamma", "delta", "epsilon", "varepsilon",
             "zeta", "eta", "theta", "vartheta", "iota", "kappa",
             "lambda", "mu", "nu", "xi", "pi", "varpi", "rho", "varrho",
             "sigma", "varsigma", "tau", "upsilon", "phi", "varphi",
             "chi", "psi", "omega",
             "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi",
             "Sigma", "Upsilon", "Phi", "Psi", "Omega"]
    for w in greek:
        text = re.sub(rf"(?<![a-zA-Z]){w}(?![a-zA-Z])", rf"$\\{w}$", text)

    # 4. 独立数学符号
    symbols = {
        "triangle": r"\\triangle",
        "approx": r"\\approx",
        "notin": r"\\notin",
        "neq": r"\\ne",
        "geq": r"\\ge",
        "leq": r"\\le",
        "perp": r"\\perp",
        "parallel": r"\\parallel",
        "infty": r"\\infty",
        "infinity": r"\\infty",
        "cdot": r"\\cdot",
        "cdots": r"\\cdots",
        "dots": r"\\cdots",
    }
    for word, latex in symbols.items():
        text = re.sub(rf"(?<![a-zA-Z]){word}(?![a-zA-Z])", rf"${latex}$", text)

    # 5. X in Y / X notin Y（词边界）
    text = re.sub(r"([A-Za-z0-9\)\}])\s+notin\s+([A-Z\\$])",
                  r"\1 $\\notin$ \2", text)
    text = re.sub(r"([A-Za-z0-9\)\}])\s+in\s+([A-Z\\$])",
                  r"\1 $\\in$ \2", text)

    return text


def typst_to_latex(text: str) -> str:
    """Typst → LaTeX：分别处理 $ 内外"""
    if not text:
        return text

    # 1. 保存 $...$ 和 $$...$$ 块
    math_blocks = []
    def _save(m):
        math_blocks.append(m.group(0))
        return f"\x00M{len(math_blocks)-1}\x00"

    text = re.sub(r"\$\$[\s\S]*?\$\$|\$[^$]*?\$", _save, text)

    # 2. $ 外部处理（Typst 残留 → $...$）
    text = _wrap_bare_math(text)

    # 3. $ 内部处理（用现有的 _conv_math 逻辑）
    def _conv_math(s):
        # 组合函数优先
        s = _replace_abs_nested(s)
        FUNC_MAP = [
            (r"arrow\s*\(\s*([^()]+?)\s*\)", r"\\vec{\1}"),
            (r"bold\s*\(\s*([^()]+?)\s*\)", r"\\mathbf{\1}"),
            (r"boldsymbol\s*\(\s*([^()]+?)\s*\)", r"\\boldsymbol{\1}"),
            (r"sqrt\s*\(\s*([^()]+?)\s*\)", r"\\sqrt{\1}"),
            (r"root\s*\(\s*(\d+)\s*,\s*([^()]+?)\s*\)", r"\\sqrt[\1]{\2}"),
            (r"frac\s*\(\s*([^,()]+?)\s*,\s*([^()]+?)\s*\)", r"\\frac{\1}{\2}"),
            (r"overline\s*\(\s*([^()]+?)\s*\)", r"\\overline{\1}"),
            (r"upright\s*\(\s*([^()]+?)\s*\)", r"\1"),
            (r'op\s*\(\s*"([^"]+?)"\s*\)', r"\\text{\1}"),
            (r"triangle\s+([A-Z]{2,})", r"\\triangle \1"),
        ]
        for pat, rep in FUNC_MAP:
            s = re.sub(pat, rep, s)

        WORD_MAP = [
            (r"\btriangle\b", r"\\triangle"),
            (r"\bcomplement_", r"\\complement_"),
            (r"\binter\b", r"\\cap"),
            (r"\bunion\b", r"\\cup"),
            (r"\bnotin\b", r"\\notin"),
            (r"\bsubset\b", r"\\subset"),
            (r"\bperp\b", r"\\perp"),
            (r"\bparallel\b", r"\\parallel"),
            (r"\bbecause\b", r"\\because"),
            (r"\btherefore\b", r"\\therefore"),
            (r"\bangle\b", r"\\angle"),
            (r"\bdegree\b", r"^\\circ"),
            (r"\binfty\b", r"\\infty"),
            (r"\binfinity\b", r"\\infty"),
            (r"\bcdots\b", r"\\cdots"),
            (r"\bdots\.c\b", r"\\cdots"),
            (r"\bdots\b", r"\\cdots"),
            (r"\bcdot\b", r"\\cdot"),
            (r"\btimes\b", r"\\times"),
            (r"\bdiv\b", r"\\div"),
            (r"\bpm\b", r"\\pm"),
            (r"\bneq\b", r"\\ne"),
            (r"\bgeq\b", r"\\ge"),
            (r"\bleq\b", r"\\le"),
            (r"\bapprox\b", r"\\approx"),
            (r"\bRR\b", r"\\mathbb{R}"),
            (r"\bNN\b", r"\\mathbb{N}"),
            (r"\bZZ\b", r"\\mathbb{Z}"),
            (r"\bQQ\b", r"\\mathbb{Q}"),
            (r"\bCC\b", r"\\mathbb{C}"),
            (r"\balpha\b", r"\\alpha"),
            (r"\bbeta\b", r"\\beta"),
            (r"\bgamma\b", r"\\gamma"),
            (r"\bdelta\b", r"\\delta"),
            (r"\btheta\b", r"\\theta"),
            (r"\blambda\b", r"\\lambda"),
            (r"\bmu\b", r"\\mu"),
            (r"\bnu\b", r"\\nu"),
            (r"\bxi\b", r"\\xi"),
            (r"\bpi\b", r"\\pi"),
            (r"\brho\b", r"\\rho"),
            (r"\bsigma\b", r"\\sigma"),
            (r"\btau\b", r"\\tau"),
            (r"\bphi\b", r"\\phi"),
            (r"\bvarphi\b", r"\\varphi"),
            (r"\bchi\b", r"\\chi"),
            (r"\bpsi\b", r"\\psi"),
            (r"\bomega\b", r"\\omega"),
            (r"\bGamma\b", r"\\Gamma"),
            (r"\bDelta\b", r"\\Delta"),
            (r"\bTheta\b", r"\\Theta"),
            (r"\bLambda\b", r"\\Lambda"),
            (r"\bSigma\b", r"\\Sigma"),
            (r"\bPhi\b", r"\\Phi"),
            (r"\bPsi\b", r"\\Psi"),
            (r"\bOmega\b", r"\\Omega"),
            (r"\bqquad\b", r"\\qquad"),
            (r"\bquad\b", r"\\quad"),
            (r"\boverparen\s*\(([^()]*)\)", r"\\overparen{\1}"),
            (r"\bcoslr\s*\(", r"\\cos\\langle "),
        ]
        for pat, rep in WORD_MAP:
            s = re.sub(pat, rep, s)

        # 清 Typst 转义符（只删 \, \; \!）
        s = re.sub(r"\\(?=[,;!\s])", "", s)
        s = re.sub(r"[ \t]+", " ", s)
        return s.strip()

    def _restore(m):
        idx = int(m.group(1))
        c = math_blocks[idx]
        if c.startswith("$$"):
            return "$$" + _conv_math(c[2:-2]) + "$$"
        return "$" + _conv_math(c[1:-1]) + "$"

    text = re.sub(r"\x00M(\d+)\x00", _restore, text)
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



# ===== typst_to_latex v2 (patch) =====
# 追加定义覆盖旧版，提供完整 Typst -> LaTeX 转换。

def _ttl_split_args(inner):
    parts, cur, depth = [], [], 0
    for ch in inner:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur)); cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts]


def _ttl_replace_func(s, name, wrapper):
    out, i, n = [], 0, len(s)
    pat = __import__("re").compile(r"(?<![a-zA-Z_])" + __import__("re").escape(name) + r"\s*\(")
    while i < n:
        m = pat.search(s, i)
        if not m:
            out.append(s[i:]); break
        out.append(s[i:m.start()])
        j = m.end(); depth = 1; start_inner = j
        while j < n and depth > 0:
            if s[j] == "(":
                depth += 1
            elif s[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth != 0:
            out.append(s[m.start():]); break
        inner = s[start_inner:j]
        try:
            out.append(wrapper(inner))
        except Exception:
            out.append(m.group(0) + inner + ")")
        i = j + 1
    return "".join(out)


def _ttl_mk_frac(inner):
    parts = _ttl_split_args(inner)
    if len(parts) == 2:
        return r"\frac{" + parts[0] + "}{" + parts[1] + "}"
    return r"\frac{" + inner + "}"


def _ttl_mk_root(inner):
    parts = _ttl_split_args(inner)
    if len(parts) == 2:
        return r"\sqrt[" + parts[0] + "]{" + parts[1] + "}"
    return r"\sqrt{" + inner + "}"


_TTL_UNICODE = [
    ("\u211d", r"\mathbb{R} "), ("\u2115", r"\mathbb{N} "),
    ("\u2124", r"\mathbb{Z} "), ("\u211a", r"\mathbb{Q} "),
    ("\u2102", r"\mathbb{C} "),
    ("\u03c0", r"\pi "), ("\u03a0", r"\Pi "),
    ("\u03b1", r"\alpha "), ("\u03b2", r"\beta "),
    ("\u03b3", r"\gamma "), ("\u03b4", r"\delta "),
    ("\u03b5", r"\epsilon "), ("\u03b6", r"\zeta "),
    ("\u03b7", r"\eta "), ("\u03b8", r"\theta "),
    ("\u03b9", r"\iota "), ("\u03ba", r"\kappa "),
    ("\u03bb", r"\lambda "), ("\u03bc", r"\mu "),
    ("\u03bd", r"\nu "), ("\u03be", r"\xi "),
    ("\u03c1", r"\rho "), ("\u03c3", r"\sigma "),
    ("\u03c4", r"\tau "), ("\u03c5", r"\upsilon "),
    ("\u03c6", r"\phi "), ("\u03c7", r"\chi "),
    ("\u03c8", r"\psi "), ("\u03c9", r"\omega "),
    ("\u0393", r"\Gamma "), ("\u0394", r"\Delta "),
    ("\u0398", r"\Theta "), ("\u039b", r"\Lambda "),
    ("\u039e", r"\Xi "), ("\u03a3", r"\Sigma "),
    ("\u03a5", r"\Upsilon "), ("\u03a6", r"\Phi "),
    ("\u03a8", r"\Psi "), ("\u03a9", r"\Omega "),
    ("\u2264", r"\le "), ("\u2265", r"\ge "), ("\u2260", r"\ne "),
    ("\u2248", r"\approx "), ("\u2261", r"\equiv "),
    ("\u223c", r"\sim "), ("\u2245", r"\cong "),
    ("\u221e", r"\infty "), ("\u2205", r"\emptyset "),
    ("\u00d7", r"\times "), ("\u00f7", r"\div "),
    ("\u00b1", r"\pm "), ("\u2213", r"\mp "), ("\u00b7", r"\cdot "),
    ("\u2192", r"\to "), ("\u2190", r"\leftarrow "),
    ("\u2194", r"\leftrightarrow "),
    ("\u21d2", r"\Rightarrow "), ("\u21d0", r"\Leftarrow "),
    ("\u21d4", r"\Leftrightarrow "),
    ("\u2208", r"\in "), ("\u2209", r"\notin "),
    ("\u2282", r"\subset "), ("\u2286", r"\subseteq "),
    ("\u2283", r"\supset "), ("\u2287", r"\supseteq "),
    ("\u222a", r"\cup "), ("\u2229", r"\cap "),
    ("\u2200", r"\forall "), ("\u2203", r"\exists "),
    ("\u2220", r"\angle "), ("\u25b3", r"\triangle "),
    ("\u22a5", r"\perp "), ("\u2225", r"\parallel "),
    ("\u2211", r"\sum "), ("\u220f", r"\prod "), ("\u222b", r"\int "),
    ("\u221a", r"\sqrt "),
    ("\u00b0", r"^\circ "),
]


def _ttl_normalize_unicode(s):
    for a, b in _TTL_UNICODE:
        s = s.replace(a, b)
    return s


_TTL_WORDS = [
    # set-operator patch
    (r"complement", r"\complement"),
    (r"inter", r"\cap"),
    (r"union", r"\cup"),

    (r"arcsin", r"\arcsin"), (r"arccos", r"\arccos"), (r"arctan", r"\arctan"),
    (r"sinh", r"\sinh"), (r"cosh", r"\cosh"), (r"tanh", r"\tanh"),
    (r"sin", r"\sin"), (r"cos", r"\cos"), (r"tan", r"\tan"),
    (r"cot", r"\cot"), (r"sec", r"\sec"), (r"csc", r"\csc"),
    (r"log", r"\log"), (r"ln", r"\ln"), (r"lg", r"\lg"),
    (r"lim", r"\lim"), (r"max", r"\max"), (r"min", r"\min"),
    (r"sup", r"\sup"), (r"inf", r"\inf"),
    (r"sum", r"\sum"), (r"prod", r"\prod"),
    (r"notin", r"\notin"), (r"in", r"\in"),
    (r"subset", r"\subset"), (r"subseteq", r"\subseteq"),
    (r"supset", r"\supset"), (r"supseteq", r"\supseteq"),
    (r"cup", r"\cup"), (r"cap", r"\cap"),
    (r"setminus", r"\setminus"), (r"emptyset", r"\emptyset"),
    (r"varnothing", r"\varnothing"),
    (r"forall", r"\forall"), (r"exists", r"\exists"),
    (r"neg", r"\neg"), (r"land", r"\land"), (r"lor", r"\lor"),
    (r"implies", r"\implies"), (r"iff", r"\iff"),
    (r"triangle", r"\triangle"), (r"angle", r"\angle"),
    (r"perp", r"\perp"), (r"parallel", r"\parallel"),
    (r"cong", r"\cong"), (r"simeq", r"\simeq"), (r"sim", r"\sim"),
    (r"approx", r"\approx"), (r"equiv", r"\equiv"),
    (r"neq", r"\ne"), (r"geq", r"\ge"), (r"leq", r"\le"),
    (r"degree", r"^\circ"), (r"infinity", r"\infty"),
    (r"infty", r"\infty"),
    (r"cdots", r"\cdots"), (r"ldots", r"\ldots"),
    (r"vdots", r"\vdots"), (r"ddots", r"\ddots"),
    (r"dots", r"\dots"), (r"cdot", r"\cdot"),
    (r"times", r"\times"), (r"div", r"\div"),
    (r"pm", r"\pm"), (r"mp", r"\mp"),
    (r"rightarrow", r"\rightarrow"), (r"leftarrow", r"\leftarrow"),
    (r"leftrightarrow", r"\leftrightarrow"),
    (r"Rightarrow", r"\Rightarrow"), (r"Leftarrow", r"\Leftarrow"),
    (r"Leftrightarrow", r"\Leftrightarrow"),
    (r"mapsto", r"\mapsto"), (r"to", r"\to"),
    (r"RR", r"\mathbb{R}"), (r"NN", r"\mathbb{N}"),
    (r"ZZ", r"\mathbb{Z}"), (r"QQ", r"\mathbb{Q}"),
    (r"CC", r"\mathbb{C}"),
    (r"qquad", r"\qquad"), (r"quad", r"\quad"),
    (r"alpha", r"\alpha"), (r"beta", r"\beta"),
    (r"gamma", r"\gamma"), (r"delta", r"\delta"),
    (r"varepsilon", r"\varepsilon"), (r"epsilon", r"\epsilon"),
    (r"zeta", r"\zeta"), (r"eta", r"\eta"),
    (r"vartheta", r"\vartheta"), (r"theta", r"\theta"),
    (r"iota", r"\iota"), (r"kappa", r"\kappa"),
    (r"lambda", r"\lambda"), (r"mu", r"\mu"),
    (r"nu", r"\nu"), (r"xi", r"\xi"),
    (r"varpi", r"\varpi"), (r"pi", r"\pi"),
    (r"varrho", r"\varrho"), (r"rho", r"\rho"),
    (r"varsigma", r"\varsigma"), (r"sigma", r"\sigma"),
    (r"tau", r"\tau"), (r"upsilon", r"\upsilon"),
    (r"varphi", r"\varphi"), (r"phi", r"\phi"),
    (r"chi", r"\chi"), (r"psi", r"\psi"), (r"omega", r"\omega"),
    (r"Gamma", r"\Gamma"), (r"Delta", r"\Delta"), (r"Theta", r"\Theta"),
    (r"Lambda", r"\Lambda"), (r"Xi", r"\Xi"), (r"Pi", r"\Pi"),
    (r"Sigma", r"\Sigma"), (r"Upsilon", r"\Upsilon"),
    (r"Phi", r"\Phi"), (r"Psi", r"\Psi"), (r"Omega", r"\Omega"),
]


def _ttl_apply_words(s):
    import re as _re
    # quad-glue in apply_words: quad/qquad 紧跟字母时补空格
    s = _re.sub(r"(?<![a-zA-Z\\])qquad(?=[a-zA-Z])", lambda m: r"\qquad ", s)
    s = _re.sub(r"(?<![a-zA-Z\\])quad(?=[a-zA-Z])", lambda m: r"\quad ", s)
    for word, latex in _TTL_WORDS:
        pat = r"(?<![a-zA-Z\\])" + _re.escape(word) + r"(?![a-zA-Z])"
        repl = latex + " "
        s = _re.sub(pat, lambda m, _r=repl: _r, s)
    return s


def _ttl_fix_subsup(s):
    out, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch in "_^" and i + 1 < n and s[i+1] == "(":
            j = i + 2; depth = 1
            while j < n and depth > 0:
                if s[j] == "(":
                    depth += 1
                elif s[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if depth == 0:
                inner = s[i+2:j]
                out.append(ch + "{" + inner + "}")
                i = j + 1
                continue
        out.append(ch); i += 1
    return "".join(out)


def _ttl_strip_placeholders(s):
    s = s.replace("#fill-placeholder()", r"\underline{\hspace{2cm}}")
    s = s.replace("#choice-placeholder()", r"\underline{\hspace{1cm}}")
    s = s.replace("#figure-placeholder()", r"\underline{\hspace{2cm}}")
    return s


def _ttl_conv_math(s):
    import re as _re
    s = _ttl_normalize_unicode(s)
    for _ in range(5):
        before = s
        s = _ttl_replace_func(s, "frac", _ttl_mk_frac)
        s = _ttl_replace_func(s, "sqrt", lambda x: r"\sqrt{" + x + "}")
        s = _ttl_replace_func(s, "root", _ttl_mk_root)
        s = _ttl_replace_func(s, "abs", lambda x: r"\left|" + x + r"\right|")
        s = _ttl_replace_func(s, "arrow", lambda x: r"\vec{" + x + "}")
        s = _ttl_replace_func(s, "overline", lambda x: r"\overline{" + x + "}")
        s = _ttl_replace_func(s, "overparen", lambda x: r"\overparen{" + x + "}")
        s = _ttl_replace_func(s, "bold", lambda x: r"\mathbf{" + x + "}")
        s = _ttl_replace_func(s, "boldsymbol", lambda x: r"\boldsymbol{" + x + "}")
        s = _ttl_replace_func(s, "upright", lambda x: x)
        if s == before:
            break
    s = _ttl_fix_subsup(s)
    s = _ttl_apply_words(s)
    s = _ttl_strip_placeholders(s)
    s = _re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _ttl_wrap_bare(s):
    import re as _re
    s = _ttl_strip_placeholders(s)
    s = _re.sub(r"#([^#\n]{1,50})#", r"\1", s)
    s = _re.sub(r"\\mathbb\{([A-Za-z])\}", r"$\\mathbb{\1}$", s)
    s = _ttl_normalize_unicode(s)
    for word, latex in _TTL_WORDS:
        s = _re.sub(r"(?<![a-zA-Z\\])" + _re.escape(word) + r"(?![a-zA-Z])",
                    r"$" + latex.replace("\\", "\\\\") + r"$", s)
    s = _re.sub(r"(?<=[A-Za-z0-9\)\}])\s+in\s+(?=[A-Za-z\\$])", r" $\\in$ ", s)
    return s


def typst_to_latex(text):
    import re as _re
    if not text:
        return text
    blocks = []
    def _save(m):
        blocks.append(m.group(0))
        return "\x00M" + str(len(blocks) - 1) + "\x00"
    text = _re.sub(r"\$\$[\s\S]*?\$\$|\$[^$]*?\$", _save, text)
    text = _ttl_wrap_bare(text)
    def _restore(m):
        idx = int(m.group(1))
        c = blocks[idx]
        if c.startswith("$$"):
            return "$$" + _ttl_conv_math(c[2:-2]) + "$$"
        return "$" + _ttl_conv_math(c[1:-1]) + "$"
    text = _re.sub(r"\x00M(\d+)\x00", _restore, text)
    return text

# ===== end patch =====

# ===== v3 patch =====
import re as _re3

_TTL_SUPSUB_MULTI_V3 = _re3.compile(r"([_^])(\d{2,})(?![\d])")





def _ttl_fix_asterisk(s):
    """Markdown ??????????? * ?? Markdown ?????
    ^* ?? ^{*}?_* ?? _{*}????? * ?? \ast?
    """
    import re as _re
    s = _re.sub(r"\^\s*\*", "^{*}", s)
    s = _re.sub(r"_\s*\*", "_{*}", s)
    s = _re.sub(r"(?<!\\)\*", r"\\ast ", s)
    return s


def _ttl_fix_multi_supsub_v3(s):
    return _TTL_SUPSUB_MULTI_V3.sub(
        lambda m: m.group(1) + "{" + m.group(2) + "}", s)


def _ttl_fix_coslr_v3(s, wrap_dollar):
    out, i, n = [], 0, len(s)
    pat = _re3.compile(r"(?<![a-zA-Z])coslr\s*\(")
    while i < n:
        m = pat.search(s, i)
        if not m:
            out.append(s[i:])
            break
        out.append(s[i:m.start()])
        j = m.end()
        depth = 1
        while j < n and depth > 0:
            if s[j] == "(":
                depth += 1
            elif s[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth != 0:
            out.append(s[m.start():])
            break
        inner = s[m.end():j].strip()
        if inner.startswith("\u27e8") and inner.endswith("\u27e9"):
            inner = inner[1:-1]
        elif inner.startswith("\u2329") and inner.endswith("\u232a"):
            inner = inner[1:-1]
        body = r"\cos\langle " + inner + r" \rangle"
        out.append(("$" + body + "$") if wrap_dollar else body)
        i = j + 1
    return "".join(out)


def _ttl_mk_mat_v3(inner):
    m = _re3.match(r"\s*delim\s*:\s*([^,]+?)\s*,\s*(.*)", inner, _re3.S)
    if not m:
        return r"\begin{matrix}" + inner + r"\end{matrix}"
    delim, rest = m.group(1).strip(), m.group(2)
    dmap = {"|": "vmatrix", "||": "Vmatrix",
            "(": "pmatrix", "[": "bmatrix", "{": "Bmatrix"}
    env = dmap.get(delim, "matrix")
    rows = [r.strip() for r in rest.split(";")]
    lines = [" & ".join(c.strip() for c in r.split(",")) for r in rows]
    return "\\begin{" + env + "}" + " \\\\ ".join(lines) + "\\end{" + env + "}"


def _ttl_mk_cases_v3(inner):
    parts = _ttl_split_args(inner)
    rows = []
    for p in parts:
        p = p.replace(r"\&", " & ")
        p = _re3.sub(r"\\quad\s*", " ", p)
        p = _re3.sub(r"\\qquad\s*", " ", p)
        p = _re3.sub(r"\s+", " ", p).strip()
        rows.append(p)
    return "\\begin{cases}" + " \\\\ ".join(rows) + "\\end{cases}"


def _ttl_conv_math(s):
    import re as _re
    s = _ttl_normalize_unicode(s)
    s = _ttl_fix_coslr_v3(s, wrap_dollar=False)
    for _ in range(5):
        before = s
        s = _ttl_replace_func(s, "frac", _ttl_mk_frac)
        s = _ttl_replace_func(s, "sqrt", lambda x: r"\sqrt{" + x + "}")
        s = _ttl_replace_func(s, "root", _ttl_mk_root)
        s = _ttl_replace_func(s, "abs", lambda x: r"\left|" + x + r"\right|")
        s = _ttl_replace_func(s, "arrow", lambda x: r"\vec{" + x + "}")
        s = _ttl_replace_func(s, "overline", lambda x: r"\overline{" + x + "}")
        s = _ttl_replace_func(s, "overparen", lambda x: r"\overparen{" + x + "}")
        s = _ttl_replace_func(s, "bold", lambda x: r"\mathbf{" + x + "}")
        s = _ttl_replace_func(s, "boldsymbol", lambda x: r"\boldsymbol{" + x + "}")
        s = _ttl_replace_func(s, "upright", lambda x: x)
        s = _ttl_replace_func(s, "mat", _ttl_mk_mat_v3)
        s = _ttl_replace_func(s, "cases", _ttl_mk_cases_v3)
        if s == before:
            break
    s = _ttl_fix_subsup(s)
    s = _ttl_fix_multi_supsub_v3(s)
    s = _ttl_fix_asterisk(s)
    s = _ttl_apply_words(s)
    s = _ttl_strip_placeholders(s)
    s = _re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _ttl_wrap_bare(s):
    import re as _re
    s = _ttl_strip_placeholders(s)
    s = _ttl_fix_coslr_v3(s, wrap_dollar=True)
    s = _re.sub(r"#([^#\n]{1,50})#", r"\1", s)
    s = _re.sub(r"\\mathbb\{([A-Za-z])\}", r"$\\mathbb{\1}$", s)
    s = _ttl_normalize_unicode(s)
    for word, latex in _TTL_WORDS:
        pat = r"(?<![a-zA-Z\\])" + _re.escape(word) + r"(?![a-zA-Z])"
        s = _re.sub(pat, lambda m, _r=latex: "$" + _r + "$", s)
    s = _re.sub(r"(?<=[A-Za-z0-9\)\}])\s+in\s+(?=[A-Za-z\\$])", r" $\\in$ ", s)
    return s

# ===== end v3 patch =====

