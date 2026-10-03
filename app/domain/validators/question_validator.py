"""题型规则校验器（需求 Requirement 3）。

校验规则（与需求逐条对应）：

- 单选题：选项 >= 2 个，答案恰为 1 个且必须是选项 key
- 多选题：选项 >= 2 个，答案 >= 1 个且必须都是选项 key
- 解答题：无选项，参考答案非空，解析可选
- 通用：科目、题干、知识点非空

依赖：app.domain.entities.question、app.domain.enums、app.domain.errors
被使用：app.application.question_service（入库前校验）、
        app.application.question_generator（AI 补题校验，需求 R10 第 4 条）
"""

from app.domain.entities.question import Question
from app.domain.enums import QuestionType
from app.domain.errors import QuestionValidationError


class QuestionValidator:
    """题型规则校验器：无状态，可全局共享同一实例。"""

    def validate(self, question: Question) -> None:
        """校验题目结构，非法时抛出 :class:`QuestionValidationError`。

        :param question: 待校验的题目实体
        :raises QuestionValidationError: 任一规则不满足时抛出，消息指明不一致原因
        """
        if not question.subject or not question.subject.strip():
            raise QuestionValidationError("科目不能为空，请先在设置中维护科目后选择")
        if not question.stem or not question.stem.strip():
            raise QuestionValidationError("题干不能为空")
        if not question.knowledge_points:
            raise QuestionValidationError("知识点不能为空，请至少填写一个知识点")

        keys = [option.key.strip().upper() for option in question.options if option.key.strip()]
        answers = [answer.strip().upper() for answer in question.answer if answer.strip()]

        if question.type is QuestionType.SOLUTION:
            if question.options:
                raise QuestionValidationError("解答题不应包含选项")
            if not answers:
                raise QuestionValidationError("解答题必须填写参考答案")
            return

        if question.type is QuestionType.FILL:
            if question.options:
                raise QuestionValidationError("填空题不应包含选项")
            if not answers:
                raise QuestionValidationError("填空题必须填写参考答案（多个空用分号分隔）")
            return

        if len([option for option in question.options if option.text.strip() or option.key.strip()]) < 2:
            raise QuestionValidationError("选择题至少需要 2 个选项")
        if not answers:
            raise QuestionValidationError("选择题必须填写答案")
        invalid = [answer for answer in answers if answer not in keys]
        if invalid:
            raise QuestionValidationError(
                "答案与选项标号不一致：" + "，".join(invalid)
            )
        if question.type is QuestionType.SINGLE and len(answers) != 1:
            raise QuestionValidationError("单选题的答案必须恰为 1 个选项")
        if question.type is QuestionType.MULTIPLE and len(set(answers)) < 1:
            raise QuestionValidationError("多选题的答案至少为 1 个选项")

    def validate_many(self, questions: list[Question]) -> list[Question]:
        """批量校验，返回通过校验的题目列表。

        :param questions: 待校验题目列表（批量粘贴场景）
        :return: 全部通过校验的题目；未通过项由调用方结合异常消息处理
        :raises QuestionValidationError: 用于承载逐条失败的聚合信息
        """
        passed: list[Question] = []
        failures: list[str] = []
        for index, question in enumerate(questions, start=1):
            try:
                self.validate(question)
            except QuestionValidationError as exc:
                failures.append(f"第 {index} 题：{exc}")
            else:
                passed.append(question)
        if failures:
            raise QuestionValidationError("；".join(failures))
        return passed
