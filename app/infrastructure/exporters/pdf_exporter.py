"""PdfExporter：PDF 格式导出器（需求 R12 / R18）。

实现接口：app.interfaces.exporters.BaseExporter
依赖：pymd2pdf（导入名 ``md2pdf``，在 export 方法内惰性导入，未安装时给出可读提示）、
      app.infrastructure.exporters.md_exporter.MdExporter（先产出 Markdown 源文件）、
      app.config.settings（默认导出目录与转换缓存目录）、app.domain.errors.ExportError
被使用：app.container（注册到 PaperExporter 的格式映射）

导出流程：先用 MdExporter 生成同名 ``.md``，再用 md2pdf 把该 MD 转成同名 ``.pdf``
（用户需求：PDF 由该 MD 转换而来）。
"""

from pathlib import Path

from app.config.settings import DEFAULT_MD2PDF_CACHE_DIR
from app.domain.entities.configs import ExportOptions
from app.domain.entities.paper import Paper
from app.domain.errors import ExportError
from app.interfaces.exporters import BaseExporter

from app.infrastructure.exporters.md_exporter import MdExporter


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
    ) -> str:
        """先生成 Markdown 源文件，再转为同名 PDF，返回 PDF 完整路径。

        :param target_dir: 目标目录；None 时用工作区根目录下的固定导出目录
        :raises app.domain.errors.ExportError: 目录不可写 / 未安装 pymd2pdf / 转换失败
        """
        md_path = self._md_exporter.export(paper, target_dir, options)
        pdf_path = str(Path(md_path).with_suffix(".pdf"))
        convert = self._load_convert()
        config = self._build_config(md_path, pdf_path)
        try:
            convert(md_path, pdf_path, config)
        except Exception as exc:  # noqa: BLE001 - md2pdf 各类渲染异常统一转译
            raise ExportError(f"Markdown 转 PDF 失败：{exc}") from exc
        if not Path(pdf_path).is_file():
            raise ExportError(f"Markdown 转 PDF 未生成文件：{pdf_path}")
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
        """构建 md2pdf 配置：转换缓存放在工作区内，不写用户主目录。"""
        from md2pdf import Config

        return Config(
            input_file=md_path,
            output_file=pdf_path,
            cache_dir=str(Path(self._cache_dir).expanduser()),
        )
