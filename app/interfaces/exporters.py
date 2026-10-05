"""试卷导出器抽象接口（需求 R12 / R18）。

每种导出格式（MD / PDF）对应一个实现；调用方通过
``app.application.paper_exporter.PaperExporter`` 按格式分发。

依赖：app.domain.entities.configs、app.domain.entities.paper
被使用（调用方）：app.application.paper_exporter
被实现（实现方）：app.infrastructure.exporters.md_exporter.MdExporter、
                  app.infrastructure.exporters.pdf_exporter.PdfExporter
"""

from abc import ABC, abstractmethod
from typing import Callable

from app.domain.entities.configs import ExportOptions
from app.domain.entities.paper import Paper

#: 导出进度上报回调：接收一行可读进度文字（界面显示，避免用户以为程序卡死）
ProgressCallback = Callable[[str], None]


class BaseExporter(ABC):
    """导出器抽象接口：把 Paper 渲染为指定格式文件。"""

    @abstractmethod
    def export(
        self,
        paper: Paper,
        target_dir: str | None = None,
        options: ExportOptions | None = None,
        progress: ProgressCallback | None = None,
    ) -> str:
        """导出试卷为文件并返回文件完整路径。

        排版契约（需求 R12）：

        - 分"选择题 / 解答题"两部分；未启用部分不出现
        - 选择题部分内按"单项选择 / 多项选择"分大题
        - 各分区标题标注题目数量与分值小计；文档标明总分
        - 分区内含知识点板块时标出所涉及的知识点板块（用户需求：导出内容带板块）
        - 卷末附独立答案页，每个答案前插入分页标记（解答题含参考答案与解析）
        - PDF 由同一次导出的 Markdown 源文件转换而来（同名 .md / .pdf）

        :param paper: 待导出的试卷实体（分值应已通过校验）
        :param target_dir: 目标目录；None 时用工作区根目录下的固定导出目录
            （用户需求：导出目录由程序创建，不再由用户指定）
        :param options: 导出选项；None 时使用默认值
        :param progress: 进度回调；转换耗时较长时由调用方（界面）在后台线程调用，
            用于显示"进行中"状态
        :return: 生成的文件完整路径
        :raises app.domain.errors.ExportError: 目录不可写 / 渲染依赖缺失
        """
