"""QuestionOpRecord 实体：题库操作台账（导入历史 / 编辑历史）。

用户需求：历史界面需分别展示"导入题目的历史"与"编辑题目的历史"。
每次题库写入（录入 / 编辑 / 删除 / 批量导入）都会产生一条记录，
供历史界面按操作类型筛选查看。

依赖：app.domain.enums
被使用：app.interfaces.repositories.QuestionOpRepository、
        app.application.question_service、app.infrastructure.repositories.question_op_repository
"""

from dataclasses import dataclass
from datetime import datetime

from app.domain.enums import QuestionOpAction


@dataclass
class QuestionOpRecord:
    """单次题库操作记录。

    :param id: 记录唯一标识（uuid 字符串）
    :param action: 操作类型（create / update / delete / import）
    :param question_id: 涉及的题目 id；批量导入为批次首题或空串
    :param subject: 题目科目（便于按科目筛选历史）
    :param stem_excerpt: 题干摘要（截断展示）
    :param batch_id: 批量导入批次标识；非批量操作为 None
    :param detail: 操作说明（如"修改难度：中 -> 难"）
    :param created_at: 操作时间
    """

    id: str
    action: QuestionOpAction
    question_id: str = ""
    subject: str = ""
    stem_excerpt: str = ""
    batch_id: str | None = None
    detail: str = ""
    created_at: datetime | None = None
