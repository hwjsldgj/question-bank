"""冒烟测试：验证框架各层模块可正常导入、核心类型与装配关系存在。

对应设计文档 "Test Strategy" 的最小保障：框架阶段保证分层结构
完整可加载，业务逻辑实现后由各专项测试文件接管。

依赖：app 各层模块
被使用：python -m pytest tests/test_smoke.py
"""

import app.container as container_module
import app.domain.entities.question as question_module
import app.domain.enums as enums_module
import app.domain.validators.question_validator as validator_module
import app.infrastructure.database.schema as schema_module
from app.application.paper_composer import PaperComposer
from app.application.selection_scorer import SelectionScorer
from app.application.weighted_sampler import WeightedSampler
from app.container import Container, build_container
from app.domain.enums import Difficulty, ExportFormat, QuestionType
from app.domain.validators.question_validator import QuestionValidator
from app.infrastructure.ai.ai_client import OpenAICompatibleAIClient
from app.infrastructure.database.connection import DatabaseConnection
from app.infrastructure.repositories.question_repository import SQLiteQuestionRepository
from app.interfaces.ai_client import AIClient
from app.interfaces.exporters import BaseExporter
from app.interfaces.repositories import (
    ConfigStore,
    QuestionRepository,
    TaskRepository,
    UsageRepository,
)


def test_domain_enums_exist() -> None:
    """核心枚举取值与需求文档一致。"""
    assert QuestionType.SINGLE.value == "single"
    assert QuestionType.SOLUTION.value == "solution"
    assert Difficulty.PENDING.value == "pending"
    assert ExportFormat.TXT.value == "txt"
    assert ExportFormat.PDF.value == "pdf"


def test_core_classes_exist() -> None:
    """各层核心类均可导入。"""
    assert callable(QuestionValidator)
    assert callable(SelectionScorer)
    assert callable(WeightedSampler)
    assert callable(PaperComposer)
    assert callable(DatabaseConnection)
    assert callable(SQLiteQuestionRepository)
    assert callable(OpenAICompatibleAIClient)


def test_interfaces_are_abstract() -> None:
    """抽象接口不可直接实例化（端口层契约）。"""
    for abstract_cls in (AIClient, BaseExporter, QuestionRepository, UsageRepository, TaskRepository, ConfigStore):
        try:
            abstract_cls()  # type: ignore[call-abstract]
        except TypeError:
            continue
        raise AssertionError(f"{abstract_cls.__name__} 应为抽象类，不可实例化")


def test_schema_covers_all_tables() -> None:
    """建表语句覆盖设计文档声明的全部数据表。"""
    joined = "\n".join(schema_module.SCHEMA_STATEMENTS)
    for table in (
        "questions",
        "knowledge_points",
        "question_usage",
        "generation_tasks",
        "task_exports",
        "settings",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in joined


def test_build_container_wires_layers() -> None:
    """组合根能把基础设施实现装配进应用服务（临时库，落盘即删）。"""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        c = build_container(str(Path(tmp) / "smoke.db"))
        assert isinstance(c, Container)
        # 接口契约：仓储实例实现对应抽象接口
        assert isinstance(c.question_repository, QuestionRepository)
        assert isinstance(c.usage_repository, UsageRepository)
        assert isinstance(c.task_repository, TaskRepository)
        assert isinstance(c.config_store, ConfigStore)
        assert isinstance(c.ai_client, AIClient)
        # 装配关系：评分器持有冷却策略引用（依赖注入生效）
        assert c.selection_scorer._cooldown_policy is c.cooldown_policy
        c.db.close()


def test_modules_importable() -> None:
    """全部关键模块可导入（框架完整性）。"""
    for module in (
        container_module,
        enums_module,
        question_module,
        validator_module,
    ):
        assert module is not None
