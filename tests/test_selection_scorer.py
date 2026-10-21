"""选题评分器单元测试（需求 R8 / Correctness #11）。"""

from datetime import datetime, timedelta

import pytest

from app.application.cooldown_policy import CooldownPolicy
from app.application.selection_scorer import SelectionScorer
from app.domain.entities.configs import ScoringConfig
from app.domain.entities.question import Question
from app.domain.entities.scoring import ScoringContext
from app.domain.entities.usage_record import UsageRecord
from app.domain.enums import Difficulty, QualityFlag


class _FakeUsageRepository:
    """内存使用记录仓储：便于构造使用历史。"""

    def __init__(self, records: dict[str, UsageRecord] | None = None) -> None:
        self._records = dict(records or {})

    def record_usage(self, question_ids, used_at):  # pragma: no cover - 未使用
        raise NotImplementedError

    def get(self, question_id):
        return self._records.get(question_id) or UsageRecord(question_id=question_id)

    def get_many(self, question_ids):
        return {qid: self._records[qid] for qid in question_ids if qid in self._records}


def _build(
    records: dict[str, UsageRecord] | None = None,
    config: ScoringConfig | None = None,
) -> SelectionScorer:
    cfg = config or ScoringConfig()
    return SelectionScorer(
        _FakeUsageRepository(records),
        CooldownPolicy(cfg),
        cfg,
    )


def _q(
    qid: str,
    difficulty: Difficulty = Difficulty.MEDIUM,
    quality: QualityFlag = QualityFlag.NORMAL,
    points: list[str] | None = None,
) -> Question:
    return Question(
        id=qid,
        subject="数学",
        difficulty=difficulty,
        quality_flag=quality,
        knowledge_points=points or [],
    )


def test_difficulty_match_monotonic() -> None:
    """难度匹配：与目标相同 > 相差一级 > 相差两级。"""
    scorer = _build()
    ctx = ScoringContext(target_difficulty=Difficulty.MEDIUM)
    assert scorer.difficulty_match_factor(_q("a", Difficulty.MEDIUM), ctx) == 1.0
    assert scorer.difficulty_match_factor(_q("b", Difficulty.EASY), ctx) == 0.5
    assert scorer.difficulty_match_factor(_q("c", Difficulty.HARD), ctx) == 0.5
    # 相差两级（easy vs hard）
    ctx_hard = ScoringContext(target_difficulty=Difficulty.HARD)
    assert scorer.difficulty_match_factor(_q("d", Difficulty.EASY), ctx_hard) == 0.0


def test_difficulty_pending_returns_neutral() -> None:
    """任一难度为 PENDING 时返回中性 0.5。"""
    scorer = _build()
    ctx = ScoringContext(target_difficulty=Difficulty.PENDING)
    assert scorer.difficulty_match_factor(_q("a", Difficulty.MEDIUM), ctx) == 0.5
    ctx2 = ScoringContext(target_difficulty=Difficulty.MEDIUM)
    assert scorer.difficulty_match_factor(_q("b", Difficulty.PENDING), ctx2) == 0.5


def test_knowledge_coverage_factor() -> None:
    """知识点覆盖：覆盖比例越高因子越高；无知识点返回中性 0.5。"""
    scorer = _build()
    ctx = ScoringContext(
        target_difficulty=Difficulty.MEDIUM,
        covered_knowledge_points={"集合"},
    )
    assert scorer.knowledge_coverage_factor(_q("a", points=["集合"]), ctx) == 0.0
    assert scorer.knowledge_coverage_factor(_q("b", points=["函数"]), ctx) == 1.0
    assert scorer.knowledge_coverage_factor(
        _q("c", points=["集合", "函数"]), ctx
    ) == pytest.approx(0.5)
    assert scorer.knowledge_coverage_factor(_q("d"), ctx) == 0.5


def test_quality_factor() -> None:
    """质量：优质 +1、普通 0、低质 -1。"""
    scorer = _build()
    assert scorer.quality_factor(_q("a", quality=QualityFlag.QUALITY)) == 1.0
    assert scorer.quality_factor(_q("b", quality=QualityFlag.NORMAL)) == 0.0
    assert scorer.quality_factor(_q("c", quality=QualityFlag.LOW)) == -1.0


def test_use_count_penalty_lowers_score() -> None:
    """使用频次越多，评分越低。"""
    now = datetime(2026, 10, 21, 12, 0, 0)
    records = {
        "used": UsageRecord(
            question_id="used", use_count=5, last_used_at=now - timedelta(days=365)
        ),
        "fresh": UsageRecord(
            question_id="fresh", use_count=0, last_used_at=None
        ),
    }
    scorer = _build(records)
    ctx = ScoringContext(target_difficulty=Difficulty.MEDIUM, now=now)
    scored = scorer.score([_q("used"), _q("fresh")], ctx)
    by_id = {item.question.id: item.score for item in scored}
    assert by_id["fresh"] > by_id["used"]


def test_recency_penalty_lowers_score() -> None:
    """最近使用越近，评分越低。"""
    now = datetime(2026, 10, 21, 12, 0, 0)
    records = {
        "recent": UsageRecord(
            question_id="recent", use_count=1, last_used_at=now - timedelta(days=5)
        ),
        "old": UsageRecord(
            question_id="old", use_count=1, last_used_at=now - timedelta(days=365)
        ),
    }
    scorer = _build(records)
    ctx = ScoringContext(target_difficulty=Difficulty.MEDIUM, now=now)
    scored = scorer.score([_q("recent"), _q("old")], ctx)
    by_id = {item.question.id: item.score for item in scored}
    assert by_id["old"] > by_id["recent"]


def test_score_sorted_descending() -> None:
    """score 返回结果按评分降序。"""
    scorer = _build()
    ctx = ScoringContext(target_difficulty=Difficulty.MEDIUM)
    candidates = [
        _q("easy_one", Difficulty.EASY),
        _q("match", Difficulty.MEDIUM),
        _q("hard_one", Difficulty.HARD),
    ]
    scored = scorer.score(candidates, ctx)
    scores = [item.score for item in scored]
    assert scores == sorted(scores, reverse=True)
    assert scored[0].question.id == "match"


def test_score_empty_candidates() -> None:
    """空候选集返回空列表。"""
    scorer = _build()
    ctx = ScoringContext(target_difficulty=Difficulty.MEDIUM)
    assert scorer.score([], ctx) == []


def test_weights_are_configurable() -> None:
    """权重可配置：关闭难度权重后，难度差异不影响评分排序。"""
    config = ScoringConfig(
        weight_difficulty=0.0,
        weight_knowledge_coverage=0.0,
        weight_quality=0.0,
        weight_use_count=0.0,
        weight_recency=0.0,
    )
    scorer = _build(config=config)
    ctx = ScoringContext(target_difficulty=Difficulty.MEDIUM)
    scored = scorer.score(
        [_q("a", Difficulty.EASY), _q("b", Difficulty.HARD)], ctx
    )
    assert all(item.score == pytest.approx(0.0) for item in scored)


def test_factors_are_populated() -> None:
    """每个 ScoredQuestion 携带完整因子，便于界面展示评分依据。"""
    scorer = _build()
    ctx = ScoringContext(target_difficulty=Difficulty.MEDIUM)
    [item] = scorer.score([_q("a", Difficulty.MEDIUM, QualityFlag.QUALITY)], ctx)
    assert item.factors.difficulty_match == 1.0
    assert item.factors.quality == 1.0