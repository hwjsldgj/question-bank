"""冷却窗口策略单元测试（需求 R13）。"""

from datetime import datetime, timedelta

import pytest

from app.application.cooldown_policy import CooldownPolicy
from app.domain.entities.configs import ScoringConfig
from app.domain.entities.usage_record import UsageRecord
from app.domain.enums import CooldownMode


def _config(days: int = 30, mode: CooldownMode = CooldownMode.DAYS) -> ScoringConfig:
    return ScoringConfig(cooldown_mode=mode, cooldown_value=days)


def test_never_used_is_outside_window() -> None:
    """从未使用过：窗口外且无惩罚。"""
    policy = CooldownPolicy(_config())
    record = UsageRecord(question_id="q1")
    now = datetime(2026, 10, 21, 12, 0, 0)
    assert policy.in_cooldown(record, now) is False
    assert policy.recency_penalty(record, now) == 0.0


def test_inside_window_is_detected() -> None:
    """窗口内：判定冷却中且惩罚为 1.0（最大值）。"""
    policy = CooldownPolicy(_config(days=30))
    now = datetime(2026, 10, 21, 12, 0, 0)
    record = UsageRecord(
        question_id="q1", use_count=1, last_used_at=now - timedelta(days=10)
    )
    assert policy.in_cooldown(record, now) is True
    assert policy.recency_penalty(record, now) == 1.0


def test_outside_window_not_detected() -> None:
    """窗口外：判定不在冷却中且惩罚在 (0, 1) 之间。"""
    policy = CooldownPolicy(_config(days=30))
    now = datetime(2026, 10, 21, 12, 0, 0)
    record = UsageRecord(
        question_id="q1", use_count=1, last_used_at=now - timedelta(days=60)
    )
    assert policy.in_cooldown(record, now) is False
    penalty = policy.recency_penalty(record, now)
    assert 0.0 < penalty < 1.0


def test_recency_penalty_monotonic() -> None:
    """距上次使用越近，惩罚越大（单调性）。"""
    policy = CooldownPolicy(_config(days=30))
    now = datetime(2026, 10, 21, 12, 0, 0)
    near = UsageRecord(question_id="q1", last_used_at=now - timedelta(days=90))
    far = UsageRecord(question_id="q2", last_used_at=now - timedelta(days=300))
    assert policy.recency_penalty(near, now) > policy.recency_penalty(far, now)


def test_use_count_penalty_monotonic_and_capped() -> None:
    """使用频次惩罚：随次数递增，达到封顶后不再增长。"""
    policy = CooldownPolicy(_config())
    p0 = policy.use_count_penalty(UsageRecord(question_id="q1", use_count=0))
    p3 = policy.use_count_penalty(UsageRecord(question_id="q1", use_count=3))
    p5 = policy.use_count_penalty(UsageRecord(question_id="q1", use_count=5))
    p100 = policy.use_count_penalty(UsageRecord(question_id="q1", use_count=100))
    assert p0 == 0.0
    assert p0 < p3 < p5
    assert p5 == p100 == 1.0


def test_relax_factor_decays() -> None:
    """放宽系数：级别越高衰减越强，恒在 (0, 1]。"""
    policy = CooldownPolicy(_config())
    assert policy.relax_factor(0) == 1.0
    assert policy.relax_factor(1) == pytest.approx(0.5)
    assert policy.relax_factor(2) == pytest.approx(0.25)
    for level in range(0, 8):
        assert 0.0 < policy.relax_factor(level) <= 1.0


def test_window_delta_days() -> None:
    """窗口换算：days 模式下与配置天数一致。"""
    config = _config(days=15)
    assert CooldownPolicy.window_delta(config) == timedelta(days=15)