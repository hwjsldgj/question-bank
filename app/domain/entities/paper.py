"""Paper / Section 实体：试卷与分区。

对应设计文档 "Data Models -> Paper"。组卷引擎（PaperComposer）产出本结构，
分值计算器（ScoreCalculator）填充分值，导出器（PaperExporter）按本结构排版。

依赖：app.domain.entities.question、app.domain.enums
被使用：app.application.paper_composer、app.application.score_calculator、
        app.application.paper_exporter、app.infrastructure.exporters、
        app.interfaces.exporters
"""

from dataclasses import dataclass, field

from app.domain.entities.criteria import PaperCriteria
from app.domain.entities.question import Question
from app.domain.enums import QuestionType, SectionKind


@dataclass
class AnswerEntry:
    """答案页中单道题的答案条目（需求 R12 第 6 条）。

    :param question_id: 题目唯一标识
    :param answer: 正确答案（选择题为选项 key 组合；解答题为参考答案文本）
    :param solution: 解析；解答题应尽量提供，选择题可为 None
    """

    question_id: str
    answer: str
    solution: str | None = None


@dataclass
class Section:
    """试卷分区值对象。

    不变量（设计文档 Correctness Properties）：

    - 卷内无重复：同一 Paper 内所有 Section 的 questions 不存在重复 id（#2）
    - 数量守恒：questions 实际题数等于对应 TypeRequirement.count（#4）
    - 总分一致：subtotal 等于本分区每题分值之和（#5）
    """

    section_kind: SectionKind
    """所属部分：choice（选择题部分）/ solution（解答题部分）。"""

    question_type: QuestionType
    """本分区题型：single / multiple / solution。"""

    questions: list[Question] = field(default_factory=list)
    """入选题目列表，顺序即卷面顺序。"""

    per_question_score: float | None = None
    """统一单题分值；为 None 时使用 question_scores 逐题分值。"""

    question_scores: dict[str, float] = field(default_factory=dict)
    """逐题分值覆盖表：question_id -> 分值，优先于 per_question_score。"""

    answer_page: list[AnswerEntry] = field(default_factory=list)
    """本分区的答案页条目，导出时写入卷末答案区。"""

    def score_of(self, question_id: str) -> float | None:
        """返回某题的生效分值：优先逐题分值，其次统一分值，均未设置返回 None。"""
        if question_id in self.question_scores:
            return self.question_scores[question_id]
        return self.per_question_score


@dataclass
class Paper:
    """试卷实体：一次组卷任务的产出。

    ``sections`` 顺序约定：选择题部分在前（单选、多选依次），解答题部分在后。
    """

    criteria: PaperCriteria
    """生成试卷所用的组卷条件。"""

    sections: list[Section] = field(default_factory=list)
    """分区列表，仅包含被启用部分的分区。"""

    total_score: float = 0.0
    """试卷总分 = Σ 各分区 subtotal（需求 R11）。"""

    def questions(self) -> list[Question]:
        """按卷面顺序返回全部题目（跨分区拼接）。"""
        return [q for section in self.sections for q in section.questions]
