# -*- coding: utf-8 -*-
"""内置组卷预设：首次使用时提供给用户的常用模板。

与 app.config.settings 分离：settings.py 是通用配置常量，
内置预设是业务数据，改动频率不同，独立维护。

内置预设不可删除、不可覆盖；用户可基于任意内置预设「另存为」自定义。

依赖：app.domain.entities.criteria、app.domain.entities.preset、app.domain.enums
被使用：app.application.preset_service
"""

from __future__ import annotations

from app.domain.entities.criteria import PaperCriteria, TypeRequirement
from app.domain.entities.preset import PaperPreset
from app.domain.enums import Difficulty, QuestionType


_SUBJECT = "数学"


def _tr(
    question_type: QuestionType,
    difficulty: Difficulty,
    count: int,
) -> TypeRequirement:
    """构造一条组卷要求的语法糖（默认科目数学、无知识点过滤）。"""
    return TypeRequirement(
        question_type=question_type,
        subject=_SUBJECT,
        difficulty=difficulty,
        count=count,
    )


def _make_easy() -> PaperPreset:
    return PaperPreset(
        name="基础巩固",
        description="单选 8 / 填空 4 / 解答 2，全 easy；适合摸底与课后练习。",
        is_builtin=True,
        criteria=PaperCriteria(
            subject=_SUBJECT,
            choice_enabled=True,
            choice_items=[_tr(QuestionType.SINGLE, Difficulty.EASY, 8)],
            fill_enabled=True,
            fill_items=[_tr(QuestionType.FILL, Difficulty.EASY, 4)],
            solution_enabled=True,
            solution_items=[_tr(QuestionType.SOLUTION, Difficulty.EASY, 2)],
        ),
    )


def _make_review() -> PaperPreset:
    return PaperPreset(
        name="一轮复习",
        description="单选 10 / 填空 6 / 解答 3，easy + medium 混合；常规训练量。",
        is_builtin=True,
        criteria=PaperCriteria(
            subject=_SUBJECT,
            choice_enabled=True,
            choice_items=[
                _tr(QuestionType.SINGLE, Difficulty.EASY, 5),
                _tr(QuestionType.SINGLE, Difficulty.MEDIUM, 5),
            ],
            fill_enabled=True,
            fill_items=[
                _tr(QuestionType.FILL, Difficulty.EASY, 2),
                _tr(QuestionType.FILL, Difficulty.MEDIUM, 4),
            ],
            solution_enabled=True,
            solution_items=[_tr(QuestionType.SOLUTION, Difficulty.MEDIUM, 3)],
        ),
    )


def _make_challenge() -> PaperPreset:
    return PaperPreset(
        name="压轴突破",
        description="单选 4 / 填空 4 / 解答 3，全 hard；题量少而精，冲刺训练。",
        is_builtin=True,
        criteria=PaperCriteria(
            subject=_SUBJECT,
            choice_enabled=True,
            choice_items=[_tr(QuestionType.SINGLE, Difficulty.HARD, 4)],
            fill_enabled=True,
            fill_items=[_tr(QuestionType.FILL, Difficulty.HARD, 4)],
            solution_enabled=True,
            solution_items=[_tr(QuestionType.SOLUTION, Difficulty.HARD, 3)],
        ),
    )


#: 内置预设清单（按展示顺序）
DEFAULT_PRESETS: tuple[PaperPreset, ...] = (
    _make_easy(),
    _make_review(),
    _make_challenge(),
)