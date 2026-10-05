"""PdfExporter：PDF 格式导出器（需求 R12 / R18）。

实现接口：app.interfaces.exporters.BaseExporter
依赖：Markdown（``markdown`` 包，方法内惰性导入）、标准库 subprocess、
      Edge 无头模式（``--headless=new --print-to-pdf``）、
      app.infrastructure.exporters.md_exporter.MdExporter（先产出 Markdown 源文件）、
      app.config.settings（默认导出目录、浏览器可执行文件候选）、
      app.domain.errors.ExportError
被使用：app.container（注册到 PaperExporter 的格式映射）

导出流程（与参考实现 ``exports/试卷.py`` 一致）：
先用 MdExporter 生成同名 ``.md``，再把它渲染成带 MathJax 与打印 CSS 的 HTML，
最后调用 Edge 无头模式打印为同名 ``.pdf``。

中文与公式：HTML 的 ``font-family`` 指定中文字体、``.pagebreak`` 负责分页，
数学公式交给 MathJax（``--virtual-time-budget`` 留出渲染时间）。
转换耗时较长，调用方（界面）应放到后台线程执行，并通过 ``progress`` 回调显示进度。
"""

import subprocess
import time
from pathlib import Path

from app.config.settings import DEFAULT_PDF_BROWSER_PATHS, DEFAULT_PDF_PROFILE_DIR
from app.domain.entities.configs import ExportOptions
from app.domain.entities.paper import Paper
from app.domain.errors import ExportError
from app.interfaces.exporters import BaseExporter, ProgressCallback

from app.infrastructure.exporters.md_exporter import MdExporter, notify_progress

