"""组卷历史服务：任务保存、查询与配置复用（需求 R14）。

历史任务用于两类场景：查看（时间 / 条件 / 总分）与复用（仅回填组卷
条件到表单，题单按当前题库重新生成，需求 R14 第 3 / 4 条）。

依赖（构造注入）：
- app.interfaces.repositories.TaskRepository（任务持久化）

被使用：app.presentation.views.history_view、
        app.application.paper_composer（组卷完成后保存任务）、app.container
"""

from app.domain.entities.criteria import PaperCriteria
from app.domain.entities.task import GenerationTask
from app.interfaces.repositories import TaskRepository


class TaskHistoryService:
    """组卷历史服务：组卷任务记录的统一入口。"""

    def __init__(self, task_repository: TaskRepository) -> None:
        """注入任务仓储。"""
        self._task_repository = task_repository

    def save_task(self, task: GenerationTask) -> None:
        """保存组卷任务（含条件、题单、总分与导出记录，需求 R14 第 1 条）。"""
        raise NotImplementedError("TODO(R14): 实现任务保存")

    def attach_export_record(self, task_id: str, file_path: str, fmt: str) -> None:
        """为已有任务追加一条导出记录（需求 R12 第 8 条）。"""
        raise NotImplementedError("TODO(R14): 实现导出记录追加")

    def list_tasks(self) -> list[GenerationTask]:
        """按创建时间倒序返回全部历史任务（需求 R14 第 2 条）。"""
        raise NotImplementedError("TODO(R14): 实现历史列表")

    def reuse_criteria(self, task_id: str) -> PaperCriteria:
        """读取历史任务的组卷条件供表单回填（需求 R14 第 3 条）。

        :raises KeyError: 任务不存在时抛出，由界面提示
        """
        raise NotImplementedError("TODO(R14): 实现条件复用")
