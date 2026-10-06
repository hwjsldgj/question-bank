"""题目服务测试：科目列表、图片导入、CRUD、批量解析、AI 辨识与操作台账。

覆盖用户需求：科目选择式录入、题目图片导入、AI 辨识（模块化输出、按需给出、
一次返回，结果仅供参考）、逐项检查各模块填写情况、组卷按知识点统计、
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
    RecognizeModule,
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
    """测试用 AI 客户端：返回预置 JSON 并记录收到的提示词与期望结构。"""

    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {}
        self.prompts: list[str] = []
        self.schemas: list[dict | None] = []

    def complete(self, prompt: str, response_schema: dict | None = None) -> dict:
        self.prompts.append(prompt)
        self.schemas.append(response_schema)
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
    """注入了假 AI 客户端的题目服务（含图片存储，保证换图 / 删除时能清理文件）。"""
    return QuestionService(
        container.question_repository,
        QuestionValidator(),
        DifficultyService(FakeAIClient(), container.config_store),
        op_repository=container.question_op_repository,
        config_store=container.config_store,
        ai_client=FakeAIClient(),
        image_store=container.image_store,
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
        "科目：数学\n知识点板块：代数、几何\n知识点：函数\n题型：解答题\n题干：求极值。\n"
        "参考答案：令导数为零。\n\n"
        "科目：数学\n知识板块：代数\n知识点：因式分解\n题型：填空\n题干：x^2-1 = ____\n"
        "参考答案：3；-1"
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

    # 知识点板块：未标注时按科目 + 知识点反查；显式标注（含旧术语）优先；
    # 一道题可属于多个板块（用户需求），统一用"、"分隔
    assert drafts[0].section == "力学"
    assert drafts[1].section == "代数、几何"
    assert drafts[2].section == "代数"

    committed = service.batch_commit(drafts)
    assert len(committed) == 3
    assert [question.section for question in committed] == [
        "力学",
        "代数、几何",
        "代数",
    ]
    # 多板块题按其中任一板块都能检索到（用户需求）
    assert [q.id for q in service.search(QuestionFilter(section="几何"))] == [
        committed[1].id
    ]
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
    # 两题题干相同：本用例验证概览与知识点字典，显式跳过自动去重拦截
    service.create_question(fill, allow_duplicate=True)

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
    # 题干相同：本用例验证图片清理，显式跳过自动去重拦截
    plain = service.create_question(_single_question(), allow_duplicate=True)

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
    # 题干相同：本用例验证"人工难度不被覆盖"，显式跳过自动去重拦截
    saved_manual = service.create_question(manual, allow_duplicate=True)

    summary = service.reanalyze_difficulties(service.all_question_ids(), True)
    assert summary == {"total": 2, "updated": 1, "skipped": 1, "failed": 0}
    assert container.question_repository.get(saved_auto.id).difficulty is Difficulty.HARD
    assert container.question_repository.get(saved_manual.id).difficulty is Difficulty.EASY


def test_history_split_import_and_edit(container, service) -> None:
    """历史分类：手工录入 / 批量导入归入导入历史，修改与删除归入编辑历史。"""
    history = container.question_history_service

    saved = service.create_question(_single_question())
    fill = Question(
        id="",
        subject="数学",
        knowledge_points=["因式分解"],
        type=QuestionType.FILL,
        stem="填空",
        answer=["3"],
        difficulty=Difficulty.EASY,
    )
    service.batch_commit([fill])
    service.update_question(saved.id, {"stem": "改后的题干"})

    imports = history.list_import_history()
    edits = history.list_edit_history()
    assert [record.action for record in imports] == [
        QuestionOpAction.IMPORT,
        QuestionOpAction.CREATE,
    ]
    assert [record.action for record in edits] == [QuestionOpAction.UPDATE]

    service.delete_question(saved.id)
    assert [record.action for record in history.list_edit_history()] == [
        QuestionOpAction.DELETE,
        QuestionOpAction.UPDATE,
    ]


def test_save_accepts_string_enum_fields(container, service) -> None:
    """回归：枚举字段以字符串给出时也能保存（曾报 'str' 没有 'value' 属性）。"""
    draft = _single_question()
    draft.type = "single"
    draft.difficulty = "easy"
    draft.difficulty_source = "manual"
    draft.quality_flag = "quality"
    draft.source = "bank"

    saved = service.create_question(draft)
    assert saved.type is QuestionType.SINGLE
    assert saved.difficulty is Difficulty.EASY
    assert saved.difficulty_source is DifficultySource.MANUAL
    stored = container.question_repository.get(saved.id)
    assert stored.quality_flag is QualityFlag.QUALITY
    assert stored.source.value == "bank"

    # 编辑补丁同样接受字符串
    service.update_question(saved.id, {"difficulty": "hard", "quality_flag": "low"})
    updated = container.question_repository.get(saved.id)
    assert updated.difficulty is Difficulty.HARD
    assert updated.quality_flag is QualityFlag.LOW


def test_storage_layer_accepts_string_enum_fields(container) -> None:
    """存储边界兜底：仓储直接写入字符串枚举取值不会抛 AttributeError。"""
    direct = Question(
        id="direct-1",
        subject="物理",
        knowledge_points=["力学"],
        type="fill",
        stem="填空",
        answer=["3"],
        difficulty="medium",
    )
    container.question_repository.save(direct)
    stored = container.question_repository.get("direct-1")
    assert stored.type is QuestionType.FILL
    assert stored.difficulty is Difficulty.MEDIUM


def test_save_rejects_invalid_enum_value(service) -> None:
    """非法枚举取值给出可读校验错误，而不是 AttributeError。"""
    from app.domain.errors import QuestionValidationError

    bad = _single_question()
    bad.type = "judge"
    with pytest.raises(QuestionValidationError, match="题型取值非法"):
        service.create_question(bad)


def test_ai_actions_require_confirmation(container) -> None:
    """所有 AI 调用都需用户确认：未确认时拒绝执行且不发起调用。"""
    from app.domain.errors import AIServiceError

    fake = FakeAIClient({"difficulty": "hard"})
    local = QuestionService(
        container.question_repository,
        QuestionValidator(),
        DifficultyService(fake, container.config_store, container.question_repository),
        op_repository=container.question_op_repository,
        config_store=container.config_store,
        ai_client=fake,
    )

    # 未确认：不调用 AI，难度保持"待确认"
    pending = _single_question()
    pending.difficulty = Difficulty.PENDING
    saved = local.create_question(pending)
    assert saved.difficulty is Difficulty.PENDING
    assert fake.prompts == []

    # 确认后：才调用 AI 分析难度
    confirmed = _single_question()
    confirmed.difficulty = Difficulty.PENDING
    # 题干与上一题相同：本用例验证 AI 难度分析，显式跳过自动去重拦截
    analyzed = local.create_question(
        confirmed, analyze_difficulty=True, allow_duplicate=True
    )
    assert analyzed.difficulty is Difficulty.HARD
    assert fake.prompts

    # 辨识与批量重析未确认 -> 拒绝执行
    with pytest.raises(AIServiceError, match="确认"):
        local.recognize_draft("题干", [])
    with pytest.raises(AIServiceError, match="确认"):
        local.reanalyze_difficulties([analyzed.id])
    # 确认了但一个模块都没勾选 -> 拒绝执行且不发起调用
    calls = len(fake.prompts)
    with pytest.raises(AIServiceError, match="模块"):
        local.recognize_draft("题干", [], True, True, [])
    assert len(fake.prompts) == calls


def test_recognize_is_modular_and_single_call(container) -> None:
    """模块化输出、按需给出、一次返回：只拼装勾选模块，一次调用返回全部所需字段。"""
    fake = FakeAIClient(
        {
            "subject": "数学",
            "knowledge_points": ["集合"],
            "question_type": "多选",
            "difficulty": "难",
            "quality_flag": "优质",
            "answer": ["A", "B"],
            "solution": "解析",
        }
    )
    service = QuestionService(
        container.question_repository,
        QuestionValidator(),
        DifficultyService(fake, container.config_store),
        config_store=container.config_store,
        ai_client=fake,
    )

    result = service.recognize_draft(
        "题干",
        [Option("A", "1"), Option("B", "2")],
        confirmed=True,
        modules=[RecognizeModule.KNOWLEDGE_POINTS, RecognizeModule.ANSWER],
    )
    # 只返回被请求的模块
    assert set(result) == {"knowledge_points", "answer"}
    assert result["knowledge_points"] == ["集合"]
    assert result["answer"] == ["A", "B"]
    # 一次调用
    assert len(fake.prompts) == 1
    # 提示词只含被勾选模块的输出要求
    prompt = fake.prompts[0]
    assert "knowledge_points：" in prompt and "answer：" in prompt
    assert "subject：" not in prompt
    assert "quality_flag：" not in prompt
    assert "difficulty：" not in prompt
    # 期望结构也只含被勾选模块
    schema = fake.schemas[0]
    assert set(schema["properties"]) == {"knowledge_points", "answer"}

    # 模块可以是字符串取值，重复项自动去重，非法值忽略
    fake.prompts.clear()
    fake.schemas.clear()
    result = service.recognize_draft(
        "题干",
        [],
        confirmed=True,
        modules=["answer", RecognizeModule.ANSWER, "不存在的模块"],
    )
    assert set(result) == {"answer"}
    assert len(fake.prompts) == 1


def test_module_states_and_apply_recognition() -> None:
    """逐项检查模块填写状态，并把 AI 结果回填到题目草稿。"""
    draft = Question(
        id="",
        subject="",
        knowledge_points=[],
        type=QuestionType.SINGLE,
        stem="题干",
        options=[Option("A", "1"), Option("B", "2")],
        answer=[],
    )
    states = dict(QuestionService.module_states(draft))
    assert states[RecognizeModule.SUBJECT] is False
    assert states[RecognizeModule.KNOWLEDGE_POINTS] is False
    assert states[RecognizeModule.QUESTION_TYPE] is True  # 题型总有取值
    assert states[RecognizeModule.QUALITY_FLAG] is True  # 质量标记默认"普通"
    assert states[RecognizeModule.DIFFICULTY] is False
    assert states[RecognizeModule.ANSWER] is False
    assert states[RecognizeModule.SOLUTION] is False

    # 必填模块：科目 / 知识点 / 答案
    assert QuestionService.required_missing_modules(draft) == [
        RecognizeModule.SUBJECT,
        RecognizeModule.KNOWLEDGE_POINTS,
        RecognizeModule.ANSWER,
    ]
    assert RecognizeModule.DIFFICULTY in QuestionService.missing_modules(draft)

    QuestionService.apply_recognition(
        draft,
        {
            "subject": "数学",
            "knowledge_points": ["集合"],
            "difficulty": Difficulty.HARD,
            "answer": ["a"],
            "solution": "解析内容",
        },
    )
    assert draft.subject == "数学"
    assert draft.knowledge_points == ["集合"]
    assert draft.answer == ["A"]  # 选择题答案统一大写
    assert draft.difficulty is Difficulty.HARD
    assert draft.difficulty_source is DifficultySource.AI
    assert draft.solution == "解析内容"
    assert QuestionService.required_missing_modules(draft) == []

    # 不允许解析时不写入解析；空结果不覆盖已有内容
    untouched = Question(
        id="",
        subject="物理",
        knowledge_points=["力学"],
        type=QuestionType.SOLUTION,
        stem="题干",
        answer=["参考"],
        solution="原有解析",
    )
    QuestionService.apply_recognition(
        untouched, {"solution": "AI 解析"}, include_solution=False
    )
    assert untouched.solution == "原有解析"
    QuestionService.apply_recognition(untouched, {"subject": "", "knowledge_points": []})
    assert untouched.subject == "物理"
    assert untouched.knowledge_points == ["力学"]


def test_count_available_with_knowledge_points(container, service) -> None:
    """组卷命中量支持指定知识点（用户需求：组卷环节可指定知识点）。"""
    service.create_question(_single_question())  # 知识点：一元二次方程
    other = _single_question()
    other.knowledge_points = ["因式分解"]
    # 后两题与第一题题干相同：本用例验证按知识点统计，显式跳过自动去重拦截
    service.create_question(other, allow_duplicate=True)
    both = _single_question()
    both.knowledge_points = ["一元二次方程", "因式分解"]
    service.create_question(both, allow_duplicate=True)

    assert service.count_available("数学", Difficulty.MEDIUM, QuestionType.SINGLE) == 3
    assert (
        service.count_available(
            "数学", Difficulty.MEDIUM, QuestionType.SINGLE, ["一元二次方程"]
        )
        == 2
    )
    # 多个知识点按"命中任一"统计
    assert (
        service.count_available(
            "数学", Difficulty.MEDIUM, QuestionType.SINGLE, ["因式分解"]
        )
        == 2
    )
    # 空列表等同不限
    assert (
        service.count_available("数学", Difficulty.MEDIUM, QuestionType.SINGLE, [])
        == 3
    )
    # 不存在的知识点使命中量为 0
    assert (
        service.count_available(
            "数学", Difficulty.MEDIUM, QuestionType.SINGLE, ["不存在的知识点"]
        )
        == 0
    )


def test_ai_supplement_requires_confirmation(container) -> None:
    """AI 补题未确认时拒绝执行（用户需求：AI 使用需手动确认）。"""
    from app.domain.errors import AIServiceError

    with pytest.raises(AIServiceError, match="确认"):
        container.question_generator.generate_questions(
            "数学", ["集合"], QuestionType.SINGLE, Difficulty.EASY, 1
        )


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
    result = service.recognize_draft("题干", [], include_solution=False, confirmed=True)
    assert result["solution"] == ""
    assert "不要输出解题解析" in fake.prompts[0]
    # 不输出解析时，提示词与期望结构都不含解析模块
    assert "solution：" not in fake.prompts[0]
    assert "solution" not in fake.schemas[0]["properties"]

    with_solution = service.recognize_draft(
        "题干", [], include_solution=True, confirmed=True
    )
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
            supplement_prompt="",
        )
    )

    result = service.recognize_draft("题干内容", [Option("A", "1")], confirmed=True)
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
        service.recognize_draft("题干", [], confirmed=True)


def _service_with(container, fake) -> QuestionService:
    """构造注入了指定假 AI 客户端的题目服务。"""
    return QuestionService(
        container.question_repository,
        QuestionValidator(),
        DifficultyService(fake, container.config_store),
        op_repository=container.question_op_repository,
        config_store=container.config_store,
        ai_client=fake,
    )


def test_recognition_reports_missing_ai_fields(container) -> None:
    """AI 返回内容缺字段时给出可读问题清单，且不把缺项静默套成默认值（用户需求）。"""
    fake = FakeAIClient({})
    service = _service_with(container, fake)

    report = service.recognize_draft_report("题干", [], confirmed=True)
    assert report.ok is False
    joined = "；".join(report.issues)
    assert "未返回科目" in joined
    assert "未返回知识点" in joined
    assert "未返回" in joined and "题型" in joined
    assert "未返回难度" in joined
    # 未返回的字段不写入结果（不会静默变成 SINGLE / PENDING / NORMAL）
    assert "difficulty" not in report.fields
    assert "question_type" not in report.fields
    assert "quality_flag" not in report.fields
    assert "subject" not in report.fields
    # recognize_draft 仍只返回字段字典（向后兼容）
    assert service.recognize_draft("题干", [], confirmed=True) == report.fields


def test_recognition_flags_unrecognized_ai_values(container) -> None:
    """AI 返回了无法识别的取值时同样报问题，可识别字段照常回填（用户需求）。"""
    fake = FakeAIClient(
        {
            "subject": "天文学",
            "knowledge_points": ["集合"],
            "question_type": "判断题",
            "difficulty": "一般",
            "quality_flag": "略低",
            "answer": ["A"],
            "solution": "解析",
        }
    )
    service = _service_with(container, fake)
    report = service.recognize_draft_report("题干", [], confirmed=True)

    assert report.fields["knowledge_points"] == ["集合"]
    assert report.fields["answer"] == ["A"]
    assert report.fields["solution"] == "解析"
    assert "difficulty" not in report.fields
    assert "quality_flag" not in report.fields
    issues = "；".join(report.issues)
    assert "题型无法识别" in issues
    assert "难度无法识别" in issues
    assert "质量标记无法识别" in issues
    assert "不在科目列表" in issues

    # 正常返回时没有问题
    good = FakeAIClient(
        {
            "subject": "数学",
            "knowledge_points": ["集合"],
            "question_type": "single",
            "difficulty": "easy",
            "quality_flag": "normal",
            "answer": ["A"],
            "solution": "",
        }
    )
    ok_report = _service_with(container, good).recognize_draft_report(
        "题干", [], confirmed=True
    )
    assert ok_report.ok is True and ok_report.issues == []


def test_recognition_prompt_keeps_one_requirement_per_field(container) -> None:
    """自定义总述已写明某字段时不再追加该模块要求（用户需求：提示词里难度不重复）。"""
    fake = FakeAIClient({"difficulty": "hard"})
    service = _service_with(container, fake)
    container.config_store.save_prompt_config(
        PromptConfig(
            recognize_prompt=(
                "自定义总述\n"
                "subject：科目\n"
                "knowledge_points：知识点\n"
                "difficulty：easy、medium 或 hard\n"
                "题干：{stem}\n"
            ),
            supplement_prompt="",
        )
    )
    service.recognize_draft("题干", [], confirmed=True)
    prompt = fake.prompts[0]
    assert prompt.count("difficulty") == 1
    assert prompt.count("subject：") == 1
    assert prompt.count("knowledge_points") == 1
    # 总述里没提到的模块仍会补上输出要求
    assert "quality_flag" in prompt
    assert "answer：" in prompt


def test_difficulty_analysis_reuses_module_prompt(container) -> None:
    """难度只维护一处提示词：难度分析复用「难度」模块片段，并接受纯文本返回。"""
    fake = FakeAIClient({"text": "medium"})
    container.config_store.save_prompt_config(
        PromptConfig(
            module_prompts={"difficulty": "difficulty：只给 easy/medium/hard"},
            supplement_prompt="",
        )
    )
    service = DifficultyService(fake, container.config_store)
    assert service.analyze(_single_question()) is Difficulty.MEDIUM
    prompt = fake.prompts[0]
    assert "只给 easy/medium/hard" in prompt
    assert "输出要求" in prompt
    assert "题干：" in prompt

    # 无法识别时抛出可读异常（界面据此弹窗），而不是静默降级
    from app.domain.errors import AIServiceError

    with pytest.raises(AIServiceError, match="难度"):
        DifficultyService(FakeAIClient({"text": "说不清"})).analyze(_single_question())
