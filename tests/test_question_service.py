"""题目服务测试：科目列表、图片导入、CRUD、批量解析、AI 辨识与操作台账。

覆盖用户需求：科目选择式录入、题目图片导入、AI 辨识（结果仅供参考）、
导入历史与编辑历史；同时覆盖需求 R1 / R2 / R6 / R13 的关键路径。
"""

from pathlib import Path

import pytest

from app.application.difficulty_service import DifficultyService
from app.application.question_service import QuestionService
from app.container import build_container
from app.domain.entities.configs import PromptConfig
from app.domain.entities.question import Option, Question, QuestionFilter
from app.domain.enums import (
    Difficulty,
    DifficultySource,
    QuestionOpAction,
    QualityFlag,
    QuestionType,
)
from app.domain.validators.question_validator import QuestionValidator
from app.infrastructure.database.schema import ensure_schema
from app.interfaces.ai_client import AIClient

#: 最小合法 PNG（1x1 像素），用于图片导入测试
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000154a24f5f0000000049454e44ae426082"
)


class FakeAIClient(AIClient):
    """测试用 AI 客户端：返回预置 JSON 并记录收到的提示词。"""

    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {}
        self.prompts: list[str] = []

    def complete(self, prompt: str, response_schema: dict | None = None) -> dict:
        self.prompts.append(prompt)
        return dict(self.payload)

    def is_configured(self) -> bool:
        return True


@pytest.fixture()
def container(tmp_path):
    """临时库上的完整对象图（含建表）。"""
    graph = build_container(str(tmp_path / "service.db"))
    ensure_schema(graph.db.connect())
    yield graph
    graph.db.close()


@pytest.fixture()
def service(container) -> QuestionService:
    """注入了假 AI 客户端的题目服务。"""
    return QuestionService(
        container.question_repository,
        QuestionValidator(),
        DifficultyService(FakeAIClient(), container.config_store),
        op_repository=container.question_op_repository,
        config_store=container.config_store,
        ai_client=FakeAIClient(),
    )


def _single_question(subject: str = "数学", image: str | None = None) -> Question:
    """构造一道合法单选题。"""
    return Question(
        id="",
        subject=subject,
        knowledge_points=["一元二次方程"],
        type=QuestionType.SINGLE,
        stem="x^2-1=0 的解是？",
        options=[Option("A", "1"), Option("B", "2")],
        answer=["A"],
        difficulty=Difficulty.MEDIUM,
        image_path=image,
    )


def test_subjects_default_and_override(container, service) -> None:
    """科目列表默认提供，保存后以配置为准（科目改为选择式录入）。"""
    assert "数学" in service.list_subjects()
    container.config_store.save_subjects(["数学", "物理", "数学"])
    assert service.list_subjects() == ["数学", "物理"]


def test_image_import_copies_and_resolves(container, tmp_path) -> None:
    """图片导入：复制到 images/ 目录并返回可解析的相对路径。"""
    source = Path(tmp_path) / "stem.png"
    source.write_bytes(PNG_BYTES)

    relative = container.image_store.save(source)
    assert relative.startswith("images/")
    resolved = container.image_store.resolve(relative)
    assert resolved is not None and resolved.is_file()
    assert container.image_store.is_supported(source)
    assert not container.image_store.is_supported(Path("bad.txt"))


def test_image_rejected_for_missing_file(container) -> None:
    """图片不存在时抛出可读的导入错误。"""
    from app.domain.errors import ImageImportError

    with pytest.raises(ImageImportError):
        container.image_store.save("not-exists.png")


def test_create_search_update_delete_with_history(container, service, tmp_path) -> None:
    """题目增删改查 + 图片字段 + 编辑 / 导入历史台账。"""
    source = Path(tmp_path) / "stem.png"
    source.write_bytes(PNG_BYTES)
    relative = container.image_store.save(source)

    saved = service.create_question(_single_question(image=relative))
    assert saved.id
    assert saved.difficulty is Difficulty.MEDIUM  # 人工填写的难度不被覆盖

    found = service.search(QuestionFilter(subject="数学"))
    assert [q.id for q in found] == [saved.id]
    assert found[0].image_path == relative
    assert service.count_available("数学", Difficulty.MEDIUM, QuestionType.SINGLE) == 1

    service.update_question(saved.id, {"stem": "改后的题干"})
    service.set_quality_flag(saved.id, QualityFlag.LOW)
    edits = service.list_operations([QuestionOpAction.UPDATE])
    assert len(edits) == 2
    assert any("质量标记" in record.detail for record in edits)

    service.delete_question(saved.id)
    assert service.search(QuestionFilter()) == []
    assert service.list_operations([QuestionOpAction.DELETE])


