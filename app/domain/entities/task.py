"""GenerationTask 实体：组卷任务记录。

对应需求 R14：保存组卷条件、题目清单与导出记录，
支持历史查看与配置复用（复用仅回填条件，题单允许不同）。

依赖：app.domain.entities.criteria、app.domain.entities.paper、app.domain.enums
被使用：app.application.task_history_service、app.interfaces.repositories.TaskRepository、
        app.infrastructure.repositories.task_repository
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.entities.criteria import PaperCriteria
from app.domain.enums import ExportFormat


@dataclass
class ExportRecord:
    """一次导出的记录值对象（需求 R12 第 8 条）。"""

    format: ExportFormat
    """导出格式：TXT / PDF。"""

    file_path: str
    """导出文件的绝对或相对路径。"""

    exported_at: datetime | None = None
    """导出时间。"""


@dataclass
class GenerationTask:
    """组卷任务实体：一次组卷请求及其结果的记录。"""

    id: str
    """任务唯一标识（uuid 字符串）。"""

    criteria: PaperCriteria
    """本次任务使用的组卷条件（复用时回填表单）。"""

    question_ids: list[str] = field(default_factory=list)
    """入选题目 id 列表（按卷面顺序）。"""

    total_score: float = 0.0
    """试卷总分。"""

    created_at: datetime | None = None
    """任务创建时间。"""

    export_records: list[ExportRecord] = field(default_factory=list)
    """该任务的导出记录列表（一次任务可多次导出）。"""
