"""Question 实体：题库中的一道题目（系统核心实体）。

字段结构与约束对应设计文档 "Data Models -> Question"，题型结构规则
由 app.domain.validators.question_validator 按需求 R3 校验。

依赖：app.domain.enums
被使用：app.domain.validators、app.interfaces.repositories、
        app.application.*、app.infrastructure.repositories、app.presentation.*
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.enums import (
    Difficulty,
    DifficultySource,
    QuestionSource,
    QuestionType,
    QualityFlag,
)


@dataclass
class Option:
    """选择题选项值对象。

    :param key: 选项标号，如 "A" / "B" / "C" / "D"
    :param text: 选项正文
    """

    key: str
    text: str


@dataclass
class Question:
    """题目实体。

    题型约定（需求 R3）：

    - 单选题：``options`` >= 2 条，``answer`` 恰为 1 个选项 key
    - 多选题：``options`` >= 2 条，``answer`` 为 1 个及以上选项 key
    - 解答题：``options`` 为空，``answer`` 为参考答案文本，``solution`` 为解析
    """

    id: str
    """唯一标识（uuid 字符串），入库时由仓储分配。"""

    subject: str
    """科目，组卷筛选的一级维度。"""

    knowledge_points: list[str] = field(default_factory=list)
    """关联知识点列表，用于选题覆盖度计算与 AI 补题。"""

    type: QuestionType = QuestionType.SINGLE
    """题型：single / multiple / solution。"""

    stem: str = ""
    """题干。"""

    options: list[Option] = field(default_factory=list)
    """选项列表；解答题恒为空列表。"""

    answer: list[str] = field(default_factory=list)
    """正确答案：选择题存选项 key 列表；解答题存参考答案文本（单元素列表）。"""

    solution: str | None = None
    """解析；解答题可选，选择题可为 None。"""

    difficulty: Difficulty = Difficulty.PENDING
    """难度：易 / 中 / 难；AI 分析完成前为 PENDING。"""

    difficulty_source: DifficultySource = DifficultySource.AI
    """难度来源：ai / manual；manual 的难度不被 AI 覆盖（需求 R5）。"""

    quality_flag: QualityFlag = QualityFlag.NORMAL
    """人工质量标记：normal / quality / low，参与选题评分（需求 R8）。"""

    source: QuestionSource = QuestionSource.BANK
    """题目来源：bank（手工录入）/ ai（AI 补题，需求 R10）。"""

    created_at: datetime | None = None
    """入库时间。"""

    updated_at: datetime | None = None
    """最后更新时间。"""

    @property
    def is_choice(self) -> bool:
        """是否属于"选择题部分"（单选或多选）。"""
        return self.type in (QuestionType.SINGLE, QuestionType.MULTIPLE)

    @property
    def is_solution(self) -> bool:
        """是否属于"解答题部分"。"""
        return self.type == QuestionType.SOLUTION


@dataclass
class QuestionFilter:
    """题库检索过滤器（需求 R6：按科目 / 知识点 / 难度 / 题型组合检索）。

    字段为 ``None`` 表示该维度不参与过滤；列表字段为空列表时同样视为不过滤。
    """

    subject: str | None = None
    """精确匹配的科目；None 表示不限。"""

    knowledge_point: str | None = None
    """知识点（命中题目的 knowledge_points 列表即可）；None 表示不限。"""

    difficulty: Difficulty | None = None
    """精确匹配的难度；None 表示不限。"""

    question_type: QuestionType | None = None
    """精确匹配的题型；None 表示不限。"""