def test_batch_parse_and_commit_records_import(service) -> None:
    """批量粘贴解析（含未标注"选项："的写法）与批量入库台账。"""
    drafts = service.batch_parse(
        "科目：物理\n知识点：牛顿定律\n题型：单选\n题干：惯性由什么决定？\n"
        "A. 质量\nB. 速度\n答案：A\n\n"
        "科目：数学\n知识点：函数\n题型：解答题\n题干：求极值。\n参考答案：令导数为零。\n\n"
        "科目：数学\n知识点：因式分解\n题型：填空\n题干：x^2-1 = ____\n参考答案：3；-1"
    )
    assert len(drafts) == 3
    assert drafts[0].type is QuestionType.SINGLE
    assert [option.text for option in drafts[0].options] == ["质量", "速度"]
    assert drafts[0].answer == ["A"]
    assert drafts[1].type is QuestionType.SOLUTION
    assert drafts[1].answer == ["令导数为零。"]
    assert drafts[2].type is QuestionType.FILL
    assert drafts[2].options == []
    assert drafts[2].answer == ["3；-1"]

    committed = service.batch_commit(drafts)
    assert len(committed) == 3
    imports = service.list_operations([QuestionOpAction.IMPORT])
    assert len(imports) == 3
    assert imports[0].batch_id and imports[0].batch_id == imports[1].batch_id


def test_fill_question_crud(service) -> None:
    """填空题可入库、可检索（用户新增题型）。"""
    fill = Question(
        id="",
        subject="数学",
        knowledge_points=["因式分解"],
        type=QuestionType.FILL,
        stem="x^2-1 = ____",
        answer=["3", "-1"],
        difficulty=Difficulty.EASY,
    )
    saved = service.create_question(fill)
    found = service.search(QuestionFilter(question_type=QuestionType.FILL))
    assert [q.id for q in found] == [saved.id]
    assert found[0].answer == ["3", "-1"]
    assert service.count_available("数学", Difficulty.EASY, QuestionType.FILL) == 1


def test_statistics_and_knowledge_points(service) -> None:
    """题库概览与知识点字典（录入 / 检索自动补全的数据来源）。"""
    service.create_question(_single_question())
    fill = _single_question()
    fill.knowledge_points = ["因式分解"]
    service.create_question(fill)

    stats = service.statistics()
    assert stats["total"] == 2
    assert stats["single"] == 2
    assert stats["fill"] == 0

    points = service.list_knowledge_points()
    assert "一元二次方程" in points and "因式分解" in points
    assert service.list_knowledge_points("数学") == points
    assert service.list_knowledge_points("不存在的科目") == []


def test_batch_operations_and_image_cleanup(container, service, tmp_path) -> None:
    """批量质量标记、批量删除，以及删除后本地图片的清理。"""
    source = Path(tmp_path) / "stem.png"
    source.write_bytes(PNG_BYTES)
    relative = container.image_store.save(source)

    with_image = service.create_question(_single_question(image=relative))
    plain = service.create_question(_single_question())

    changed = service.set_quality_flag_many(
        [with_image.id, plain.id, "missing-id"], QualityFlag.QUALITY
    )
    assert changed == 2

    assert service.delete_questions([with_image.id]) == 1
    # 无其他题目引用该图片 -> 本地文件被清理
    assert container.image_store.resolve(relative) is None
    remaining = service.search(QuestionFilter())
    assert [question.id for question in remaining] == [plain.id]


