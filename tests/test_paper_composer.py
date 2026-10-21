"""组卷引擎集成测试（需求 R7-R10 / R13 / Correctness #2 / #4 / #10）。"""

import pytest

from app.application.cooldown_policy import CooldownPolicy
from app.application.paper_composer import PaperComposer
from app.application.score_calculator import ScoreCalculator
from app.application.selection_scorer import SelectionScorer
from app.application.weighted_sampler import WeightedSampler
from app.domain.entities.configs import ScoringConfig
from app.domain.entities.criteria import PaperCriteria, TypeRequirement
from app.domain.entities.question import Question, QuestionFilter, split_sections
from app.domain.entities.usage_record import UsageRecord
from app.domain.enums import Difficulty, QualityFlag, QuestionType
from app.domain.errors import CriteriaValidationError


class _FakeQuestionRepository:
    """内存题目仓储：仅实现 search，其它方法抛 NotImplementedError。"""

    def __init__(self, questions: list[Question]) -> None:
        self._questions = list(questions)

    def search(self, filter: QuestionFilter) -> list[Question]:
        result = list(self._questions)
        if filter.subject:
            result = [q for q in result if q.subject == filter.subject]
        if filter.question_type:
            result = [q for q in result if q.type == filter.question_type]
        if filter.exclude_low_quality:
            result = [q for q in result if q.quality_flag != QualityFlag.LOW]
        if filter.section:
            result = [q for q in result if filter.section in split_sections(q.section)]
        return result

    def save(self, question):  # pragma: no cover - 未使用
        raise NotImplementedError

    def get(self, question_id):  # pragma: no cover - 未使用
        raise NotImplementedError

    def delete(self, question_id):  # pragma: no cover - 未使用
        raise NotImplementedError

    def statistics(self):  # pragma: no cover - 未使用
        raise NotImplementedError


class _FakeUsageRepository:
    """内存使用记录仓储：记录 record_usage 调用。"""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], object]] = []

    def record_usage(self, question_ids, used_at):
        self.calls.append((list(question_ids), used_at))

    def get(self, question_id):
        return UsageRecord(question_id=question_id)

    def get_many(self, question_ids):
        return {}


def _q(
    qid: str,
    qtype: QuestionType = QuestionType.SINGLE,
    difficulty: Difficulty = Difficulty.MEDIUM,
    points: list[str] | None = None,
    quality: QualityFlag = QualityFlag.NORMAL,
    subject: str = "数学",
) -> Question:
    return Question(
        id=qid,
        subject=subject,
        type=qtype,
        stem=f"题{qid}",
        difficulty=difficulty,
        quality_flag=quality,
        knowledge_points=points or [],
    )


def _build_composer(questions: list[Question]):
    q_repo = _FakeQuestionRepository(questions)
    u_repo = _FakeUsageRepository()
    config = ScoringConfig()
    scorer = SelectionScorer(u_repo, CooldownPolicy(config), config)
    sampler = WeightedSampler()
    composer = PaperComposer(
        q_repo, u_repo, scorer, sampler, None, ScoreCalculator(), config
    )
    return composer, u_repo


def _single_criteria(count: int, difficulty: Difficulty = Difficulty.MEDIUM) -> PaperCriteria:
    return PaperCriteria(
        choice_enabled=True,
        choice_items=[
            TypeRequirement(QuestionType.SINGLE, "数学", difficulty, count)
        ],
        subject="数学",
    )


def test_count_conserved_when_bank_sufficient() -> None:
    """库内充足：请求 N 道即出 N 道（Correctness #4）。"""
    questions = [_q(f"q{i}") for i in range(10)]
    composer, _ = _build_composer(questions)
    paper = composer.generate(_single_criteria(3))
    assert len(paper.questions()) == 3


def test_insufficient_bank_returns_actual_count() -> None:
    """库内不足：返回实际可提供的数量，不报错。"""
    questions = [_q("q0")]
    composer, _ = _build_composer(questions)
    paper = composer.generate(_single_criteria(5))
    assert len(paper.questions()) == 1


