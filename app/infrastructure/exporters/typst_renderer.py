"""TypstRenderer：把题目里的 Typst 源码渲染成 PNG 图片（导出时使用）。

在试卷导出阶段，将含图题的原始 Typst 代码即时渲染为 PNG，
写入导出目录的 figures/ 子目录，由 Markdown 引用。

依赖：标准库 subprocess / pathlib、app.config.settings
被使用：app.infrastructure.exporters.md_exporter、app.container
"""

import re

import subprocess
from pathlib import Path

from app.config.settings import (
    TYPST_EXE,
    TYPST_GAOKAO_ROOT,
    EXPORT_FIGURES_DIR,
)


class TypstRenderer:
    """Typst 代码 -> PNG 渲染器。"""

    def __init__(
        self,
        typst_exe: str = TYPST_EXE,
        gaokao_root: str = TYPST_GAOKAO_ROOT,
        figures_dir: str = EXPORT_FIGURES_DIR,
        ppi: int = 400,
    ) -> None:
        self._typst_exe = typst_exe
        self._gaokao_root = Path(gaokao_root) if gaokao_root else None
        self._figures_dir = Path(figures_dir)
        self._ppi = ppi
        self._tmp_dir = None

    def is_available(self) -> bool:
        """Typst 编译器是否可用。"""
        return bool(self._typst_exe) and Path(self._typst_exe).exists()

    def _strip_missing_images(self, source: str) -> str:
        """把指向不存在文件的 image("...") 删掉（避免 Typst 编译失败）。"""
        if not source or self._gaokao_root is None:
            return source

        def _check(m):
            path = m.group(1)
            if path.startswith("/"):
                real = self._gaokao_root / path.lstrip("/")
            else:
                real = None
                for y in self._gaokao_root.iterdir():
                    if y.is_dir() and y.name.isdigit():
                        c = y / path
                        if c.exists():
                            real = c
                            break
            if real is not None and real.exists() and real.stat().st_size > 1000:
                return m.group(0)
            return ""

        return re.sub(
            r'image\("([^"]+)"(?:\s*,[^)]*)?\)',
            _check,
            source,
        )

    @staticmethod
    def _prefix_image_paths(source: str, year: str) -> str:
        """把 image("assets/xxx") 改成 image("/<year>/assets/xxx")，让 --root 能解析。"""
        if not source or not year:
            return source
        return re.sub(
            r'image\("(?!\/)([^"]+)"',
            lambda m: f'image("/{year}/{m.group(1)}"',
            source,
        )

    @staticmethod
    def _extract_header(source: str) -> str:
        """从 typst_source 提取头部（#set page 之前的部分）。"""
        idx = source.find("#set page")
        return source[:idx].rstrip() if idx > 0 else ""

    @staticmethod
    def _extract_figures(source: str) -> str:
        """从 typst_source 提取图形部分（#set align(center) 之后的内容）。"""
        marker = "#set align(center)"
        idx = source.find(marker)
        if idx < 0:
            return ""
        return source[idx + len(marker):].strip()

    @staticmethod
    def _extract_all_figure_calls(source: str) -> list:
        """从 source 提取所有 #figure(...) 完整调用（含括号平衡）。"""
        marker = "#set align(center)"
        idx = source.find(marker)
        body = source[idx + len(marker):] if idx >= 0 else source
        figs = []
        pos = 0
        while True:
            m_idx = body.find("#figure", pos)
            if m_idx < 0:
                break
            paren = m_idx + len("#figure")
            while paren < len(body) and body[paren] != "(":
                paren += 1
            if paren >= len(body):
                break
            depth = 0
            i = paren
            while i < len(body):
                c = body[i]
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                    if depth == 0:
                        figs.append(body[m_idx:i+1])
                        pos = i + 1
                        break
                i += 1
            else:
                break
        return figs

    def render_group(self, group_id: str, items: list, output_dir=None) -> str | None:
        """渲染一组图，横向并列。

        :param group_id: 组合 id（用于命名文件）
        :param items: [(question_id, typst_source, label), ...]
            每项对应一题的图；label 是图下方说明（如 "第 5 题"）
        :param output_dir: 导出目标目录
        :return: 相对路径或 None
        """
        if not self.is_available() or not items:
            return None
        if self._gaokao_root is None:
            return None

        # 合并所有题的 header（去重），避免引用不到函数
        headers = []
        for qid, src, _ in items:
            mm = re.match(r"^(\d{4})_", qid)
            yr = mm.group(1) if mm else None
            if yr:
                src = self._prefix_image_paths(src, yr)
            src = self._strip_missing_images(src)
            src = self._sanitize_typst_source(src)
            h = self._extract_header(src)
            if h and h not in headers:
                headers.append(h)
        header = "\n\n".join(headers)

        # 修正每个 item 的 src 里的 image 路径
        new_items = []
        for qid, src, label in items:
            mm = re.match(r"^(\d{4})_", qid)
            yr = mm.group(1) if mm else None
            if yr:
                src = self._prefix_image_paths(src, yr)
            new_items.append((qid, src, label))
        items = new_items

        # 用 grid 两行布局：第一行图，第二行题号
        figs_cells = []
        labels_cells = []
        for qid, src, label in items:
            figs = self._extract_figures(src)
            if not figs:
                figs = "#figure()"
            figs_cells.append(
                "[\n      " + figs.replace("\n", "\n      ") + "\n    ]"
            )
            # 注意：grid 参数里已经在代码模式，不要加 #
            labels_cells.append(
                'text(size: 7pt)[' + label + ']'
            )

        n = len(items)
        source = header + "\n\n"
        source += "#set page(width: auto, height: auto, margin: 4pt)\n"
        source += "#set align(center)\n\n"
        rows_data = figs_cells + labels_cells
        source += (
            "#grid(\n  columns: " + str(n) + ",\n"
            + "  row-gutter: 0.3em,\n  "
            + ",\n  ".join(rows_data) + ",\n)\n"
        )

        # 写临时文件
        tmp_dir = self._tmp_dir_for(group_id)
        tmp_typ = tmp_dir / (group_id + ".typ")
        tmp_typ.write_text(source, encoding="utf-8")

        figures_dir = Path(output_dir) / "figures" if output_dir else self._figures_dir
        figures_dir.mkdir(parents=True, exist_ok=True)
        out_png = figures_dir / (group_id + ".png")

        cmd = [
            self._typst_exe, "compile",
            "--root", str(self._gaokao_root),
            "--pages", "1",

            "--format", "png",
            "--ppi", str(self._ppi),
            str(tmp_typ), str(out_png),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=120,
            )
        except Exception:
            return None

        if result.returncode == 0 and out_png.exists():
            return "figures/" + group_id + ".png"
        return None

    def _tmp_dir_for(self, question_id: str) -> Path:
        """返回临时 .typ 应放置的目录：优先与原 .typ 同目录（让 image 相对路径生效）。"""
        m = re.match(r"^(\d{4})_", question_id)
        if m and self._gaokao_root:
            year = m.group(1)
            year_dir = self._gaokao_root / year
            if year_dir.is_dir():
                tmp_dir = year_dir / "_render_tmp"
                tmp_dir.mkdir(exist_ok=True)
                return tmp_dir
        # 回退
        tmp_dir = self._gaokao_root / "_export_tmp"
        tmp_dir.mkdir(exist_ok=True)
        return tmp_dir

    def render(
        self, question_id: str, typst_source: str,
        output_dir=None, label: str = None,
        option_labels: list = None,
        only_first_n: int = None,
    ) -> str | None:
        """渲染 Typst 代码为 PNG，所有图横向排一行，题号标在下方。

        :param only_first_n: 只渲染前 N 个 figure（用于只要题干图的情况）。
        """
        if not self.is_available() or not typst_source:
            return None
        if self._gaokao_root is None:
            return None

        # 修正 image 相对路径
        m = re.match(r"^(\d{4})_", question_id)
        year = m.group(1) if m else None
        if year:
            typst_source = self._prefix_image_paths(typst_source, year)

        typst_source = self._strip_missing_images(typst_source)
        typst_source = self._sanitize_typst_source(typst_source)

        header = self._extract_header(typst_source)
        figs = self._extract_all_figure_calls(typst_source)
        if not figs:
            return None

        # 只取前 N 个
        if only_first_n is not None and only_first_n > 0:
            figs = figs[:only_first_n]

        row = self._build_fig_row(figs, [label] if label else None)

        source = (
            header
            + "\n\n"
            + "#set page(width: auto, height: auto, margin: 4pt)\n"
            + "#set align(center)\n\n"
            + row
            + "\n"
        )

        tmp_dir = self._tmp_dir_for(question_id)
        tmp_typ = tmp_dir / f"{question_id}.typ"
        tmp_typ.write_text(source, encoding="utf-8")

        figures_dir = Path(output_dir) / "figures" if output_dir else self._figures_dir
        figures_dir.mkdir(parents=True, exist_ok=True)
        out_png = figures_dir / f"{question_id}.png"

        cmd = [
            self._typst_exe, "compile",
            "--root", str(self._gaokao_root),
            "--pages", "1",

            "--format", "png",
            "--ppi", str(self._ppi),
            str(tmp_typ), str(out_png),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=120,
            )
        except Exception:
            return None

        if result.returncode == 0 and out_png.exists():
            return f"figures/{question_id}.png"
        return None

    def render_single(self, output_id: str, fig_call: str, header: str, output_dir=None) -> str | None:
        """单独渲染一个 #figure(...) 为 PNG。"""
        if not self.is_available() or self._gaokao_root is None:
            return None

        # 修正 image 相对路径
        m = re.match(r"^(\d{4})_", output_id)
        year = m.group(1) if m else None
        if year:
            fig_call = self._prefix_image_paths(fig_call, year)
            header = self._prefix_image_paths(header, year)

        fig_call = self._strip_missing_images(fig_call)
        header = self._strip_missing_images(header)
        fig_call = self._sanitize_typst_source(fig_call)
        header = self._sanitize_typst_source(header)

        source = (
            header + "\n\n"
            + "#set page(width: auto, height: auto, margin: 4pt)\n"
            + "#set align(center)\n\n"
            + fig_call + "\n"
        )

        tmp_dir = self._tmp_dir_for(output_id)
        tmp_typ = tmp_dir / f"{output_id}.typ"
        tmp_typ.write_text(source, encoding="utf-8")

        figures_dir = Path(output_dir) / "figures" if output_dir else self._figures_dir
        figures_dir.mkdir(parents=True, exist_ok=True)
        out_png = figures_dir / f"{output_id}.png"

        cmd = [
            self._typst_exe, "compile",
            "--root", str(self._gaokao_root),
            "--pages", "1",

            "--format", "png",
            "--ppi", str(self._ppi),
            str(tmp_typ), str(out_png),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=120,
            )
        except Exception:
            return None

        if result.returncode == 0 and out_png.exists():
            return f"figures/{output_id}.png"
        return None

    def render_option_figures(self, question_id: str, typst_source: str,
                               option_labels: list, output_dir=None) -> list:
        """选项图逐个单独渲染，返回 [(label, path), ...]。

        从 typst_source 中取**最后 len(option_labels) 个** figure 作为选项图
        （前面的 figure 视为题干图）。
        """
        if not typst_source or not option_labels:
            return None
        header = self._extract_header(typst_source)
        figs = self._extract_all_figure_calls(typst_source)
        n_opt = len(option_labels)
        if len(figs) < n_opt:
            return None

        opt_figs = figs[-n_opt:]
        results = []
        for fig, lbl in zip(opt_figs, option_labels):
            sub_id = f"{question_id}__opt{lbl}"
            path = self.render_single(sub_id, fig, header, output_dir)
            if path:
                results.append((lbl, path))
        return results if len(results) == n_opt else None

    def count_figures(self, typst_source: str) -> int:
        """返回 typst_source 里的 figure 数量。"""
        if not typst_source:
            return 0
        return len(self._extract_all_figure_calls(typst_source))

    @staticmethod
    def _build_fig_row(figs: list, labels: list = None, *extra) -> str:
        """N 个 figure 横排一行，下方可选 label 行。"""
        n = len(figs)
        parts = []
        parts.append("#grid(")
        parts.append("  columns: " + str(n) + ",")
        parts.append("  gutter: 0.6em,")
        parts.append("  row-gutter: 0.15em,")
        for f in figs:
            body = f.replace("\n", "\n        ")
            parts.append("  [\n        " + body + "\n      ],")
        if labels:
            for lbl in labels:
                parts.append("  text(size: 7pt)[" + lbl + "],")
        parts.append(")")
        return "\n".join(parts)



