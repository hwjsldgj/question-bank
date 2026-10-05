"""仓储与配置存储抽象接口。

定义题目、使用记录、组卷任务三类数据的读写契约，以及 AI / 评分配置的
存取契约。应用服务层仅通过本模块访问数据；SQLite 实现见
``app.infrastructure.repositories`` 与 ``app.infrastructure.config_store``。

依赖：app.domain.entities.configs、app.domain.entities.question、
      app.domain.entities.task、app.domain.entities.usage_record
被使用（调用方）：app.application.*（全部服务）
被实现（实现方）：app.infrastructure.repositories.*、app.infrastructure.config_store
"""

from abc import ABC, abstractmethod
from datetime import datetime

from app.domain.entities.configs import AIConfig, PromptConfig, ScoringConfig
from app.domain.entities.knowledge_section import KnowledgeSection
from app.domain.entities.question import Question, QuestionFilter
from app.domain.entities.question_op import QuestionOpRecord
from app.domain.entities.task import GenerationTask
from app.domain.entities.usage_record import UsageRecord


class QuestionRepository(ABC):
    """题目仓储接口：题库 CRUD 与按条件检索。

    实现方：app.infrastructure.repositories.question_repository.SQLiteQuestionRepository
    调用方：app.application.question_service、app.application.paper_composer
    """

    @abstractmethod
    def save(self, question: Question) -> Question:
        """新增一道题目并分配唯一标识（需求 R1 第 1 条）。"""

    @abstractmethod
    def get(self, question_id: str) -> Question | None:
        """按 id 读取题目；不存在时返回 None。"""

    @abstractmethod
    def update(self, question: Question) -> Question:
        """更新题目内容，保留唯一标识与使用记录（需求 R1 第 3 条）。"""

    @abstractmethod
    def delete(self, question_id: str) -> None:
        """删除题目，使其不再参与后续组卷（需求 R1 第 4 条）。"""

    @abstractmethod
    def search(self, question_filter: QuestionFilter) -> list[Question]:
        """按科目 / 知识点 / 难度 / 题型组合检索（需求 R6 第 1 条）。"""

    @abstractmethod
    def count_available(
        self,
        subject: str,
        difficulty: str,
        question_type: str,
        knowledge_points: list[str] | None = None,
        section: str | None = None,
    ) -> int:
        """统计满足组卷条件的命中题数量（需求 R6 第 2 条）。

        :param knowledge_points: 指定知识点（用户需求：组卷可指定知识点）；
            为空表示不限，非空表示命中其中任一知识点的题目才计入
        :param section: 指定知识点板块（用户需求：组卷可选知识点板块作为限定）；
            为空表示不限
        """

    @abstractmethod
    def list_knowledge_points(self, subject: str | None = None) -> list[str]:
        """返回知识点字典（可按科目过滤），供录入与检索自动补全。"""

    @abstractmethod
    def count_by_type(self) -> dict[str, int]:
        """按题型统计题量（题库概览），key 为题型取值。"""

    @abstractmethod
    def count_by_image(self, image_path: str) -> int:
        """统计引用同一图片路径的题目数（删除题目时判断图片能否清理）。"""


class UsageRepository(ABC):
    """使用记录仓储接口：近期重复抑制（需求 R13）的数据读写。

    实现方：app.infrastructure.repositories.usage_repository.SQLiteUsageRepository
    调用方：app.application.paper_composer、app.application.selection_scorer
    """

    @abstractmethod
    def record_usage(self, question_ids: list[str], used_at: datetime) -> None:
        """批量记录一次入卷：use_count 加一并更新 last_used_at（需求 R13 第 1 条）。"""

    @abstractmethod
    def get(self, question_id: str) -> UsageRecord:
        """读取单题使用记录；无记录时返回零值记录（use_count=0）。"""

    @abstractmethod
    def get_many(self, question_ids: list[str]) -> dict[str, UsageRecord]:
        """批量读取使用记录，key 为题目 id（评分器批量取数用）。"""


class TaskRepository(ABC):
    """组卷任务仓储接口：历史保存与查询（需求 R14）。

    实现方：app.infrastructure.repositories.task_repository.SQLiteTaskRepository
    调用方：app.application.task_history_service
    """

    @abstractmethod
    def save_task(self, task: GenerationTask) -> None:
        """保存或更新组卷任务（含导出记录）。"""

    @abstractmethod
    def get_task(self, task_id: str) -> GenerationTask | None:
        """按 id 读取任务；不存在时返回 None。"""

    @abstractmethod
    def list_tasks(self) -> list[GenerationTask]:
        """按创建时间倒序返回全部任务（需求 R14 第 2 条）。"""


class QuestionOpRepository(ABC):
    """题库操作台账仓储接口：导入历史与编辑历史（用户需求）。

    实现方：app.infrastructure.repositories.question_op_repository
    调用方：app.application.question_service（写入）、app.application.question_history_service（读取）
    """

    @abstractmethod
    def record(self, record: QuestionOpRecord) -> None:
        """追加一条题库操作记录。"""

    @abstractmethod
    def list_records(
        self, actions: list[str] | None = None, limit: int | None = None
    ) -> list[QuestionOpRecord]:
        """按操作类型筛选并返回记录（按时间倒序）。"""


class ConfigStore(ABC):
    """配置存储接口：AI 配置、评分配置、提示词、科目与知识点板块的持久化（需求 R15）。

    密钥仅保存在本机（需求 R18），实现方不得外传。

    实现方：app.infrastructure.config_store.SQLiteConfigStore
    调用方：app.container（装配时加载）、app.presentation.views.settings_view
    """

    @abstractmethod
    def load_ai_config(self) -> AIConfig:
        """读取 AI 配置；无配置时返回带默认值的 AIConfig（视为未配置）。"""

    @abstractmethod
    def save_ai_config(self, config: AIConfig) -> None:
        """保存 AI 配置（需求 R15 第 3 条：新配置用于后续调用）。"""

    @abstractmethod
    def load_scoring_config(self) -> ScoringConfig:
        """读取评分与冷却配置；无配置时返回 app.config.settings 的默认值。"""

    @abstractmethod
    def save_scoring_config(self, config: ScoringConfig) -> None:
        """保存评分与冷却配置（需求 R8 第 7 条 / R13 第 4 条）。"""

    @abstractmethod
    def load_prompt_config(self) -> PromptConfig:
        """读取 AI 提示词配置；无配置时返回默认模板。"""

    @abstractmethod
    def save_prompt_config(self, config: PromptConfig) -> None:
        """保存 AI 提示词配置，用于后续 AI 调用。"""

    @abstractmethod
    def load_subjects(self) -> list[str]:
        """读取可选科目列表；无配置时返回默认科目。"""

    @abstractmethod
    def save_subjects(self, subjects: list[str]) -> None:
        """保存可选科目列表（科目改为选择式录入后由设置界面维护）。"""

    @abstractmethod
    def load_sections(self) -> list[KnowledgeSection]:
        """读取知识点板块列表；无配置时返回默认值。"""

    @abstractmethod
    def save_sections(self, sections: list[KnowledgeSection]) -> None:
        """保存知识点板块映射（科目改为选择式录入后由设置界面维护）。"""
