"""题型规则校验器测试（需求 R3 已实现用例）。

覆盖：单选题答案数、多选题答案集合、解答题无选项 + 参考答案、
通用必填字段（科目 / 题干 / 知识点），以及批量校验的聚合报错。
"""

import pytest

from app.domain.entities.question import Option, Question
from app.domain.enums import QuestionType
from app.domain.errors import QuestionValidationError
from app.domain.validators.question_validator import QuestionValidator


@pytest.fixture()
def validator() -> QuestionValidator:
    """共享的校验器实例（无状态）。"""
    return QuestionValidator()


def _choice(question_type: QuestionType, answer: list[str], options: int = 2) -> Question:
    """构造一道选择题（默认 2 个选项 A/B）。"""
    return Question(
        id="",
        subject="数学",
        knowledge_points=["集合"],
        type=question_type,
        stem="题干",
        options=[Option(chr(ord("A") + i), f"选项{i}") for i in range(options)],
        answer=answer,
    )


def test_single_choice_valid(validator) -> None:
    """单选题：2 个选项 + 恰 1 个答案 -> 通过。"""
    validator.validate(_choice(QuestionType.SINGLE, ["A"]))


def test_single_choice_two_answers_rejected(validator) -> None:
    """单选题：答案为 2 个 -> 拒绝并说明原因。"""
    with pytest.raises(QuestionValidationError, match="单选题"):
        validator.validate(_choice(QuestionType.SINGLE, ["A", "B"]))


def test_multiple_choice_needs_answer(validator) -> None:
    """多选题：无答案 -> 拒绝；1 个及以上答案 -> 通过。"""
    with pytest.raises(QuestionValidationError):
        validator.validate(_choice(QuestionType.MULTIPLE, []))
    validator.validate(_choice(QuestionType.MULTIPLE, ["A", "B"]))


def test_answer_must_be_option_key(validator) -> None:
    """答案不是选项标号 -> 拒绝。"""
    with pytest.raises(QuestionValidationError, match="标号"):
        validator.validate(_choice(QuestionType.SINGLE, ["C"]))


def test_choice_needs_two_options(validator) -> None:
    """选择题少于 2 个选项 -> 拒绝。"""
    with pytest.raises(QuestionValidationError, match="2 个选项"):
        validator.validate(_choice(QuestionType.SINGLE, ["A"], options=1))


def test_solution_rules(validator) -> None:
    """解答题：无选项且有参考答案 -> 通过；其余情况 -> 拒绝。"""
    valid = Question(
        id="",
        subject="数学",
        knowledge_points=["导数"],
        type=QuestionType.SOLUTION,
        stem="求极值",
        answer=["令导数为零"],
    )
    validator.validate(valid)

    with_options = Question(
        id="",
        subject="数学",
        knowledge_points=["导数"],
        type=QuestionType.SOLUTION,
        stem="求极值",
        options=[Option("A", "1")],
        answer=["令导数为零"],
    )
    with pytest.raises(QuestionValidationError, match="选项"):
        validator.validate(with_options)

    without_answer = Question(
        id="",
        subject="数学",
        knowledge_points=["导数"],
        type=QuestionType.SOLUTION,
        stem="求极值",
    )
    with pytest.raises(QuestionValidationError, match="参考答案"):
        validator.validate(without_answer)


def test_fill_rules(validator) -> None:
    """填空题：无选项且参考答案非空 -> 通过；含选项或缺答案 -> 拒绝。"""
    valid = Question(
        id="",
        subject="数学",
        knowledge_points=["因式分解"],
        type=QuestionType.FILL,
        stem="x^2-1 = ____",
        answer=["3", "-1"],
    )
    validator.validate(valid)

    with_options = Question(
        id="",
        subject="数学",
        knowledge_points=["因式分解"],
        type=QuestionType.FILL,
        stem="x^2-1 = ____",
        options=[Option("A", "1")],
        answer=["3"],
    )
    with pytest.raises(QuestionValidationError, match="选项"):
        validator.validate(with_options)

    without_answer = Question(
        id="",
        subject="数学",
        knowledge_points=["因式分解"],
        type=QuestionType.FILL,
        stem="x^2-1 = ____",
    )
    with pytest.raises(QuestionValidationError, match="参考答案"):
        validator.validate(without_answer)


def test_required_fields(validator) -> None:
    """科目 / 题干 / 知识点为空 -> 拒绝。"""
    for patch, message in (
        ({"subject": ""}, "科目"),
        ({"stem": ""}, "题干"),
        ({"knowledge_points": []}, "知识点"),
    ):
        question = _choice(QuestionType.SINGLE, ["A"])
        for key, value in patch.items():
            setattr(question, key, value)
        with pytest.raises(QuestionValidationError, match=message):
            validator.validate(question)


def test_validate_many_aggregates_failures(validator) -> None:
    """批量校验：全部合法时返回原列表，存在非法项时聚合报错。"""
    good = _choice(QuestionType.SINGLE, ["A"])
    assert validator.validate_many([good]) == [good]
    with pytest.raises(QuestionValidationError, match="第 2 题"):
        validator.validate_many([good, _choice(QuestionType.SINGLE, ["A", "B"])])
