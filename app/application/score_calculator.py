"""分值计算器：每题分值、分区小计与试卷总分（需求 R11）。

支持两种设置方式：按题型统一分值（per_question_score）或逐题分值覆盖
（question_scores）；小计 = 数量 × 单题分值，总分 = Σ 分区小计。

依赖：app.domain.entities.paper（Paper / Section）
被使用：app.application.paper_composer（组卷后汇总）、
        app.presentation.views.paper_generation_view（分值编辑）
"""

from app.domain.entities.paper import Paper, Section


class ScoreCalculator:
    """分值计算器：试卷分值体系的唯一读写入口。"""

    def set_type_score(self, section: Section, per_question_score: float) -> None:
        """按题型设置统一单题分值（需求 R11 第 1 条）。"""
        raise NotImplementedError("TODO(R11): 实现统一分值设置")

    def set_question_score(self, section: Section, question_id: str, score: float) -> None:
        """为单道题目设置分值，覆盖统一分值（需求 R11 第 1 条）。"""
        raise NotImplementedError("TODO(R11): 实现逐题分值设置")

    def section_subtotal(self, section: Section) -> float:
        """计算分区小计：Σ 该分区每题生效分值（需求 R11 第 2 条）。"""
        raise NotImplementedError("TODO(R11): 实现分区小计计算")

    def total_score(self, paper: Paper) -> float:
        """汇总试卷总分：Σ 各分区小计（需求 R11 第 3 条）。"""
        raise NotImplementedError("TODO(R11): 实现总分汇总")

    def build_answer_page(self, paper: Paper) -> None:
        """为每个分区填充答案页条目（需求 R12 第 6 条；解答题含参考答案与解析）。"""
        raise NotImplementedError("TODO(R12): 实现答案页数据生成")
