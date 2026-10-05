"""PaperCriteria 实体：组卷条件。

对应需求 R7：出题者分别启用/停用"选择题部分"与"解答题部分"，
并为启用部分指定科目、难度与数量。合法性由表现层入口校验
（全停用应拒绝），部分数量守恒关系见设计文档 Correctness Properties #4。

依赖：app.domain.enums
被使用：app.application.paper_composer、app.application.task_history_service、
        app.presentation.views.paper_generation_view
"""

from dataclasses import dataclass, field

from app.domain.enums import CooldownMode, Difficulty, QuestionType


@dataclass
class TypeRequirement:
    """单个题型的出题要求值对象。

    :param question_type: 题型（single / multiple / fill / solution）
    :param subject: 科目
    :param difficulty: 目标难度（易 / 中 / 难）
    :param count: 需要的题目数量（正整数）
    :param knowledge_points: 指定知识点（用户需求：组卷时可指定知识点）；
        空列表表示不限，非空表示只统计 / 选取命中其中任一知识点的题目
    """

    question_type: QuestionType
    subject: str
    difficulty: Difficulty
    count: int
    knowledge_points: list[str] = field(default_factory=list)


@dataclass
class PaperCriteria:
    """组卷条件实体。

    单选 / 多选 / 填空 / 解答四类题型各自独立启用（用户需求：单选多选分开）；
    每类题型可配置多条出题要求（界面按"知识点 × 难度"逐行配置题数），
    至少一条要求，否则拒绝请求（需求 R7 第 4 条）。
    """

    choice_enabled: bool = False
    """是否启用"选择题部分"（单选或多选任一启用即视为启用）。"""

    solution_enabled: bool = False
    """是否启用"解答题部分"。"""

    choice_items: list[TypeRequirement] = field(default_factory=list)
    """选择题部分内各题型（单选 / 多选）的出题要求。"""

    fill_enabled: bool = False
    """是否启用"填空题部分"（用户新增题型）。"""

    fill_items: list[TypeRequirement] = field(default_factory=list)
    """填空题部分的出题要求（可按知识点 × 难度配置多条）。"""

    solution_items: list[TypeRequirement] = field(default_factory=list)
    """解答题部分的出题要求（可按知识点 × 难度配置多条）。"""

    subject: str = ""
    """全局科目：一次组卷只针对一个科目（用户需求）。"""

    def enabled_requirements(self) -> list[TypeRequirement]:
        """返回所有启用部分的题型要求列表（组卷引擎按此逐条选题）。"""
        requirements: list[TypeRequirement] = []
        if self.choice_enabled:
            requirements.extend(self.choice_items)
        if self.fill_enabled:
            requirements.extend(self.fill_items)
        if self.solution_enabled:
            requirements.extend(self.solution_items)
        return requirements

    @staticmethod
    def cooldown_mode_default() -> CooldownMode:
        """返回冷却窗口的默认计量方式（按天数）。

        仅供界面初始化时读取默认值，冷却窗口本体配置见
        app.domain.entities.configs.ScoringConfig。
        """
        return CooldownMode.DAYS