# ===== sanitize patch =====

# ===== end sanitize patch =====


def _sanitize_typst_source(src):
    """保留 imports + 被 #figure 递归引用到的 #let + #set page/align + 尾部图调用。
    行扫描确定 #let 边界（比括号计数更鲁棒）；宽松收集标识符（含 name.attr 引用）。
    单字母未定义参数兜底为 0。
    """
    import re as _re
    if not src:
        return src

    lines = src.splitlines()
    align_idx = None
    for i, line in enumerate(lines):
        if "#set align(center)" in line:
            align_idx = i
            break
    if align_idx is None:
        return src

    head = lines[:align_idx]
    tail = lines[align_idx + 1:]

    # --- imports ---
    imports = []
    i = 0
    while i < len(head) and not head[i].strip():
        i += 1
    while i < len(head) and head[i].lstrip().startswith("#import"):
        start = i
        d = head[i].count("(") - head[i].count(")")
        i += 1
        while i < len(head) and d > 0:
            d += head[i].count("(") - head[i].count(")")
            i += 1
        imports.extend(head[start:i])

    # --- #let 边界（行扫描）---
    let_starts = [idx for idx, l in enumerate(head)
                  if _re.match(r"^#let\s+[a-zA-Z_]", l)]
    if not let_starts:
        return src

    lets = {}
    let_order = []
    for k in range(len(let_starts)):
        start = let_starts[k]
        end = let_starts[k + 1] if k + 1 < len(let_starts) else len(head)
        block = head[start:end]
        # 去掉尾部空行
        while block and not block[-1].strip():
            block.pop()
        m = _re.match(r"^#let\s+([a-zA-Z_][a-zA-Z0-9_\-]*)", block[0])
        if not m:
            continue
        name = m.group(1)
        # 检查块括号平衡（忽略字符串内的括号，粗略处理）
        depth = 0
        balanced = True
        for l in block:
            # 去掉 $...$ 里的内容，避免数学公式里的括号干扰
            l_clean = _re.sub(r"\$[^$]*\$", "", l)
            depth += (l_clean.count("{") + l_clean.count("(") + l_clean.count("[")
                      - l_clean.count("}") - l_clean.count(")") - l_clean.count("]"))
        if depth != 0:
            balanced = False
        if balanced:
            lets[name] = block
            let_order.append(name)

    # --- 递归收集 needed ---
    id_re = _re.compile(r"[a-zA-Z_][a-zA-Z0-9_\-]*")
    tail_ids = set(id_re.findall("\n".join(tail)))
    needed = set()
    frontier = set(tail_ids)
    while frontier:
        for name in list(frontier):
            if name in lets and name not in needed:
                needed.add(name)
        new_frontier = set()
        for name in needed:
            for id_ in id_re.findall("\n".join(lets[name])):
                if id_ in lets and id_ not in needed:
                    new_frontier.add(id_)
        frontier = new_frontier

    # --- 保留需要的 #let，按原顺序 ---
    kept = []
    for name in let_order:
        if name in needed:
            kept.extend(lets[name])
            kept.append("")

    # --- 单字母参数兜底 ---
    tail_text = "\n".join(tail)
    all_kept = "\n".join(kept)
    for mm in _re.finditer(
        r"#figure\s*\(\s*([a-zA-Z_][a-zA-Z0-9_\-]*)\s*\(\s*([a-z])\s*\)\s*\)",
        tail_text,
    ):
        var = mm.group(2)
        has_def = (
            _re.search(r"(?:^|\n)\s*" + _re.escape(var) + r"\s*=", all_kept)
            or _re.search(r"#let\s+" + _re.escape(var) + r"\b", all_kept)
            or _re.search(r"#let\s+" + _re.escape(var) + r"\b", tail_text)
            or _re.search(r"for\s+" + _re.escape(var) + r"\s+in\b", tail_text)
            or _re.search(r"for\s*\(\s*" + _re.escape(var) + r"[,)]", tail_text)
        )
        if not has_def:
            tail_text = tail_text.replace(
                mm.group(0), "#figure(" + mm.group(1) + "(0))"
            )

    # --- 重建 ---
    result = list(imports) + [""]
    result.extend(kept)
    result.append("#set page(width: auto, height: auto, margin: 8pt)")
    result.append("#set align(center)")
    result.append("")
    result.append(tail_text)

    return "\n".join(result) + "\n"


TypstRenderer._sanitize_typst_source = staticmethod(_sanitize_typst_source)

