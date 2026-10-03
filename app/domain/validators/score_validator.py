"""分值规则校验器（需求 Requirement 11）。

校验试卷中不存在未设置分值的题目，并复核"总分 = Σ 分区小计"。

依赖：app.domain.entities.paper、app.domain.errors
被使用：app.application.paper_exporter（导出前拦截，需求 R11 第 4 条）、
        app.application.score_calculator
"""

from app.domain.entities.paper import Paper
from app.domain.errors import ScoreValidationError


class ScoreValidator:
    """分值校验器：无状态，可全局共享同一实例。"""

    def validate(self, paper: Paper) -> None:
        """校验试卷分值完整性，非法时抛出 :class:`ScoreValidationError`。

        :param paper: 待校验的试卷实体
        :raises ScoreValidationError: 存在未设分值题目或总分不一致时抛出
        """
        raise NotImplementedError("TODO(R11): 实现分值完整性校验")
