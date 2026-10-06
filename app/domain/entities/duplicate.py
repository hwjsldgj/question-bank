"""DuplicateGroup：题库自动去重的重复题分组（用户需求）。

判定口径（用户需求）：题干经 :func:`app.domain.entities.question.stem_fingerprint`
归一化后完全相同即视为重复；同一组内保留**最早录入**的一道
（``created_at`` 最早，时间相同时先入库的优先），其余为待删除的重复题。

依赖：app.domain.entities.question
被使用：app.application.question_service、app.presentation.views.question_bank_view
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.entities.question import Question, stem_fingerprint

#: 无入库时间（旧数据）时在"保留最早"排序中的占位：视为最晚录入，不会被优先保留
_UNKNOWN_CREATED_AT = datetime.max


@dataclass
class DuplicateGroup:
    """一组题干相同的题目：保留一道（``keeper``）+ 其余重复题（``duplicates``）。

    :param fingerprint: 该组的题干指纹（:func:`stem_fingerprint` 的结果）
    :param keeper: 保留的题目（最早录入的那道）
    :param duplicates: 待删除的重复题（按录入时间从早到晚）
    """

    fingerprint: str
    keeper: Question
    duplicates: list[Question] = field(default_factory=list)

    @property
    def size(self) -> int:
        """该组题目总数（含保留的那道）。"""
        return 1 + len(self.duplicates)

    def stem_excerpt(self, length: int = 60) -> str:
        """题干摘要（列表与提示文案展示用，折行归一为空格）。"""
        stem = " ".join((self.keeper.stem or "").split())
        return stem if len(stem) <= length else stem[:length] + "…"

    def describe(self, length: int = 40) -> str:
        """可读描述，如 ``"x^2-1=0…（2 道重复）"``。"""
        return f"{self.stem_excerpt(length)}（{self.size} 道）"


def group_duplicates(questions: list[Question]) -> list[DuplicateGroup]:
    """把题目按题干指纹分组，只返回存在重复的分组（每组保留最早录入的一道）。

    :param questions: 待检查的题目列表；无有效题干的题目会被跳过
    :return: 重复分组列表，按保留题目的录入时间倒序（与题库列表顺序一致）
    """
    buckets: dict[str, list[Question]] = {}
    for question in questions:
        key = stem_fingerprint(question.stem)
        if not key:
            continue
        buckets.setdefault(key, []).append(question)

    groups: list[DuplicateGroup] = []
    for key, items in buckets.items():
        if len(items) < 2:
            continue
        ordered = _oldest_first(items)
        groups.append(
            DuplicateGroup(
                fingerprint=key, keeper=ordered[0], duplicates=ordered[1:]
            )
        )
    groups.sort(
        key=lambda group: group.keeper.created_at or _UNKNOWN_CREATED_AT,
        reverse=True,
    )
    return groups


def _oldest_first(questions: list[Question]) -> list[Question]:
    """按"最早录入优先"排序。

    题目列表来自 ``QuestionRepository.search``（``created_at DESC, rowid DESC``），
    因此入库时间相同时（同秒入库的批次）列表**靠后**的那道才是先入库的，
    用下标倒序作为次序键，保证结果与传入顺序无关地稳定。
    """
    indexed = list(enumerate(questions))
    indexed.sort(key=lambda pair: (pair[1].created_at or _UNKNOWN_CREATED_AT, -pair[0]))
    return [question for _, question in indexed]
