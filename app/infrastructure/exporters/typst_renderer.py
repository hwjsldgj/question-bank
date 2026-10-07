"""TypstRenderer：把题目里的 Typst 源码渲染成 PNG 图片（导出时使用）。

在试卷导出阶段，将含图题的原始 Typst 代码即时渲染为 PNG，
写入导出目录的 figures/ 子目录，由 Markdown 引用。

依赖：标准库 subprocess / pathlib、app.config.settings
被使用：app.infrastructure.exporters.md_exporter、app.container
"""

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
        ppi: int = 150,
    ) -> None:
        self._typst_exe = typst_exe
        self._gaokao_root = Path(gaokao_root) if gaokao_root else None
        self._figures_dir = Path(figures_dir)
        self._ppi = ppi
        self._tmp_dir = None

    def is_available(self) -> bool:
        """Typst 编译器是否可用。"""
        return bool(self._typst_exe) and Path(self._typst_exe).exists()

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

        # 用第一题的 header
        header = self._extract_header(items[0][1])

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
        tmp_dir = self._gaokao_root / "_export_tmp"
        tmp_dir.mkdir(exist_ok=True)
        tmp_typ = tmp_dir / (group_id + ".typ")
        tmp_typ.write_text(source, encoding="utf-8")

        figures_dir = Path(output_dir) / "figures" if output_dir else self._figures_dir
        figures_dir.mkdir(parents=True, exist_ok=True)
        out_png = figures_dir / (group_id + ".png")

        cmd = [
            self._typst_exe, "compile",
            "--root", str(self._gaokao_root),
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

    def render(self, question_id: str, typst_source: str, output_dir=None, label: str = None) -> str | None:
        """渲染 Typst 代码为 PNG，返回相对路径；失败返回 None。

        :param output_dir: 导出目标目录；图片写到 <output_dir>/figures/。None 时用默认。
        :param label: 图下方文字（如 "第 5 题"）；None 时不加。
        """
        if not self.is_available() or not typst_source:
            return None

        if self._gaokao_root is None:
            return None

        # 提取 header 和所有 figure 调用
        header = self._extract_header(typst_source)
        figs = self._extract_all_figure_calls(typst_source)
        if not figs:
            return None

        # 构造渲染源码：header + set page + 横排 figs（可能多个）+ 题号
        source = header + "\n\n"
        source += "#set page(width: auto, height: auto, margin: 4pt)\n"
        source += "#set align(center)\n\n"

        if len(figs) == 1:
            source += figs[0] + "\n"
        else:
            # 多图横排
            cells = ["[\n    " + f.replace("\n", "\n    ") + "\n  ]" for f in figs]
            source += (
                "#grid(\n  columns: " + str(len(figs)) + ",\n  gutter: 0.6em,\n  "
                + ",\n  ".join(cells) + ",\n)\n"
            )

        if label:
            source += "#v(0.1em)\n#text(size: 7pt)[" + label + "]\n"

        tmp_dir = self._gaokao_root / "_export_tmp"
        tmp_dir.mkdir(exist_ok=True)
        tmp_typ = tmp_dir / f"{question_id}.typ"
        tmp_typ.write_text(source, encoding="utf-8")

        figures_dir = Path(output_dir) / "figures" if output_dir else self._figures_dir
        figures_dir.mkdir(parents=True, exist_ok=True)
        out_png = figures_dir / f"{question_id}.png"

        cmd = [
            self._typst_exe, "compile",
            "--root", str(self._gaokao_root),
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
