"""UsageRecord 实体：题目使用记录。

近期重复抑制（需求 R13）的数据基础：记录每道题被选入试卷的次数与
最近一次使用时间，供 CooldownPolicy 与 SelectionScorer 计算惩罚分。

依赖：无（仅使用标准库）
被使用：app.interfaces.repositories.UsageRepository、
        app.application.cooldown_policy、app.application.selection_scorer、
        app.infrastructure.repositories.usage_repository
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class UsageRecord:
    """一道题目的使用记录值对象。

    不变量（设计文档 Correctness Properties #10）：

    - ``use_count`` 每次题目被选入试卷时递增 1
    - ``last_used_at`` 等于该次组卷时间；从未被选入时为 None
    """

    question_id: str
    """题目唯一标识，与 Question.id 对应。"""

    use_count: int = 0
    """历史被选入试卷的次数。"""

    last_used_at: datetime | None = None
    """最近一次被选入试卷的时间；None 表示从未被选入。"""
