"""Question 实体：题库中的一道题目（系统核心实体）。

字段结构与约束对应设计文档 "Data Models -> Question"，题型结构规则
由 app.domain.validators.question_validator 按需求 R3 校验。

依赖：app.domain.enums
被使用：app.domain.validators、app.interfaces.repositories、
        app.application.*、app.infrastructure.repositories、app.presentation.*
"""

from dataclasses import dataclass, field
from datetime import datetime
import re
import unicodedata

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

    section: str = ""
    """所属知识点板块（科目的二级分组）。

    一道题可以属于多个板块（用户需求），多个板块以"、"分隔存储，
    如 ``"代数、几何"``；拆分与匹配统一用 :func:`split_sections`。
    """

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

    typst_source: str | None = None
    """题目的原始 Typst 渲染源码；导出时即时渲染为图片插入试卷。"""

    image_path: str | None = None
    """题目图片的本地相对路径（相对数据库所在目录，如 ``images/xxx.png``）。

    导入时由图片存储复制到本地 ``images/`` 目录后写入；仅做本地存储与
    界面展示，不参与 AI 难度分析与 AI 辨识。
    """

    created_at: datetime | None = None
    """入库时间。"""

    updated_at: datetime | None = None
    """最后更新时间。"""

    @property
    def is_choice(self) -> bool:
        """是否属于"选择题部分"（单选或多选）。"""
        return self.type in (QuestionType.SINGLE, QuestionType.MULTIPLE)

    @property
    def is_fill(self) -> bool:
        """是否为填空题（无选项，答案为文本，用户新增题型）。"""
        return self.type == QuestionType.FILL

    @property
    def is_solution(self) -> bool:
        """是否属于"解答题部分"。"""
        return self.type == QuestionType.SOLUTION

    @property
    def has_options(self) -> bool:
        """该题型是否需要选项（选择题需要，填空题与解答题不需要）。"""
        return self.is_choice


def split_sections(text: str | None) -> list[str]:
    """把板块文本拆分为板块列表（用户需求：一道题可属于多个知识点板块）。

    支持顿号、逗号、分号与空白分隔，并去除重复与空白项，
    与知识点的录入 / 匹配口径一致。

    :param text: 形如 ``"代数、几何"`` 的板块文本；None 或空串返回空列表
    :return: 去重后的板块列表（保持出现顺序）
    """
    parts = [part.strip() for part in re.split(r"[,，、;；\s]+", text or "")]
    return list(dict.fromkeys(part for part in parts if part))


def stem_fingerprint(stem: str | None) -> str:
    """题干指纹：题库自动去重时判定"两道题题干是否相同"的依据（用户需求）。

    归一化步骤：

    1. Unicode NFKC 归一化：全角 / 半角、兼容字形（如 ``Ａ`` 与 ``A``）统一
    2. 转小写（``casefold``），忽略英文大小写差异
    3. 剔除标点（``P*``）、空白与分隔符（``Z*``）、控制与格式字符（``C*``），
       保留文字、数字与数学符号（``+ - = × ÷ √`` 等不参与忽略，避免
       ``x+1`` 与 ``x1`` 被误判为同一题）

    :param stem: 题干文本；None 或空串返回空串（无有效题干，调用方应跳过）
    :return: 归一化后的指纹字符串
    """
    text = unicodedata.normalize("NFKC", stem or "").casefold()
    return "".join(
        char
        for char in text
        if not unicodedata.category(char).startswith(("P", "Z", "C"))
    )


@dataclass
class QuestionFilter:
    """题库检索过滤器（需求 R6：按科目 / 知识点 / 难度 / 题型组合检索）。

    字段为 ``None`` 表示该维度不参与过滤；列表字段为空列表时同样视为不过滤。
    """

    subject: str | None = None
    """精确匹配的科目；None 表示不限。"""

    section: str | None = None
    """知识点板块；None 表示不限。

    可写单个板块或"代数、几何"这类多板块文本，命中其中任一板块的题目即匹配
    （用户需求：一道题可属于多个板块）。
    """

    knowledge_point: str | None = None
    """知识点（命中题目的 knowledge_points 列表即可）；None 表示不限。"""

    difficulty: Difficulty | None = None
    """精确匹配的难度；None 表示不限。"""

    question_type: QuestionType | None = None
    """精确匹配的题型；None 表示不限。"""