def test_no_duplicate_across_requirements() -> None:
    """同卷去重：多条要求竞争同一道题时只入卷一次（Correctness #2）。"""
    questions = [_q("q0", points=["集合"]), _q("q1", points=["函数"])]
    composer, _ = _build_composer(questions)
    criteria = PaperCriteria(
        choice_enabled=True,
        choice_items=[
            TypeRequirement(
                QuestionType.SINGLE, "数学", Difficulty.MEDIUM, 2,
                knowledge_points=["集合"],
            ),
            TypeRequirement(
                QuestionType.SINGLE, "数学", Difficulty.MEDIUM, 2,
                knowledge_points=["函数"],
            ),
        ],
        subject="数学",
    )
    paper = composer.generate(criteria)
    ids = [q.id for q in paper.questions()]
    assert len(ids) == len(set(ids))
    assert set(ids) == {"q0", "q1"}


def test_usage_recorded_once() -> None:
    """组卷完成后 record_usage 被调用一次，包含全部入选题（R13 第 1 条）。"""
    questions = [_q(f"q{i}") for i in range(5)]
    composer, usage_repo = _build_composer(questions)
    composer.generate(_single_criteria(3))
    assert len(usage_repo.calls) == 1
    ids, _ = usage_repo.calls[0]
    assert len(ids) == 3


def test_empty_criteria_rejected() -> None:
    """未启用任何部分时拒绝组卷（R7 第 4 条）。"""
    composer, _ = _build_composer([])
    with pytest.raises(CriteriaValidationError):
        composer.generate(PaperCriteria())


def test_zero_count_rejected() -> None:
    """数量为 0 时拒绝组卷。"""
    composer, _ = _build_composer([_q("q0")])
    with pytest.raises(CriteriaValidationError):
        composer.generate(_single_criteria(0))


def test_low_quality_excluded() -> None:
    """quality_flag='low' 的题不参与组卷（R5 第 3 条 / R8 第 8 条）。"""
    questions = [
        _q("low", quality=QualityFlag.LOW),
        _q("normal1"),
        _q("normal2"),
    ]
    composer, _ = _build_composer(questions)
    paper = composer.generate(_single_criteria(5))
    ids = {q.id for q in paper.questions()}
    assert "low" not in ids
    assert ids == {"normal1", "normal2"}


def test_pending_difficulty_excluded() -> None:
    """PENDING 难度的题不参与智能组卷（无法判定难度匹配）。"""
    questions = [_q("pending", difficulty=Difficulty.PENDING), _q("ok")]
    composer, _ = _build_composer(questions)
    paper = composer.generate(_single_criteria(5))
    ids = {q.id for q in paper.questions()}
    assert "pending" not in ids
    assert ids == {"ok"}


def test_target_difficulty_is_soft() -> None:
    """目标难度是偏好而非硬过滤：库里只有 EASY 时仍能出卷。"""
    questions = [_q(f"q{i}", difficulty=Difficulty.EASY) for i in range(5)]
    composer, _ = _build_composer(questions)
    paper = composer.generate(_single_criteria(3, difficulty=Difficulty.MEDIUM))
    assert len(paper.questions()) == 3


def test_knowledge_points_filter() -> None:
    """指定知识点时只从命中其中任一知识点的题目中选。"""
    questions = [
        _q("match", points=["集合"]),
        _q("no_match", points=["函数"]),
    ]
    composer, _ = _build_composer(questions)
    criteria = PaperCriteria(
        choice_enabled=True,
        choice_items=[
            TypeRequirement(
                QuestionType.SINGLE, "数学", Difficulty.MEDIUM, 5,
                knowledge_points=["集合"],
            )
        ],
        subject="数学",
    )
    paper = composer.generate(criteria)
    ids = {q.id for q in paper.questions()}
    assert ids == {"match"}


def test_subject_mismatch_returns_empty() -> None:
    """科目不匹配时没有候选题，返回空卷（不抛异常）。"""
    questions = [_q("q0", subject="物理")]
    composer, _ = _build_composer(questions)
    paper = composer.generate(_single_criteria(3))
    assert paper.questions() == []