"""领域异常体系。

所有业务校验失败与领域规则违反均抛出本模块定义的异常；
表现层统一捕获并转化为用户可读的提示（需求中的"拒绝并提示"类行为）。

依赖：无
被使用：app.domain.validators、app.application.*、app.infrastructure.exporters、
        app.presentation.*
"""


class DomainError(Exception):
    """领域异常基类：所有业务异常的公共父类，便于表现层统一捕获。"""


class QuestionValidationError(DomainError):
    """题目结构不符合题型规则（需求 R3），例如单选题答案数不为 1。"""


class CriteriaValidationError(DomainError):
    """组卷条件非法（需求 R7），例如所有部分均被停用或数量非正整数。"""


class ScoreValidationError(DomainError):
    """分值设置不完整或非法（需求 R11），例如存在未设分值的题目时导出。"""


class AIServiceError(DomainError):
    """AI API 调用失败、超时或返回无效结果（需求 R4 / R10 / R15）。"""


class AIConfigMissingError(AIServiceError):
    """AI 服务未配置（需求 R15），提示用户后保持库内功能可用。"""


class ExportError(DomainError):
    """试卷导出失败（需求 R12 / R18），例如目录不可写或运行环境缺失。"""
