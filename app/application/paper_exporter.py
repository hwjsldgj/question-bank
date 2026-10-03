"""试卷导出服务：按格式分发导出（需求 R12 / R18）。

导出前先执行分值完整性校验（需求 R11 第 4 条：存在未设分值题目时
阻止导出），再分发给对应格式的导出器实现。

依赖（构造注入）：
- dict[ExportFormat, BaseExporter]：格式 -> 导出器实现映射
- app.domain.validators.score_validator.ScoreValidator（导出前校验）

被使用：app.presentation.views.paper_generation_view、app.container
"""

from app.domain.entities.configs import ExportOptions, ExportFormat
from app.domain.entities.paper import Paper
from app.domain.validators.score_validator import ScoreValidator
from app.interfaces.exporters import BaseExporter


class PaperExporter:
    """试卷导出服务：统一导出入口，按格式路由到具体实现。"""

    def __init__(
        self,
        exporters: dict[ExportFormat, BaseExporter],
        score_validator: ScoreValidator,
    ) -> None:
        """注入格式导出器映射与分值校验器。"""
        self._exporters = exporters
        self._score_validator = score_validator

    def export(
        self,
        paper: Paper,
        fmt: ExportFormat,
        target_dir: str,
        options: ExportOptions | None = None,
    ) -> str:
        """导出试卷并返回文件路径（需求 R12 第 7 条）。

        :param paper: 待导出试卷（分值必须完整）
        :param fmt: 导出格式 TXT / PDF
        :param target_dir: 目标目录
        :param options: 导出选项；None 时使用默认值
        :return: 生成的文件完整路径
        :raises app.domain.errors.ScoreValidationError: 分值不完整
        :raises app.domain.errors.ExportError: 目录不可写 / 渲染失败
        """
        raise NotImplementedError("TODO(R12): 实现导出分发")

    def supported_formats(self) -> list[ExportFormat]:
        """返回当前已注册的导出格式列表（界面下拉框数据源）。"""
        raise NotImplementedError("TODO(R12): 实现格式枚举")
