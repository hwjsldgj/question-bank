"""试卷导出器接口定义。"""
from abc import ABC, abstractmethod
from typing import Callable
from app.domain.entities.paper import Paper
from app.domain.entities.configs import ExportOptions

# 进度回调类型 (消息: str) -> None
ProgressCallback = Callable[[str], None]

class BaseExporter(ABC):
    """试卷导出器抽象接口（MD / PDF 等格式统一入口）。"""

    @abstractmethod
    def export(
        self,
        paper: Paper,
        target_dir: str | None = None,
        options: ExportOptions | None = None,
        progress: ProgressCallback | None = None,
    ) -> str:
        """将试卷对象渲染为文件并返回绝对路径。

        :param paper: 待导出的试卷实体
        :param target_dir: 目标目录，None 表示使用程序默认导出目录
        :param options: 导出选项（是否包含答案页、是否保留中间产物等）
        :param progress: 进度回调函数，用于向 UI 实时发送状态
        :return: 生成的文件绝对路径
        :raises ExportError: 目录不可写 / 缺少依赖 / 渲染失败
        """
        pass
