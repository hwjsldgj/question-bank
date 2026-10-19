"""组卷历史服务：任务保存、查询与配置复用。"""

from datetime import datetime
from app.domain.entities.criteria import PaperCriteria
from app.domain.entities.task import ExportRecord, GenerationTask
from app.domain.enums import ExportFormat
from app.interfaces.repositories import TaskRepository


class TaskHistoryService:
    """组卷历史服务：组卷任务记录的统一入口。"""

    def __init__(self, task_repository: TaskRepository) -> None:
        self._task_repository = task_repository

    def save_task(self, task: GenerationTask) -> None:
        """保存组卷任务。"""
        if task.created_at is None:
            task.created_at = datetime.now()
        self._task_repository.save_task(task)

    def attach_export_record(self, task_id: str, file_path: str, fmt: str) -> None:
        """为已有任务追加一条导出记录。"""
        task = self._task_repository.get_task(task_id)
        if not task:
            return
        
        # 去重（如果同一个路径已经记录过，就不重复添加）
        if any(exp.file_path == file_path for exp in task.export_records):
            return

        try:
            format_enum = ExportFormat(fmt.lower())
        except ValueError:
            format_enum = ExportFormat.PDF # 默认回退

        task.export_records.append(ExportRecord(
            format=format_enum,
            file_path=file_path,
            exported_at=datetime.now()
        ))
        self._task_repository.save_task(task)

    def list_tasks(self) -> list[GenerationTask]:
        """按创建时间倒序返回全部历史任务。"""
        return self._task_repository.list_tasks()

    def reuse_criteria(self, task_id: str) -> PaperCriteria:
        """读取历史任务的组卷条件供表单回填。"""
        task = self._task_repository.get_task(task_id)
        if not task:
            raise KeyError(f"未找到任务: {task_id}")
        return task.criteria
