"""题目操作历史服务：导入历史与编辑历史的查询入口（用户需求）。

历史界面把题库操作台账分为两类展示：

- 导入历史：批量粘贴 / 批量入库产生的记录（action = import）
- 编辑历史：单题录入 / 编辑 / 删除产生的记录（action = create / update / delete）

依赖（构造注入）：app.interfaces.repositories.QuestionOpRepository
被使用：app.presentation.views.history_view、app.container
"""

from app.domain.entities.question_op import QuestionOpRecord
from app.domain.enums import QuestionOpAction
from app.interfaces.repositories import QuestionOpRepository

#: 导入类操作
IMPORT_ACTIONS: tuple[QuestionOpAction, ...] = (QuestionOpAction.IMPORT,)

#: 编辑类操作（录入 / 编辑 / 删除）
EDIT_ACTIONS: tuple[QuestionOpAction, ...] = (
    QuestionOpAction.CREATE,
    QuestionOpAction.UPDATE,
    QuestionOpAction.DELETE,
)


class QuestionHistoryService:
    """题目操作历史服务：按导入 / 编辑两类返回台账记录。"""

    def __init__(self, op_repository: QuestionOpRepository) -> None:
        """注入操作台账仓储。"""
        self._op_repository = op_repository

    def list_import_history(self, limit: int = 500) -> list[QuestionOpRecord]:
        """导入历史：批量导入题目的记录，按时间倒序。"""
        return self._list(IMPORT_ACTIONS, limit)

    def list_edit_history(self, limit: int = 500) -> list[QuestionOpRecord]:
        """编辑历史：单题录入 / 编辑 / 删除的记录，按时间倒序。"""
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
