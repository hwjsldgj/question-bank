"""领域枚举定义。

集中定义系统中所有受限取值，供领域实体、应用服务与表现层共同引用，
保证"题型 / 难度 / 来源"等概念在全局取值一致。

依赖：无（领域层最底层模块）
被使用：app.domain.entities.*、app.domain.validators、app.application.*、
        app.infrastructure.*、app.presentation.*
"""

from enum import Enum


class QuestionType(str, Enum):
    """题型枚举。

    取值与需求文档 Glossary 一致：

    - ``SINGLE``    单选题（属于"选择题部分"）
    - ``MULTIPLE``  多选题（属于"选择题部分"）
    - ``SOLUTION``  解答题（属于"解答题部分"）
    """

    SINGLE = "single"
    MULTIPLE = "multiple"
    SOLUTION = "solution"


class Difficulty(str, Enum):
    """难度枚举：易 / 中 / 难 三级，外加"待确认"过渡态。

    ``PENDING`` 仅在 AI 难度分析失败或未完成时出现（需求 R4），
    组卷筛选条件中不允许使用 ``PENDING``。
    """

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    PENDING = "pending"


class DifficultySource(str, Enum):
    """难度来源：AI 分析（ai）或人工设置（manual）。

    需求 R5：来源为 manual 的难度不被后续 AI 分析覆盖。
    """

    AI = "ai"
    MANUAL = "manual"


class QualityFlag(str, Enum):
    """人工质量标记：普通 / 优质 / 低质。

    参与选题评分（需求 R8）：优质加分、低质减分。
    """

    NORMAL = "normal"
    QUALITY = "quality"
    LOW = "low"


class QuestionSource(str, Enum):
    """题目来源：题库录入（bank）或 AI 生成（ai）。

    需求 R10：AI 补题入库后必须带 AI 来源标记，保证可溯源。
    """

    BANK = "bank"
    AI = "ai"


class SectionKind(str, Enum):
    """试卷分区：选择题部分（choice）/ 解答题部分（solution）。

    需求 R7 / R12：两部分均可独立启用或停用。
    """

    CHOICE = "choice"
    SOLUTION = "solution"


class ExportFormat(str, Enum):
    """导出格式：TXT / PDF（需求 R12）。"""

    TXT = "txt"
    PDF = "pdf"


class CooldownMode(str, Enum):
    """冷却窗口的计量方式：按天数（days）或按最近 N 次组卷任务（tasks）。"""

    DAYS = "days"
    TASKS = "tasks"
