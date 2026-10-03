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
        raise NotImplementedError("TODO(R3): 实现题型规则校验")

    def validate_many(self, questions: list[Question]) -> list[Question]:
        """批量校验，返回通过校验的题目列表。

        :param questions: 待校验题目列表（批量粘贴场景）
        :return: 全部通过校验的题目；未通过项由调用方结合异常消息处理
        :raises QuestionValidationError: 用于承载逐条失败的聚合信息
        """
        raise NotImplementedError("TODO(R3): 实现批量校验")
