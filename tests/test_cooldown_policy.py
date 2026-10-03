"""冷却窗口策略测试计划（业务实现后补充实际用例）。

对应需求 R13，规划用例：

- last_used_at 为 None -> 判定窗口外，惩罚为 0
- last_used_at 在窗口内 -> 判定窗口内，惩罚 > 0
- 距上次使用越近惩罚越大（单调性）
- tasks 模式与 days 模式的窗口换算
- relax_factor：级别越高惩罚衰减越强，恒在 (0, 1]
"""

import pytest


@pytest.mark.skip(reason="框架阶段：待 CooldownPolicy 业务实现后启用")
def test_cooldown_policy_placeholder() -> None:
    raise AssertionError("占位用例不应被执行")