#: 套在 Markdown 渲染结果外的 HTML 模板（打印 CSS + MathJax，参考 exports/试卷.py）
_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>试卷</title>
<script>
MathJax = {{
  tex: {{
    inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
    displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
    processEscapes: true
  }},
  svg: {{ fontCache: 'global' }},
  startup: {{ typeset: true }}
}};
</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
<style>
  body {{
    font-family: "Microsoft YaHei", "SimSun", sans-serif;
    line-height: 1.7;
    font-size: 11pt;
    padding: 1.5cm;
    color: #000;
  }}
  h1 {{ font-size: 20pt; border-bottom: 2px solid #333; padding-bottom: 6px; }}
  h2 {{ font-size: 15pt; margin-top: 1.2em; }}
  h3 {{ font-size: 13pt; }}
  table {{ border-collapse: collapse; width: 100%; page-break-inside: avoid; }}
  th, td {{ border: 1px solid #999; padding: 6px 8px; }}
  code {{ background: #f5f5f5; padding: 2px 4px; border-radius: 3px; }}
  .pagebreak {{ page-break-after: always; break-after: page; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""

#: MathJax 渲染等待时间（毫秒，参考实现取 15 秒）
_RENDER_BUDGET_MS = 15000

#: 等待 Edge 写出 PDF 的最长时间（秒）：浏览器会先返回、再落盘
_PRINT_WAIT_SECONDS = 60


def render_html(markdown_text: str) -> str:
    """把 Markdown 试卷渲染为可打印的 HTML（含 MathJax 与分页 CSS）。

    :raises ExportError: 未安装 ``markdown`` 包时抛出
    """
    try:
        import markdown
    except ImportError as exc:
        raise ExportError(
            "未安装 Markdown（markdown 包），无法生成 PDF；可改用 MD 格式导出。"
        ) from exc
    body = markdown.markdown(
        markdown_text, extensions=["extra", "md_in_html", "sane_lists"]
    )
    return _HTML_TEMPLATE.format(body=body)


def resolve_browser() -> str | None:
    """返回可用的 Edge 无头浏览器路径（找不到时返回 None）。"""
    for candidate in DEFAULT_PDF_BROWSER_PATHS:
        if Path(candidate).is_file():
            return candidate
    return None


class PdfExporter(BaseExporter):
    """PDF 格式导出器：Markdown -> HTML -> Edge 无头打印实现。"""

    def __init__(
        self,
        md_exporter: MdExporter | None = None,
        browser_path: str | None = None,
    ) -> None:
        """注入 MD 导出器与浏览器路径（None 时按候选自动查找）。"""
        self._md_exporter = md_exporter or MdExporter()
        self._browser_path = browser_path

    def export(
        self,
        paper: Paper,
        target_dir: str | None = None,
        options: ExportOptions | None = None,
        progress: ProgressCallback | None = None,
    ) -> str:
        """先生成 Markdown 源文件，再打印为同名 PDF，返回 PDF 完整路径。

        :param progress: 进度回调（界面在后台线程调用，显示"进行中"状态）
        :raises app.domain.errors.ExportError: 目录不可写 / 缺少浏览器 / 打印失败
        """
        md_path = Path(self._md_exporter.export(paper, target_dir, options, progress))
        pdf_path = md_path.with_suffix(".pdf")
        html_path = md_path.with_suffix(".html")
        notify_progress(progress, "正在渲染 HTML…")
        try:
            html_path.write_text(
                render_html(md_path.read_text(encoding="utf-8")), encoding="utf-8"
            )
        except OSError as exc:
            raise ExportError(f"写入临时 HTML 失败：{html_path}（{exc}）") from exc
        try:
            notify_progress(progress, "正在调用 Edge 打印 PDF（耗时较长，请稍候）…")
            self._print_pdf(html_path, pdf_path)
        finally:
            html_path.unlink(missing_ok=True)
        if not pdf_path.is_file():
            raise ExportError(f"打印 PDF 未生成文件：{pdf_path}")
        notify_progress(progress, f"PDF 已生成：{pdf_path}")
        return str(pdf_path)

    def _print_pdf(self, html_path: Path, pdf_path: Path) -> None:
        """调用浏览器无头模式把 HTML 打印为 PDF（参考 exports/试卷.py 的命令行）。

        浏览器通常先返回、随后才把 PDF 落盘，因此打印后要等文件写出来；
        用独立用户数据目录，避免与本机正在运行的 Edge 冲突。
        """
        browser = self._browser_path or resolve_browser()
        if not browser:
            raise ExportError(
                "未找到 Edge 浏览器（msedge.exe），无法导出 PDF；"
                "可改用 MD 格式导出（内容一致）。"
            )
        profile_dir = Path(DEFAULT_PDF_PROFILE_DIR).expanduser()
        try:
            profile_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ExportError(f"无法创建浏览器临时目录：{profile_dir}（{exc}）") from exc
        pdf_path.unlink(missing_ok=True)
        command = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--user-data-dir={profile_dir.absolute()}",
            f"--print-to-pdf={pdf_path.absolute()}",
            f"--virtual-time-budget={_RENDER_BUDGET_MS}",
            html_path.absolute().as_uri(),
        ]
        try:
            result = subprocess.run(command, check=False)
        except OSError as exc:
            raise ExportError(f"调用浏览器打印 PDF 失败：{exc}") from exc
        if result.returncode != 0:
            raise ExportError(f"浏览器打印 PDF 失败（退出码 {result.returncode}）")
        if not self._wait_for_file(pdf_path):
            raise ExportError(f"浏览器未写出 PDF 文件：{pdf_path}")

    @staticmethod
    def _wait_for_file(path: Path, timeout: float = _PRINT_WAIT_SECONDS) -> bool:
        """等待浏览器把 PDF 写完（文件出现且大小稳定）。"""
        deadline = time.monotonic() + timeout
        last_size = -1
        while time.monotonic() < deadline:
            if path.is_file():
                size = path.stat().st_size
                if size > 0 and size == last_size:
                    return True
                last_size = size
            time.sleep(0.5)
        return path.is_file()
