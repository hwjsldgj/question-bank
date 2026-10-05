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

    取值与需求文档 Glossary 一致，并新增用户要求的填空题：

    - ``SINGLE``    单选题（属于"选择题部分"）
    - ``MULTIPLE``  多选题（属于"选择题部分"）
    - ``FILL``      填空题（属于"填空题部分"，无选项，答案为文本）
    - ``SOLUTION``  解答题（属于"解答题部分"）
    """

    SINGLE = "single"
    MULTIPLE = "multiple"
    FILL = "fill"
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
    """试卷分区：选择题部分（choice）/ 填空题部分（fill）/ 解答题部分（solution）。

    需求 R7 / R12：各部分均可独立启用或停用。
    """

    CHOICE = "choice"
    FILL = "fill"
    SOLUTION = "solution"


class ExportFormat(str, Enum):
    """导出格式：MD / PDF（需求 R12）。

    ``MD`` 输出 Markdown 源文件（原 TXT 输出改为 .md，内容不变）；
    ``PDF`` 由同一份 Markdown 转换而来。
    """

    MD = "md"
    PDF = "pdf"


class CooldownMode(str, Enum):
    """冷却窗口的计量方式：按天数（days）或按最近 N 次组卷任务（tasks）。"""

    DAYS = "days"
    TASKS = "tasks"


class QuestionOpAction(str, Enum):
    """题库操作类型：用于"导入历史 / 编辑历史"台账。

    - ``CREATE`` 单题录入
    - ``UPDATE`` 题目编辑（含难度 / 质量标记修正）
    - ``DELETE`` 题目删除
    - ``IMPORT`` 批量导入（粘贴解析或图片批量入库）
    """

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    IMPORT = "import"


class RecognizeModule(str, Enum):
    """AI 辨识模块：可"按需给出、一次返回"的字段单元（用户需求）。

    每个模块对应题目实体的一个字段，并各自拥有一段可编辑的输出提示词
    （见 app.config.settings.DEFAULT_MODULE_PROMPTS 与 PromptConfig.module_prompts）。
    出题者只勾选需要的模块，服务层便只拼装这些模块的提示词与期望结构，
    用一次 AI 调用返回全部所需字段，未请求的字段不会被生成。

    - ``SUBJECT`` 科目（必填）
    - ``KNOWLEDGE_POINTS`` 知识点（必填）
    - ``QUESTION_TYPE`` 题型
    - ``DIFFICULTY`` 难度（选填，未给出时保持"待确认"）
    - ``QUALITY_FLAG`` 质量标记（选填，默认"普通"）
    - ``ANSWER`` 答案 / 参考答案（必填）
    - ``SOLUTION`` 解析（选填，可要求不生成）
    - ``STEM`` 题干（选填，原文残缺时可要求 AI 补全）
    - ``OPTIONS`` 选项（选填，不足 2 项时可要求 AI 补充）
    """

    SUBJECT = "subject"
    KNOWLEDGE_POINTS = "knowledge_points"
    QUESTION_TYPE = "question_type"
    DIFFICULTY = "difficulty"
    QUALITY_FLAG = "quality_flag"
    ANSWER = "answer"
    SOLUTION = "solution"
    STEM = "stem"
    OPTIONS = "options"
