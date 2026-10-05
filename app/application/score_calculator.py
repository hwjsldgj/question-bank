"""分值计算器：每题分值、分区小计与试卷总分（需求 R11）。

支持两种设置方式：按题型统一分值（per_question_score）或逐题分值覆盖
（question_scores）；小计 = Σ 每题生效分值，总分 = Σ 分区小计。

依赖：app.domain.entities.paper（Paper / Section / AnswerEntry）、
      app.domain.entities.question、app.domain.errors
被使用：app.application.paper_composer（组卷后汇总）、
        app.presentation.views.paper_generation_view（分值编辑）
"""

from app.domain.entities.paper import AnswerEntry, Paper, Section
from app.domain.entities.question import Question
from app.domain.errors import ScoreValidationError


class ScoreCalculator:
    """分值计算器：试卷分值体系的唯一读写入口。"""

    def set_type_score(self, section: Section, per_question_score: float) -> None:
        """按题型设置统一单题分值（需求 R11 第 1 条）。"""
        section.per_question_score = float(per_question_score)

    def set_question_score(self, section: Section, question_id: str, score: float) -> None:
        """为单道题目设置分值，覆盖统一分值（需求 R11 第 1 条）。"""
        section.question_scores[question_id] = float(score)

    def section_subtotal(self, section: Section) -> float:
        """计算分区小计：Σ 该分区每题生效分值（需求 R11 第 2 条）。

        :raises ScoreValidationError: 分区内存在未设置分值的题目
        """
        subtotal = 0.0
        for question in section.questions:
            score = section.score_of(question.id)
            if score is None:
                raise ScoreValidationError(
                    f"题目未设置分值：{question.stem[:20] or question.id}"
                )
            subtotal += float(score)
        return round(subtotal, 6)

    def total_score(self, paper: Paper) -> float:
        """汇总试卷总分（需求 R11 第 3 条），并回写 ``paper.total_score``。"""
        paper.total_score = round(
            sum(self.section_subtotal(section) for section in paper.sections), 6
        )
        return paper.total_score

    def build_answer_page(self, paper: Paper) -> None:
        """为每个分区填充答案页条目（需求 R12 第 6 条；解答题含参考答案与解析）。"""
        for section in paper.sections:
            section.answer_page = [
                AnswerEntry(
                    question_id=question.id,
                    answer=self._answer_text(question),
                    solution=question.solution,
                )
                for question in section.questions
            ]

    @staticmethod
    def _answer_text(question: Question) -> str:
        """题目实体 -> 答案文本（选择题为选项 key 组合，其余取参考答案）。"""
        if question.is_choice:
            return "、".join(question.answer)
        return question.answer[0] if question.answer else ""
