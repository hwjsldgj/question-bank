"""TxtExporter：TXT 格式导出器（需求 R12 / R18）。

实现接口：app.interfaces.exporters.BaseExporter
依赖：标准库 pathlib、app.domain.entities.paper、app.domain.errors.ExportError
被使用：app.container（注册到 PaperExporter 的格式映射）

排版契约与 PDF 导出器保持一致：选择题 / 解答题两部分、按题型分大题、
分区标题含数量与小计、文档总分、卷末独立答案页。
"""

from pathlib import Path

from app.domain.entities.configs import ExportOptions
from app.domain.entities.paper import Paper
from app.interfaces.exporters import BaseExporter


class TxtExporter(BaseExporter):
    """TXT 格式导出器：纯文本排版实现。"""

    def export(
        self,
        paper: Paper,
        target_dir: str,
        options: ExportOptions | None = None,
    ) -> str:
        """渲染文本试卷并写入 target_dir，返回文件完整路径。

        :raises ExportError: 目标目录不可写时抛出（需求 R18 第 3 条）
        """
        raise NotImplementedError("TODO(R12): 实现 TXT 渲染与写盘")

    @staticmethod
    def _render(paper: Paper, options: ExportOptions) -> str:
        """把 Paper 渲染为全文文本（私有方法：分区 / 小计 / 总分 / 答案页）。"""
        raise NotImplementedError("TODO(R12): 实现 TXT 文本渲染")

    @staticmethod
    def _ensure_target_dir(target_dir: str) -> Path:
        """校验目标目录存在且可写，非法时抛出 ExportError。"""
        raise NotImplementedError("TODO(R18): 实现目录校验")