def test_reanalyze_difficulties_skips_manual(container) -> None:
    """批量重析难度：AI 来源题目被更新，人工难度保持不变（需求 R5 第 4 条）。"""

    class HardAIClient(FakeAIClient):
        def complete(self, prompt, response_schema=None):
            self.prompts.append(prompt)
            return {"difficulty": "hard"}

    fake = HardAIClient()
    service = QuestionService(
        container.question_repository,
        QuestionValidator(),
        DifficultyService(fake, container.config_store, container.question_repository),
        op_repository=container.question_op_repository,
        config_store=container.config_store,
        ai_client=fake,
    )

    auto = _single_question()
    auto.difficulty = Difficulty.PENDING
    saved_auto = service.create_question(auto)

    manual = _single_question()
    manual.difficulty = Difficulty.EASY
    manual.difficulty_source = DifficultySource.MANUAL
    saved_manual = service.create_question(manual)

    summary = service.reanalyze_difficulties(service.all_question_ids())
    assert summary == {"total": 2, "updated": 1, "skipped": 1, "failed": 0}
    assert container.question_repository.get(saved_auto.id).difficulty is Difficulty.HARD
    assert container.question_repository.get(saved_manual.id).difficulty is Difficulty.EASY


def test_recognize_can_skip_solution(container) -> None:
    """AI 辨识可要求不输出解析（用户需求）。"""
    fake = FakeAIClient(
        {
            "subject": "数学",
            "knowledge_points": ["集合"],
            "question_type": "单选",
            "difficulty": "易",
            "quality_flag": "普通",
            "answer": ["A"],
            "solution": "AI 生成的解析",
        }
    )
    service = QuestionService(
        container.question_repository,
        QuestionValidator(),
        DifficultyService(fake, container.config_store),
        config_store=container.config_store,
        ai_client=fake,
    )
    result = service.recognize_draft("题干", [], include_solution=False)
    assert result["solution"] == ""
    assert "不要输出解题解析" in fake.prompts[0]

    with_solution = service.recognize_draft("题干", [], include_solution=True)
    assert with_solution["solution"] == "AI 生成的解析"


def test_batch_commit_reports_invalid_draft(service) -> None:
    """批量入库遇到非法题目时聚合报错（需求 R2 第 4 条）。"""
    from app.domain.errors import QuestionValidationError

    bad = _single_question()
    bad.answer = []
    with pytest.raises(QuestionValidationError, match="第 1 题"):
        service.batch_commit([bad])


def test_recognize_draft_normalizes_and_uses_prompt(container) -> None:
    """AI 辨识：结果归一化为题型 / 难度 / 质量枚举，提示词来自可编辑配置。"""
    fake = FakeAIClient(
        {
            "subject": "数学",
            "knowledge_points": "一元二次方程，因式分解",
            "question_type": "单选题",
            "difficulty": "难",
            "quality_flag": "优质",
            "answer": "A",
            "solution": "两边开方",
        }
    )
    service = QuestionService(
        container.question_repository,
        QuestionValidator(),
        DifficultyService(fake, container.config_store),
        op_repository=container.question_op_repository,
        config_store=container.config_store,
        ai_client=fake,
    )
    container.config_store.save_prompt_config(
        PromptConfig(
            recognize_prompt="自定义辨识 {subjects} :: {stem}",
            difficulty_prompt="",
            supplement_prompt="",
        )
    )

    result = service.recognize_draft("题干内容", [Option("A", "1")])
    assert service.ai_configured() is True
    assert result["subject"] == "数学"
    assert result["knowledge_points"] == ["一元二次方程", "因式分解"]
    assert result["question_type"] is QuestionType.SINGLE
    assert result["difficulty"] is Difficulty.HARD
    assert result["quality_flag"] is QualityFlag.QUALITY
    assert result["answer"] == ["A"]
    assert result["solution"] == "两边开方"
    assert fake.prompts[0].startswith("自定义辨识")


def test_recognize_without_ai_raises(container) -> None:
    """未接入 / 未配置 AI 时不进行辨识，抛出可读异常。"""
    from app.config.settings import DEFAULT_AI_CONFIG
    from app.domain.errors import AIConfigMissingError
    from app.infrastructure.ai.ai_client import OpenAICompatibleAIClient

    service = QuestionService(
        container.question_repository,
        QuestionValidator(),
        DifficultyService(OpenAICompatibleAIClient(DEFAULT_AI_CONFIG)),
        config_store=container.config_store,
        ai_client=OpenAICompatibleAIClient(DEFAULT_AI_CONFIG),
    )
    assert service.ai_configured() is False
    with pytest.raises(AIConfigMissingError):
        service.recognize_draft("题干", [])
