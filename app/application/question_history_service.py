"""题目操作历史服务：导入历史与编辑历史的查询入口（用户需求）。

历史界面把题库操作台账分为两类展示：

- 导入历史：手工录入（create）与批量导入（import）——即"手动导入"的新增记录
- 编辑历史：题目修改（update）与删除（delete）

依赖（构造注入）：app.interfaces.repositories.QuestionOpRepository
被使用：app.presentation.views.history_view、app.container
"""

from app.domain.entities.question_op import QuestionOpRecord
from app.domain.enums import QuestionOpAction
from app.interfaces.repositories import QuestionOpRepository

#: 导入类操作：手工录入 + 批量导入（手动导入的记录归入导入历史）
IMPORT_ACTIONS: tuple[QuestionOpAction, ...] = (
    QuestionOpAction.CREATE,
    QuestionOpAction.IMPORT,
)

#: 编辑类操作：题目修改与删除
EDIT_ACTIONS: tuple[QuestionOpAction, ...] = (
    QuestionOpAction.UPDATE,
    QuestionOpAction.DELETE,
)


class QuestionHistoryService:
    """题目操作历史服务：按导入 / 编辑两类返回台账记录。"""

    def __init__(self, op_repository: QuestionOpRepository) -> None:
        """注入操作台账仓储。"""
        self._op_repository = op_repository

    def list_import_history(self, limit: int = 500) -> list[QuestionOpRecord]:
        """导入历史：手工录入与批量导入的记录，按时间倒序。"""
        return self._list(IMPORT_ACTIONS, limit)

    def list_edit_history(self, limit: int = 500) -> list[QuestionOpRecord]:
        """编辑历史：题目修改与删除的记录，按时间倒序。"""
        return self._list(EDIT_ACTIONS, limit)

    def _list(
        self, actions: tuple[QuestionOpAction, ...], limit: int
    ) -> list[QuestionOpRecord]:
        """读取指定操作类型的记录（仓储异常时返回空列表，界面不崩溃）。"""
        try:
            return self._op_repository.list_records(
                [QuestionOpAction(action).value for action in actions], limit
            )
        except Exception:  # noqa: BLE001 - 历史展示非关键路径
            return []
