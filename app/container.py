"""组合根（Composition Root）与轻量依赖注入容器。

程序中唯一知晓具体实现类型的位置：把基础设施实现装配为抽象接口，
再构造应用服务与表现层所需的完整对象图。

装配关系（依赖方向）::

    DatabaseConnection -> SQLiteXxxRepository / SQLiteConfigStore
    配置提供者          -> OpenAICompatibleAIClient（保存设置后立即生效）
    上述实现            -> QuestionService / DifficultyService / PaperComposer 等
    Container          -> MainWindow（表现层）

依赖：app.config.settings、app.domain.entities.configs、
      app.application.*、app.infrastructure.*、app.interfaces.*
被使用：main.py、app.presentation.main_window
"""

from dataclasses import dataclass
from pathlib import Path

from app.application.cooldown_policy import CooldownPolicy
from app.application.difficulty_service import DifficultyService
from app.application.paper_composer import PaperComposer
from app.application.paper_exporter import PaperExporter
from app.application.question_generator import QuestionGenerator
from app.application.question_history_service import QuestionHistoryService
from app.application.question_service import QuestionService
from app.application.score_calculator import ScoreCalculator
from app.application.selection_scorer import SelectionScorer
from app.application.task_history_service import TaskHistoryService
from app.application.weighted_sampler import WeightedSampler
from app.config.settings import (
    DEFAULT_DB_PATH,
    DEFAULT_IMAGE_DIR,
    DEFAULT_SCORING_CONFIG,
    QUESTION_GENERATOR_MAX_RETRIES,
)
from app.domain.entities.configs import ScoringConfig
from app.domain.validators.question_validator import QuestionValidator
from app.domain.validators.score_validator import ScoreValidator
from app.infrastructure.ai.ai_client import OpenAICompatibleAIClient
from app.infrastructure.config_store import SQLiteConfigStore
from app.infrastructure.database.connection import DatabaseConnection
from app.infrastructure.exporters.pdf_exporter import PdfExporter
from app.infrastructure.exporters.txt_exporter import TxtExporter
from app.infrastructure.image_store import LocalImageStore
from app.infrastructure.repositories.question_op_repository import (
    SQLiteQuestionOpRepository,
)
from app.infrastructure.repositories.question_repository import SQLiteQuestionRepository
from app.infrastructure.repositories.task_repository import SQLiteTaskRepository
from app.infrastructure.repositories.usage_repository import SQLiteUsageRepository
from app.interfaces.ai_client import AIClient
from app.interfaces.exporters import BaseExporter
from app.interfaces.repositories import (
    ConfigStore,
    QuestionOpRepository,
    QuestionRepository,
    TaskRepository,
    UsageRepository,
)
from app.domain.enums import ExportFormat


@dataclass
class Container:
    """应用对象图：按层聚合全部可协作对象，供界面与入口直接取用。"""

    # 基础设施
    db: DatabaseConnection
    question_repository: QuestionRepository
    usage_repository: UsageRepository
    task_repository: TaskRepository
    question_op_repository: QuestionOpRepository
    config_store: ConfigStore
    ai_client: AIClient
    image_store: LocalImageStore
    # 领域校验器
    question_validator: QuestionValidator
    score_validator: ScoreValidator
    # 应用服务
    difficulty_service: DifficultyService
    question_service: QuestionService
    cooldown_policy: CooldownPolicy
    selection_scorer: SelectionScorer
    weighted_sampler: WeightedSampler
    question_generator: QuestionGenerator
    score_calculator: ScoreCalculator
    paper_composer: PaperComposer
    paper_exporter: PaperExporter
    task_history_service: TaskHistoryService
    question_history_service: QuestionHistoryService


def build_container(db_path: str = DEFAULT_DB_PATH) -> Container:
    """装配完整对象图并返回容器（应用启动时调用一次）。

    :param db_path: 本地数据库文件路径，默认见 app.config.settings
    """
    db = DatabaseConnection(db_path)

    # 基础设施实现 -> 抽象接口
    question_repository: QuestionRepository = SQLiteQuestionRepository(db)
    usage_repository: UsageRepository = SQLiteUsageRepository(db)
    task_repository: TaskRepository = SQLiteTaskRepository(db)
    question_op_repository: QuestionOpRepository = SQLiteQuestionOpRepository(db)
    config_store: ConfigStore = SQLiteConfigStore(db)

    # AI 客户端按"配置提供者"构造：设置保存后后续调用立即使用新配置（R15-3）
    ai_client: AIClient = OpenAICompatibleAIClient(config_store.load_ai_config)

    scoring_config: ScoringConfig = config_store.load_scoring_config()

    # 题目图片本地存储（复制进数据库同级 images/ 目录，用户需求）
    image_store = LocalImageStore(Path(db_path).parent, DEFAULT_IMAGE_DIR)

    # 领域校验器
    question_validator = QuestionValidator()
    score_validator = ScoreValidator()

    # 应用服务装配
    difficulty_service = DifficultyService(ai_client, config_store)
    question_service = QuestionService(
        question_repository,
        question_validator,
        difficulty_service,
        op_repository=question_op_repository,
        config_store=config_store,
        ai_client=ai_client,
    )

    cooldown_policy = CooldownPolicy(scoring_config)
    selection_scorer = SelectionScorer(usage_repository, cooldown_policy, scoring_config)
    weighted_sampler = WeightedSampler(epsilon=scoring_config.epsilon)
    question_generator = QuestionGenerator(
        ai_client, question_validator, question_repository, QUESTION_GENERATOR_MAX_RETRIES
    )
    score_calculator = ScoreCalculator()
    paper_composer = PaperComposer(
        question_repository,
        usage_repository,
        selection_scorer,
        weighted_sampler,
        question_generator,
        score_calculator,
        scoring_config,
    )

    exporters: dict[ExportFormat, BaseExporter] = {
        ExportFormat.TXT: TxtExporter(),
        ExportFormat.PDF: PdfExporter(),
    }
    paper_exporter = PaperExporter(exporters, score_validator)
    task_history_service = TaskHistoryService(task_repository)
    question_history_service = QuestionHistoryService(question_op_repository)

    return Container(
        db=db,
        question_repository=question_repository,
        usage_repository=usage_repository,
        task_repository=task_repository,
        question_op_repository=question_op_repository,
        config_store=config_store,
        ai_client=ai_client,
        image_store=image_store,
        question_validator=question_validator,
        score_validator=score_validator,
        difficulty_service=difficulty_service,
        question_service=question_service,
        cooldown_policy=cooldown_policy,
        selection_scorer=selection_scorer,
        weighted_sampler=weighted_sampler,
        question_generator=question_generator,
        score_calculator=score_calculator,
        paper_composer=paper_composer,
        paper_exporter=paper_exporter,
        task_history_service=task_history_service,
        question_history_service=question_history_service,
    )
