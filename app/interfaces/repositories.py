"""仓储层抽象接口定义。"""
from abc import ABC, abstractmethod
from datetime import datetime
from app.domain.entities.question import Question, QuestionFilter
from app.domain.entities.usage_record import UsageRecord
from app.domain.entities.task import GenerationTask
from app.domain.entities.question_op import QuestionOpRecord
from app.domain.entities.configs import (
    AIConfig,
    DebugConfig,
    PromptConfig,
    ScoringConfig,
)
from app.domain.entities.knowledge_section import KnowledgeSection

class QuestionRepository(ABC):
    """题目仓储抽象接口。"""

    @abstractmethod
    def save(self, question: Question) -> Question:
        """新增题目并返回落库后的实体（分配 id）。"""
        pass

    @abstractmethod
    def get(self, question_id: str) -> Question | None:
        """按 id 读取题目。"""
        pass

    @abstractmethod
    def update(self, question: Question) -> Question:
        """更新题目，保留原 id。"""
        pass

    @abstractmethod
    def delete(self, question_id: str) -> None:
        """删除题目。"""
        pass

    @abstractmethod
    def search(self, question_filter: QuestionFilter) -> list[Question]:
        """按条件组合检索题目。"""
        pass

    @abstractmethod
    def count_available(self, subject: str, difficulty: str, question_type: str,
                        knowledge_points: list[str] | None = None, section: str | None = None) -> int:
        """统计符合条件的可用题目数量。"""
        pass

    @abstractmethod
    def list_knowledge_points(self, subject: str | None = None) -> list[str]:
        """返回题库中已出现过的知识点列表。"""
        pass

    @abstractmethod
    def count_by_type(self) -> dict[str, int]:
        """按题型统计题量。"""
        pass

    @abstractmethod
    def count_by_image(self, image_path: str) -> int:
        """统计引用指定图片的题目数量。"""
        pass


class UsageRepository(ABC):
    """使用记录仓储抽象接口。"""

    @abstractmethod
    def record_usage(self, question_ids: list[str], used_at: datetime) -> None:
        """记录一组题目被使用。"""
        pass

    @abstractmethod
    def get(self, question_id: str) -> UsageRecord:
        """读取单题使用记录（无记录返回零值对象）。"""
        pass

    @abstractmethod
    def get_many(self, question_ids: list[str]) -> dict[str, UsageRecord]:
        """批量读取使用记录。"""
        pass


class TaskRepository(ABC):
    """组卷任务仓储抽象接口。"""

    @abstractmethod
    def save_task(self, task: GenerationTask) -> None:
        """保存组卷任务。"""
        pass

    @abstractmethod
    def get_task(self, task_id: str) -> GenerationTask | None:
        """读取单个任务。"""
        pass

    @abstractmethod
    def list_tasks(self) -> list[GenerationTask]:
        """列出所有任务（按时间倒序）。"""
        pass


class QuestionOpRepository(ABC):
    """题库操作台账仓储抽象接口。"""

    @abstractmethod
    def record(self, record: QuestionOpRecord) -> None:
        """记录一次操作。"""
        pass

    @abstractmethod
    def list_records(self, actions: list[str] | None = None, limit: int | None = None) -> list[QuestionOpRecord]:
        """查询操作记录。"""
        pass


class ConfigStore(ABC):
    """配置存储抽象接口。"""

    @abstractmethod
    def load_debug_config(self) -> DebugConfig: pass

    @abstractmethod
    def save_debug_config(self, config: DebugConfig) -> None: pass

    @abstractmethod
    def load_ai_config(self) -> AIConfig: pass
    @abstractmethod
    def save_ai_config(self, config: AIConfig) -> None: pass
    @abstractmethod
    def load_scoring_config(self) -> ScoringConfig: pass
    @abstractmethod
    def save_scoring_config(self, config: ScoringConfig) -> None: pass
    @abstractmethod
    def load_prompt_config(self) -> PromptConfig: pass
    @abstractmethod
    def save_prompt_config(self, config: PromptConfig) -> None: pass
    @abstractmethod
    def load_subjects(self) -> list[str]: pass
    @abstractmethod
    def save_subjects(self, subjects: list[str]) -> None: pass
    @abstractmethod
    def load_sections(self) -> list[KnowledgeSection]: pass
    @abstractmethod
    def save_sections(self, sections: list[KnowledgeSection]) -> None: pass

    @abstractmethod
    def load_table_state(self, key: str) -> str | None: pass

    @abstractmethod
    def save_table_state(self, key: str, state: str) -> None: pass
