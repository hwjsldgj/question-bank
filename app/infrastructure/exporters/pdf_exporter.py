"""PdfExporter：PDF 格式导出器（需求 R12 / R18）。

实现接口：app.interfaces.exporters.BaseExporter
依赖：reportlab（在 export 方法内惰性导入，避免未安装时阻塞应用启动）、
      app.domain.entities.paper、app.domain.errors.ExportError
被使用：app.container（注册到 PaperExporter 的格式映射）
"""

from app.domain.entities.configs import ExportOptions
from app.domain.entities.paper import Paper
from app.interfaces.exporters import BaseExporter

from app.infrastructure.exporters.txt_exporter import TxtExporter


class PdfExporter(BaseExporter):
    """PDF 格式导出器：reportlab 排版实现。"""

    def export(
        self,
        paper: Paper,
        target_dir: str,
        options: ExportOptions | None = None,
    ) -> str:
        """渲染 PDF 试卷并写入 target_dir，返回文件完整路径。

        reportlab 在本方法内导入；导入失败时抛出 ExportError，由界面
        提示改用 TXT 格式（需求 R18 第 4 条：给出可执行的替代格式）。
        """
        TxtExporter._ensure_target_dir(target_dir)
        raise NotImplementedError("TODO(R12): 实现 PDF 渲染与写盘")
