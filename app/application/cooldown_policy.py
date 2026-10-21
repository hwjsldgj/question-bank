"""冷却窗口策略：近期重复抑制的核心规则（需求 R13）。

对"最近使用时间"落在冷却窗口内的候选题施加额外惩罚；
窗口内题量不足时逐级放宽惩罚以补足数量（需求 R13 第 3 条）。

依赖（构造注入）：
- app.domain.entities.configs.ScoringConfig（窗口模式与长度，可由设置界面调整）

被使用：app.application.selection_scorer、app.container
"""

from datetime import datetime, timedelta

from app.domain.entities.configs import ScoringConfig
from app.domain.entities.usage_record import UsageRecord

#: 使用频次惩罚封顶值：use_count 达到该次数后惩罚不再增长（防单题独占罚分）
_USE_COUNT_CAP = 5.0


class CooldownPolicy:
    """冷却窗口策略：纯计算组件，无副作用，可独立单元测试。"""

    def __init__(self, config: ScoringConfig) -> None:
        """注入评分配置（cooldown_mode / cooldown_value）。"""
        self._config = config

    def in_cooldown(self, record: UsageRecord, now: datetime) -> bool:
        """判断题目当前是否处于冷却窗口内（需求 R13 第 2 条）。

        :param record: 题目使用记录；last_used_at 为 None 视为窗口外
        :param now: 当前时刻
        :return: True 表示窗口内（需降权）
        """
        if record.last_used_at is None:
            return False
        elapsed = now - record.last_used_at
        return elapsed < CooldownPolicy.window_delta(self._config)

    def recency_penalty(self, record: UsageRecord, now: datetime) -> float:
        """计算最近使用惩罚分（正值，参与评分减法）。

        规则（需求 R8 第 5 条 / R13 第 2 条）：距上次使用间隔越短惩罚越大；
        窗口内题目额外加重。从未使用过的题目惩罚为 0。

        取值约定：

        - last_used_at 为 None -> 0.0（从未使用，无惩罚）
        - 窗口内 -> 1.0（最大惩罚）
        - 窗口外 -> window_seconds / elapsed_seconds，恒在 (0, 1) 且单调递减
        """
        if record.last_used_at is None:
            return 0.0
        window = CooldownPolicy.window_delta(self._config)
        window_seconds = window.total_seconds()
        if window_seconds <= 0:
            return 0.0
        elapsed_seconds = (now - record.last_used_at).total_seconds()
        if elapsed_seconds < 0:
            # 时钟回拨等异常视为刚使用过
            return 1.0
        if elapsed_seconds < window_seconds:
            return 1.0
        return window_seconds / elapsed_seconds

    def use_count_penalty(self, record: UsageRecord) -> float:
        """计算使用频次惩罚分（正值，参与评分减法）。

        规则（需求 R8 第 6 条）：历史被选次数越多惩罚越大；
        超过 _USE_COUNT_CAP 后封顶为 1.0，避免使用次数极端值主导评分。
        """
        return min(1.0, record.use_count / _USE_COUNT_CAP)

    def relax_factor(self, relax_level: int) -> float:
        """返回放宽系数：冷却窗口内题量不足时逐级降低惩罚（需求 R13 第 3 条）。

        :param relax_level: 放宽级别，0 表示不放宽（系数 1.0），级别越高
            惩罚衰减越强（0.5^level）
        :return: 乘在惩罚分上的放宽系数，恒在 (0, 1] 区间
        """
        if relax_level <= 0:
            return 1.0
        return 0.5 ** relax_level

    @staticmethod
    def window_delta(config: ScoringConfig) -> timedelta:
        """把配置中的冷却窗口换算为时间增量（days 模式用）。

        tasks 模式（按最近 N 次组卷任务）由 PaperComposer 结合任务历史
        换算为起始时间后调用本方法之外的比较逻辑；本方法对 tasks 模式
        按天数近似（与 days 模式共用 cooldown_value 字段）。
        """
        return timedelta(days=config.cooldown_value)