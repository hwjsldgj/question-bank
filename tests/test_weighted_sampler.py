"""加权随机抽样器单元测试（需求 R9 / Correctness #6 / #7）。"""

import random

import pytest

from app.application.weighted_sampler import WeightedSampler
from app.domain.entities.question import Question
from app.domain.entities.scoring import ScoredQuestion


def _sq(qid: str, score: float) -> ScoredQuestion:
    return ScoredQuestion(
        question=Question(id=qid, subject="数学"),
        score=score,
    )


def test_returns_k_items() -> None:
    """抽取数量等于 k。"""
    sampler = WeightedSampler(rng=random.Random(42))
    pool = [_sq(f"q{i}", 1.0) for i in range(10)]
    picked = sampler.sample(pool, 3)
    assert len(picked) == 3


def test_no_duplicates() -> None:
    """不放回：结果不含重复题目。"""
    sampler = WeightedSampler(rng=random.Random(42))
    pool = [_sq(f"q{i}", 1.0) for i in range(10)]
    picked = sampler.sample(pool, 5)
    ids = [item.question.id for item in picked]
    assert len(ids) == len(set(ids))


def test_k_zero_returns_empty() -> None:
    """k=0 返回空列表。"""
    sampler = WeightedSampler()
    assert sampler.sample([_sq("q1", 1.0)], 0) == []


def test_empty_pool_returns_empty() -> None:
    """空候选集返回空列表。"""
    sampler = WeightedSampler()
    assert sampler.sample([], 3) == []


def test_k_greater_than_pool_returns_all() -> None:
    """k >= 候选数时返回全部（顺序打乱）。"""
    sampler = WeightedSampler(rng=random.Random(42))
    pool = [_sq(f"q{i}", 1.0) for i in range(3)]
    picked = sampler.sample(pool, 10)
    assert len(picked) == 3
    assert {item.question.id for item in picked} == {"q0", "q1", "q2"}


def test_epsilon_keeps_zero_score_eligible() -> None:
    """评分 <= 0 的候选仍可能被抽中（epsilon 兜底，权重恒正）。"""
    sampler = WeightedSampler(rng=random.Random(0))
    pool = [_sq("zero", 0.0), _sq("negative", -100.0)]
    picked = sampler.sample(pool, 2)
    assert len(picked) == 2


def test_reproducible_with_seed() -> None:
    """注入固定随机数发生器时结果可复现。"""
    pool = [_sq(f"q{i}", float(i + 1)) for i in range(10)]
    a = WeightedSampler(rng=random.Random(123)).sample(pool, 5)
    b = WeightedSampler(rng=random.Random(123)).sample(pool, 5)
    assert [x.question.id for x in a] == [x.question.id for x in b]


def test_high_score_preferred() -> None:
    """统计性断言：高评分候选的中选概率显著高于低评分候选。"""
    sampler = WeightedSampler(rng=random.Random(7))
    pool = [_sq("high", 1.0), _sq("low", 0.0)]
    high_hits = 0
    trials = 2000
    for _ in range(trials):
        picked = sampler.sample(pool, 1)
        if picked[0].question.id == "high":
            high_hits += 1
    # high 权重 1.0，low 权重 1e-6，high 几乎必中
    assert high_hits / trials > 0.99