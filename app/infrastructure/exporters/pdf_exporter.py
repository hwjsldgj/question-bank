"""PdfExporter：PDF 格式导出器（需求 R12 / R18）。

实现接口：app.interfaces.exporters.BaseExporter
依赖：pymd2pdf（导入名 ``md2pdf``，在 export 方法内惰性导入，未安装时给出可读提示）、
      app.infrastructure.exporters.md_exporter.MdExporter（先产出 Markdown 源文件）、
      app.config.settings（默认导出目录、转换缓存目录、中文字体候选）、
      app.domain.errors.ExportError
被使用：app.container（注册到 PaperExporter 的格式映射）

导出流程：先用 MdExporter 生成同名 ``.md``，再用 md2pdf 把该 MD 转成同名 ``.pdf``
（用户需求：PDF 由该 MD 转换而来）。

中文不乱码：md2pdf 默认字体 DejaVu Sans 不含中文字形，这里用 ThemeConfig
同时给出中文字体的逻辑名称与 TTF 文件路径（用户需求）。
转换耗时较长，调用方（界面）应放到后台线程执行，并通过 ``progress`` 回调显示进度。
"""

import os
from pathlib import Path
from typing import Any

from app.config.settings import DEFAULT_MD2PDF_CACHE_DIR, DEFAULT_PDF_FONT_CANDIDATES
from app.domain.entities.configs import ExportOptions
from app.domain.entities.paper import Paper
from app.domain.errors import ExportError
from app.interfaces.exporters import BaseExporter, ProgressCallback

from app.infrastructure.exporters.md_exporter import MdExporter, notify_progress


def font_directories() -> tuple[Path, ...]:
    """返回常见系统字体目录（Windows / Linux / macOS）。"""
    return (
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
        Path("/usr/share/fonts"),
        Path("/usr/share/fonts/truetype"),
        Path("/usr/local/share/fonts"),
        Path("/Library/Fonts"),
        Path("/System/Library/Fonts"),
        Path.home() / "Library/Fonts",
    )


def resolve_chinese_font() -> tuple[str, str] | None:
    """在系统字体目录里找出第一个可用的中文字体。

    :return: ``(逻辑名称, TTF 文件路径)``；找不到时返回 None（沿用 md2pdf 默认字体）
    """
    for name, filename in DEFAULT_PDF_FONT_CANDIDATES:
        for directory in font_directories():
            path = directory / filename
            if path.is_file():
                return (name, str(path))
    return None


class PdfExporter(BaseExporter):
    """PDF 格式导出器：Markdown -> pymd2pdf 渲染实现。"""

    def __init__(
        self,
        md_exporter: MdExporter | None = None,
        cache_dir: str = DEFAULT_MD2PDF_CACHE_DIR,
    ) -> None:
        """注入 MD 导出器与 md2pdf 转换缓存目录。"""
        self._md_exporter = md_exporter or MdExporter()
        self._cache_dir = cache_dir

    def export(
        self,
        paper: Paper,
        target_dir: str | None = None,
        options: ExportOptions | None = None,
        progress: ProgressCallback | None = None,
    ) -> str:
        """先生成 Markdown 源文件，再转为同名 PDF，返回 PDF 完整路径。

        :param progress: 进度回调（界面在后台线程调用，显示"进行中"状态）
        :raises app.domain.errors.ExportError: 目录不可写 / 未安装 pymd2pdf / 转换失败
        """
        md_path = self._md_exporter.export(paper, target_dir, options, progress)
        pdf_path = str(Path(md_path).with_suffix(".pdf"))
        convert = self._load_convert()
        config = self._build_config(md_path, pdf_path)
        notify_progress(progress, "正在转换 PDF（耗时较长，请稍候）…")
        try:
            convert(md_path, pdf_path, config, progress_callback=self._progress_bridge(progress))
        except Exception as exc:  # noqa: BLE001 - md2pdf 各类渲染异常统一转译
            raise ExportError(f"Markdown 转 PDF 失败：{exc}") from exc
        if not Path(pdf_path).is_file():
            raise ExportError(f"Markdown 转 PDF 未生成文件：{pdf_path}")
        notify_progress(progress, f"PDF 已生成：{pdf_path}")
        return pdf_path

    @staticmethod
    def _load_convert():
        """惰性导入 md2pdf 的 convert；未安装时给出可执行提示（需求 R18 第 4 条）。"""
        try:
            from md2pdf import convert
        except ImportError as exc:
            raise ExportError(
                "未安装 pymd2pdf，无法导出 PDF；可改用 MD 格式导出（内容一致）。"
            ) from exc
        return convert

    def _build_config(self, md_path: str, pdf_path: str):
        """构建 md2pdf 配置：中文主题 + 工作区内的转换缓存。"""
        from md2pdf import Config

        return Config(
            input_file=md_path,
            output_file=pdf_path,
            cache_dir=str(Path(self._cache_dir).expanduser()),
            theme_config=chinese_theme_config(),
        )

    @staticmethod
    def _progress_bridge(progress: ProgressCallback | None):
        """把 md2pdf 的 ``(stage, info)`` 进度转成一行可读文字。

        md2pdf 的回调形如 ``Callable[[str, dict], None]``；无进度回调时返回 None。
        """
        if progress is None:
            return None

        def _on_progress(stage: str, info: dict[str, Any]) -> None:
            detail = ""
            if isinstance(info, dict):
                for key in ("message", "detail", "title", "page"):
                    value = info.get(key)
                    if value:
                        detail = str(value)
                        break
            progress(f"PDF 转换中：{stage}" + (f"（{detail}）" if detail else ""))

        return _on_progress


def chinese_theme_config():
    """构建带中文字体的 ThemeConfig（找不到中文字体时返回 None）。

    pymd2pdf 要求同时设置逻辑名称（``font_*``）与 TTF 文件路径（``font_file_*``），
    否则中文会按默认 DejaVu Sans 渲染成乱码（用户需求）。
    """
    font = resolve_chinese_font()
    if font is None:
        return None
    from md2pdf.styles.theme import ThemeConfig

    name, path = font
    return ThemeConfig(
        font_body=name,
        font_heading=name,
        font_mono=name,
        font_file_body=path,
        font_file_heading=path,
        font_file_mono=path,
    )
