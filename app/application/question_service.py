"""题目服务：题库 CRUD、批量粘贴解析、AI 辨识与可用量统计。

职责对应需求：

- R1：题目手工录入与维护（保存 / 编辑 / 删除）
- R2：批量粘贴录入（解析预览 -> 确认提交）
- R5：难度、标签与质量人工修正
- R6：题库检索与可用量统计
- 用户需求：AI 辨识科目 / 知识点 / 题型 / 难度 / 质量 / 答案 / 解析（结果仅供参考），
  各字段为独立模块：按需勾选、只拼装所需提示词、一次调用返回（模块化输出）
- 用户需求：保存 / 导入前逐项检查各模块填写情况，并可让 AI 填充缺失项（题干除外）
- 用户需求：题库操作台账（导入历史 / 编辑历史）

依赖（构造注入，全部为抽象）：
- app.interfaces.repositories.QuestionRepository
- app.interfaces.repositories.QuestionOpRepository（可选，操作台账）
- app.interfaces.repositories.ConfigStore（可选，科目列表、知识板块与提示词）
- app.interfaces.ai_client.AIClient（可选，AI 辨识）
- app.domain.validators.question_validator.QuestionValidator
- app.application.difficulty_service.DifficultyService

被使用：app.presentation.views.question_bank_view、app.container
"""

import re
import uuid
from dataclasses import dataclass, field

from app.application.difficulty_service import DifficultyService
from app.application.prompt_utils import load_prompt_config, render
from app.config.settings import (
    DEFAULT_KNOWLEDGE_SECTIONS,
    DEFAULT_MODULE_PROMPTS,
    DEFAULT_PROMPT_CONFIG,
    DEFAULT_SUBJECTS,
)
from app.domain.entities.knowledge_section import KnowledgeSection
from app.domain.entities.question import Option, Question, QuestionFilter
from app.domain.entities.question_op import QuestionOpRecord
from app.domain.enums import (
    Difficulty,
    DifficultySource,
    QualityFlag,
    QuestionOpAction,
    QuestionSource,
    QuestionType,
    RecognizeModule,
)
from app.domain.errors import AIServiceError, QuestionValidationError
from app.domain.validators.question_validator import QuestionValidator
from app.interfaces.ai_client import AIClient
from app.interfaces.repositories import (
    ConfigStore,
    QuestionOpRepository,
    QuestionRepository,
)

#: 题块分隔：空行或 "---" / "===" 行
_BLOCK_SPLIT = re.compile(r"\n\s*\n|\n\s*[-=]{3,}\s*\n")

#: 字段标签行（如 "科目：数学"）
_LABEL_LINE = re.compile(r"^\s*([\u4e00-\u9fa5A-Za-z]{1,6})\s*[：:]\s*(.*)$")

#: 选项行（如 "A. 内容" / "A、内容" / "A) 内容"）
_OPTION_LINE = re.compile(r"^\s*([A-Za-z])\s*[\.、\)．]\s*(.*)$")

#: AI 辨识返回字段期望结构（提示模型输出 JSON 对象）
RECOGNIZE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "knowledge_points": {"type": "object"},
        "question_type": {"type": "string"},
        "difficulty": {"type": "string"},
        "quality_flag": {"type": "string"},
        "answer": {"type": "array", "items": {"type": "string"}},
        "solution": {"type": "string"},
        "stem": {"type": "string"},
        "options": {"type": "array", "items": {"type": "object"}},
    },
}

#: 模块 -> 中文名（问题提示文案统一口径）
_MODULE_NAMES: dict[RecognizeModule, str] = {
    RecognizeModule.SUBJECT: "科目",
    RecognizeModule.KNOWLEDGE_POINTS: "知识点",
    RecognizeModule.QUESTION_TYPE: "题型",
    RecognizeModule.DIFFICULTY: "难度",
    RecognizeModule.QUALITY_FLAG: "质量标记",
    RecognizeModule.ANSWER: "答案",
    RecognizeModule.SOLUTION: "解析",
}

#: 全部 AI 辨识模块（界面默认全选；顺序即表单与提示词的呈现顺序）
RECOGNIZE_MODULES: tuple[RecognizeModule, ...] = tuple(RecognizeModule)

#: 模块 -> 期望的 JSON 结构片段：只把被勾选模块写入一次调用的期望结构
MODULE_SCHEMAS: dict[RecognizeModule, dict] = {
    RecognizeModule.SUBJECT: {"type": "string"},
    RecognizeModule.KNOWLEDGE_POINTS: {"type": "object"},
    RecognizeModule.QUESTION_TYPE: {"type": "string"},
    RecognizeModule.DIFFICULTY: {"type": "string"},
    RecognizeModule.QUALITY_FLAG: {"type": "string"},
    RecognizeModule.ANSWER: {"type": "array", "items": {"type": "string"}},
    RecognizeModule.SOLUTION: {"type": "string"},
    RecognizeModule.STEM: {"type": "string"},
    RecognizeModule.OPTIONS: {"type": "array", "items": {"type": "object"}},
}

# 必填模块（科目 / 知识点 / 答案）的规范定义见 QuestionService.REQUIRED_MODULES；
# 此处为兼容旧导入名的别名，类定义结束后赋值。
REQUIRED_MODULES: tuple[RecognizeModule, ...]


def recognize_schema(modules: list[RecognizeModule] | tuple[RecognizeModule, ...]) -> dict:
    """按被勾选的模块生成期望结构（只包含所需字段，一次调用返回全部所需字段）。"""
    return {
        "type": "object",
        "properties": {module.value: MODULE_SCHEMAS[module] for module in modules},
    }


_FIELD_ALIASES: dict[str, str] = {
    "科目": "subject",
    "学科": "subject",
    "subject": "subject",
    "知识点": "knowledge",
    "考点": "knowledge",
    "knowledge": "knowledge",
    "题型": "type",
    "类型": "type",
    "type": "type",
    "题干": "stem",
    "题目": "stem",
    "stem": "stem",
    "选项": "options",
    "options": "options",
    "答案": "answer",
    "参考答案": "answer",
    "answer": "answer",
    "解析": "solution",
    "solution": "solution",
    "难度": "difficulty",
}

_TYPE_WORDS: dict[str, QuestionType] = {
    "单选": QuestionType.SINGLE,
    "单项选择": QuestionType.SINGLE,
    "single": QuestionType.SINGLE,
    "多选": QuestionType.MULTIPLE,
    "多项选择": QuestionType.MULTIPLE,
    "multiple": QuestionType.MULTIPLE,
    "填空": QuestionType.FILL,
    "fill": QuestionType.FILL,
    "解答": QuestionType.SOLUTION,
    "简答": QuestionType.SOLUTION,
    "解答题": QuestionType.SOLUTION,
    "solution": QuestionType.SOLUTION,
}

_DIFFICULTY_WORDS: dict[str, Difficulty] = {
    "易": Difficulty.EASY,
    "简单": Difficulty.EASY,
    "easy": Difficulty.EASY,
    "中": Difficulty.MEDIUM,
    "中等": Difficulty.MEDIUM,
    "medium": Difficulty.MEDIUM,
    "难": Difficulty.HARD,
    "困难": Difficulty.HARD,
    "hard": Difficulty.HARD,
}

_QUALITY_WORDS: dict[str, QualityFlag] = {
    "优质": QualityFlag.QUALITY,
    "quality": QualityFlag.QUALITY,
    "低质": QualityFlag.LOW,
    "low": QualityFlag.LOW,
    "普通": QualityFlag.NORMAL,
    "normal": QualityFlag.NORMAL,
}


@dataclass
class RecognitionReport:
    """AI 辨识结果 + 返回内容问题清单（用户需求：返回信息有问题时弹窗提示）。

    :param fields: 归一化后的字段字典，只含被请求模块对应的键，且只包含
        "确实识别出来"的字段（无法识别的字段不会写入，避免静默套用默认值）
    :param issues: 可读问题列表，如 "AI 未返回知识点（knowledge_points）"、
        "AI 返回的难度无法识别：'一般'"；为空表示返回内容正常
    """

    fields: dict = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """返回内容是否没有发现问题。"""
        return not self.issues


class QuestionService:
    """题目服务：题库维护的统一入口。"""

    #: 保存前必须齐全的模块（题干与选项另由界面校验，AI 不负责生成）
    REQUIRED_MODULES: tuple[RecognizeModule, ...] = (
        RecognizeModule.SUBJECT,
        RecognizeModule.KNOWLEDGE_POINTS,
        RecognizeModule.ANSWER,
    )

    def __init__(
        self,
        repository: QuestionRepository,
        validator: QuestionValidator,
        difficulty_service: DifficultyService,
        op_repository: QuestionOpRepository | None = None,
        config_store: ConfigStore | None = None,
        ai_client: AIClient | None = None,
        image_store=None,
    ) -> None:
        """注入仓储、校验器、难度服务，以及可选的台账 / 配置 / AI 客户端 / 图片存储。"""
        self._repository = repository
        self._validator = validator
        self._difficulty_service = difficulty_service
        self._op_repository = op_repository
        self._config_store = config_store
        self._ai_client = ai_client
        self._image_store = image_store

    # ------------------------------------------------------------------ CRUD

    def create_question(
        self, draft: Question, analyze_difficulty: bool = False
    ) -> Question:
        """新增题目：校验通过后落库（需求 R1）。

        AI 难度分析必须经用户确认：仅当 ``analyze_difficulty=True`` 时才会调用
        AI（用户需求：所有使用 AI 的内容都需手动确认）。

        :param draft: 待保存题目草稿
        :param analyze_difficulty: 用户是否已确认调用 AI 分析难度
        """
        self._normalize_enums(draft)
        self._validator.validate(draft)
        saved = self._repository.save(draft)
        self._analyze_if_automatic(saved, analyze_difficulty)
        self._record(
            QuestionOpAction.CREATE,
            saved,
            detail=f"录入题目（{saved.type.value}）",
        )
        return saved

    def update_question(
        self, question_id: str, patch: dict, analyze_difficulty: bool = False
    ) -> Question:
        """编辑题目：合并字段、校验后更新，保留 id 与使用记录（需求 R1 第 3 条）。

        :param analyze_difficulty: 用户是否已确认调用 AI 分析难度
        """
        current = self._repository.get(question_id)
        if current is None:
            raise QuestionValidationError(f"题目不存在：{question_id}")
        old = Question(**{**current.__dict__})
        for key, value in patch.items():
            if hasattr(current, key):
                setattr(current, key, value)
        current.id = question_id
        self._normalize_enums(current)
        self._validator.validate(current)
        updated = self._repository.update(current)
        self._analyze_if_automatic(updated, analyze_difficulty)
        # 换图后清理旧图片（无其他题目引用时）
        if old.image_path and old.image_path != updated.image_path:
            self._cleanup_image(old.image_path)
        self._record(
            QuestionOpAction.UPDATE,
            updated,
            detail=self._diff_detail(old, updated),
        )
        return updated

    def delete_question(self, question_id: str) -> None:
        """删除题目，使其不再参与后续组卷（需求 R1 第 4 条）。"""
        current = self._repository.get(question_id)
        self._repository.delete(question_id)
        if current is not None:
            self._cleanup_image(current.image_path)
            self._record(QuestionOpAction.DELETE, current, detail="删除题目")

    def delete_questions(self, question_ids: list[str]) -> int:
        """批量删除题目（用户需求：题库批量维护），返回实际删除数量。"""
        deleted = 0
        for question_id in question_ids:
            current = self._repository.get(question_id)
            if current is None:
                continue
            self._repository.delete(question_id)
            self._cleanup_image(current.image_path)
            self._record(QuestionOpAction.DELETE, current, detail="批量删除题目")
            deleted += 1
        return deleted

    def set_quality_flag(self, question_id: str, flag: QualityFlag) -> None:
        """设置人工质量标记，参与后续选题评分（需求 R5 第 3 条 / R8 第 8 条）。"""
        current = self._repository.get(question_id)
        if current is None:
            raise QuestionValidationError(f"题目不存在：{question_id}")
        flag = QualityFlag(flag)
        current.quality_flag = flag
        updated = self._repository.update(current)
        self._record(
            QuestionOpAction.UPDATE,
            updated,
            detail=f"质量标记改为「{flag.value}」",
        )

    def set_quality_flag_many(self, question_ids: list[str], flag: QualityFlag) -> int:
        """批量设置质量标记（用户需求：题库批量维护），返回处理数量。"""
        changed = 0
        for question_id in question_ids:
            try:
                self.set_quality_flag(question_id, flag)
            except QuestionValidationError:
                continue
            changed += 1
        return changed

    def reanalyze_difficulties(
        self, question_ids: list[str], confirmed: bool = False
    ) -> dict:
        """批量重析难度（仅 AI 来源题目，人工难度保持不变，需求 R5 第 4 条）。

        用户需求：所有使用 AI 的内容都需手动确认，``confirmed=False`` 时拒绝执行。

        :param question_ids: 待重分析的题目 id
        :param confirmed: 用户是否已在界面确认调用 AI
        :return: 难度服务返回的统计摘要
        """
        if not confirmed:
            raise AIServiceError("批量重析难度会调用 AI，需要出题者确认后执行")
        if not question_ids:
            return {"total": 0, "updated": 0, "skipped": 0, "failed": 0}
        return self._difficulty_service.batch_reanalyze(question_ids)

    def all_question_ids(self) -> list[str]:
        """返回题库中全部题目 id（批量重析全库难度用）。"""
        return [question.id for question in self._repository.search(QuestionFilter())]

    # ------------------------------------------------------------- 批量粘贴

    def batch_parse(self, raw_text: str) -> list[Question]:
        """把粘贴的多题文本拆分为候选题目列表（需求 R2 第 1 条）。"""
        blocks = [block.strip() for block in _BLOCK_SPLIT.split(raw_text or "") if block.strip()]
        return [self._parse_block(block) for block in blocks]

    def batch_commit(
        self, drafts: list[Question], analyze_difficulty: bool = False
    ) -> list[Question]:
        """批量写入确认后的候选题目（需求 R2 第 3 条）。

        :param analyze_difficulty: 用户是否已确认对入库题目调用 AI 分析难度
        """
        saved_questions: list[Question] = []
        batch_id = uuid.uuid4().hex[:12]
        failures: list[str] = []
        for index, draft in enumerate(drafts, start=1):
            try:
                self._normalize_enums(draft)
                self._validator.validate(draft)
            except QuestionValidationError as exc:
                failures.append(f"第 {index} 题：{exc}")
                continue
            saved = self._repository.save(draft)
            self._analyze_if_automatic(saved, analyze_difficulty)
            self._record(
                QuestionOpAction.IMPORT,
                saved,
                detail=f"批量导入（批次 {batch_id}）",
                batch_id=batch_id,
            )
            saved_questions.append(saved)
        if failures:
            raise QuestionValidationError(
                f"共 {len(failures)} 道题未通过校验：" + "；".join(failures)
            )
        return saved_questions

    # ------------------------------------------------------------- 检索统计

    def search(self, question_filter: QuestionFilter) -> list[Question]:
        """按条件检索题库（需求 R6 第 1 条），透传仓储查询。"""
        return self._repository.search(question_filter)

    def count_available(
        self,
        subject: str,
        difficulty: Difficulty,
        question_type: QuestionType,
        knowledge_points: list[str] | None = None,
    ) -> int:
        """统计某组卷条件的命中题数量（需求 R6 第 2 / 3 条）。

        :param knowledge_points: 指定知识点（用户需求：组卷时可指定知识点），
            非空表示只统计命中其中任一知识点的题目
        """
        return self._repository.count_available(
            subject, difficulty, question_type, knowledge_points
        )

    # ------------------------------------------------------------- AI 辨识

    def ai_configured(self) -> bool:
        """AI 服务是否已配置（未配置时界面禁用"AI 辨识"按钮）。"""
        return bool(self._ai_client is not None and self._ai_client.is_configured())

    def recognize_draft(
        self,
        stem: str,
        options: list[Option],
        include_solution: bool = True,
        confirmed: bool = False,
        modules: list[RecognizeModule] | list[str] | None = None,
    ) -> dict:
        """调用 AI 辨识题目字段，结果仅供参考（用户需求）。

        用户需求：所有使用 AI 的内容都需手动确认，``confirmed=False`` 时拒绝调用；
        界面在用户点击「AI 辨识」按钮或确认补全对话框后传 ``confirmed=True``。

        用户需求：模块化输出、按需给出、一次返回。只把 ``modules`` 中指明的模块
        （科目 / 知识点 / 题型 / 难度 / 质量标记 / 答案 / 解析）拼进提示词与期望
        结构，用**一次** AI 调用返回全部所需字段；未请求的字段不会出现在结果里。

        :param stem: 题干文本
        :param options: 当前已填选项（可为空）
        :param include_solution: 是否允许输出解析；为 False 时提示词与期望结构中
            都不包含解析，且结果的 solution 恒为空字符串
        :param confirmed: 用户是否已确认调用 AI
        :param modules: 需要 AI 给出的模块（``RecognizeModule`` 或其取值）；
            None 表示全部模块
        :return: 归一化后的字段字典，仅含被请求模块对应的键
        :raises app.domain.errors.AIServiceError: 未确认 / 未选模块 / 未配置或调用失败
        """
        if not confirmed:
            raise AIServiceError("AI 辨识会调用 AI，需要出题者确认后执行")
        report = self.recognize_draft_report(
            stem, options, include_solution, confirmed, modules
        )
        return report.fields

    def recognize_draft_report(
        self,
        stem: str,
        options: list[Option],
        include_solution: bool = True,
        confirmed: bool = False,
        modules: list[RecognizeModule] | list[str] | None = None,
    ) -> "RecognitionReport":
        """同 :meth:`recognize_draft`，但额外返回"AI 返回内容的问题清单"。

        用户需求：AI 返回信息出现问题时要有弹窗提示，因此这里把每个请求模块的
        缺失 / 无法识别情况收集为可读问题（如"AI 未返回知识点"、
        "AI 返回的难度无法识别：'一般'"），由界面弹窗展示；
        无法识别的字段不会写回结果（不静默套用默认值）。
        """
        if not confirmed:
            raise AIServiceError("AI 辨识会调用 AI，需要出题者确认后执行")
        if self._ai_client is None:
            raise AIServiceError("未接入 AI 客户端，无法进行 AI 辨识")
        requested = self._resolve_modules(modules)
        effective = [
            module
            for module in requested
            if include_solution or module is not RecognizeModule.SOLUTION
        ]
        if not effective:
            raise AIServiceError("要求不输出解析后没有其他模块需要 AI 辨识")
        subjects = self.list_subjects()
        prompts = load_prompt_config(self._config_store)
        template = prompts.recognize_prompt or DEFAULT_PROMPT_CONFIG.recognize_prompt
        sections_text = self._format_sections_for_prompt()
        blocks = self._render_module_prompts(prompts, effective, subjects, sections_text)
        prompt = render(
            template,
            DEFAULT_PROMPT_CONFIG.recognize_prompt,
            subjects="、".join(subjects),
            stem=stem,
            options="；".join(f"{o.key}. {o.text}" for o in options) or "无",
            modules=blocks,
        )
        if "{modules}" not in template:
            # 用户自定义总述未写 {modules} 占位符时，只补它还没提到的模块要求，
            # 避免同一字段（如难度）在提示词里出现两次（用户需求）
            extra = self._render_module_prompts(
                prompts,
                [m for m in effective if not self._template_mentions(template, m)],
                subjects,
                sections_text,
            )
            if extra:
                prompt = f"{prompt}\n{extra}"
        if not include_solution:
            prompt += "\n注意：本次不要输出解题解析，solution 请留空字符串。"
        data = self._ai_client.complete(prompt, recognize_schema(effective))
        report = self._normalize_recognition(data, effective, options, subjects)
        if not include_solution and RecognizeModule.SOLUTION in requested:
            report.fields["solution"] = ""
        return report

    @staticmethod
    def _template_mentions(template: str, module: RecognizeModule) -> bool:
        """总述模板里是否已经写了该字段的输出要求（避免追加时重复）。"""
        return f"{module.value}：" in template or f"{module.value}:" in template

    def _format_sections_for_prompt(self) -> str:
        """把"科目-板块-知识点"扁平为提示词可读的"板块：细分知识点"清单。

        供知识点模块的分级提示词使用；无配置时返回空串，由提示词兜底文本兜底。
        """
        try:
            sections = self._config_store.load_sections() if self._config_store else []
        except Exception:  # noqa: BLE001 - 非关键路径，降级为默认值
            sections = []
        items = sections or [
            KnowledgeSection(subject=subject, section=section, knowledge_points=list(points))
            for subject, groups in DEFAULT_KNOWLEDGE_SECTIONS.items()
            for section, points in groups.items()
        ]
        lines = [f"  - {item.section}：" + "、".join(item.knowledge_points) for item in items]
        return "\n".join(lines) if lines else ""

    @staticmethod
    def _flatten_sectioned_points(sectioned: dict) -> tuple[list[str], str]:
        """把分级输出 {板块: [细分知识点, ...]} 扁平为列表与板块名。

        一道题可涉及多个板块，板块名用"、"拼接；每个板块的细分知识点按顺序收集。
        """
        points: list[str] = []
        sections: list[str] = []
        for section, items in sectioned.items():
            name = str(section).strip()
            if name:
                sections.append(name)
            if not isinstance(items, list):
                continue
            points.extend(str(item).strip() for item in items if str(item).strip())
        return points, "、".join(sections)

    @staticmethod
    def _resolve_modules(
        modules: list[RecognizeModule] | list[str] | None,
    ) -> list[RecognizeModule]:
        """把外部传入的模块取值归一化为模块列表（去重并保持给定顺序）。"""
        if modules is None:
            requested = list(RECOGNIZE_MODULES)
        else:
            requested = []
            for item in modules:
                try:
                    module = item if isinstance(item, RecognizeModule) else RecognizeModule(item)
                except (TypeError, ValueError):
                    continue
                if module not in requested:
                    requested.append(module)
            if not requested:
                raise AIServiceError("请至少选择一个需要 AI 辨识的模块")
        return requested

    @staticmethod
    def _render_module_prompts(prompts, requested, subjects: list[str], sections: str = "") -> str:
        """把被勾选模块的输出提示词拼装为一段文本（按需给出，一次返回）。"""
        subject_text = "、".join(subjects)
        blocks: list[str] = []
        for module in requested:
            default = DEFAULT_MODULE_PROMPTS.get(module.value, "")
            fragment = prompts.module_prompts.get(module.value) or default
            if not fragment:
                continue
            blocks.append(
                render(fragment, default, subjects=subject_text, sections=sections)
            )
        return "\n".join(blocks)

    @staticmethod
    def module_states(question: Question) -> list[tuple[RecognizeModule, bool]]:
        """逐项检查题目各模块是否已填写（用户需求：保存 / 导入前逐项检查）。

        :return: ``[(模块, 是否已填写)]``，顺序与 :data:`RECOGNIZE_MODULES` 一致；
            题干与选项同样纳入检查，原文残缺时可由 AI 补全
        """
        states: list[tuple[RecognizeModule, bool]] = []
        for module in RECOGNIZE_MODULES:
            if module is RecognizeModule.SUBJECT:
                filled = bool((question.subject or "").strip())
            elif module is RecognizeModule.KNOWLEDGE_POINTS:
                filled = bool(question.knowledge_points)
            elif module is RecognizeModule.QUESTION_TYPE:
                filled = question.type is not None
            elif module is RecognizeModule.DIFFICULTY:
                filled = question.difficulty is not Difficulty.PENDING
            elif module is RecognizeModule.QUALITY_FLAG:
                filled = question.quality_flag is not None
            elif module is RecognizeModule.ANSWER:
                filled = bool([item for item in question.answer if str(item).strip()])
            elif module is RecognizeModule.STEM:
                filled = bool((question.stem or "").strip())
            elif module is RecognizeModule.OPTIONS:
                filled = bool(question.options)
            else:
                filled = bool((question.solution or "").strip())
            states.append((module, filled))
        return states

    @classmethod
    def missing_modules(cls, question: Question) -> list[RecognizeModule]:
        """返回尚未填写的模块列表（供"是否需要 AI 填充"弹窗逐项展示）。"""
        return [module for module, filled in cls.module_states(question) if not filled]

    @classmethod
    def required_missing_modules(cls, question: Question) -> list[RecognizeModule]:
        """返回尚未填写的必填模块（科目 / 知识点 / 答案，缺失时不许保存）。"""
        return [
            module
            for module in cls.missing_modules(question)
            if module in cls.REQUIRED_MODULES
        ]

    @staticmethod
    def apply_recognition(
        question: Question, result: dict, include_solution: bool = True
    ) -> Question:
        """把 AI 辨识结果写回题目草稿（仅覆盖结果中出现的字段）。

        供批量导入场景把 AI 填充结果落到候选题上；表单场景由界面把结果写回控件。
        分级知识点（{板块: [细分知识点]}）会被扁平为知识点列表，同时回填所属板块。
        """
        subject = str(result.get("subject", "")).strip()
        if subject:
            question.subject = subject

        section = str(result.get("section", "")).strip()
        if section:
            question.section = section

        points = result.get("knowledge_points")
        if points:
            question.knowledge_points = [str(item).strip() for item in points if str(item).strip()]

        stem = result.get("stem")
        if stem:
            question.stem = str(stem).strip()

        options = result.get("options")
        if options:
            question.options = options

        if result.get("question_type") is not None:
            question.type = QuestionType(result["question_type"])

        if result.get("difficulty") is not None:
            question.difficulty = Difficulty(result["difficulty"])
            question.difficulty_source = DifficultySource.AI

        if result.get("quality_flag") is not None:
            question.quality_flag = QualityFlag(result["quality_flag"])

        answer = [str(item).strip() for item in (result.get("answer") or []) if str(item).strip()]
        if answer:
            if question.type in (QuestionType.FILL, QuestionType.SOLUTION):
                question.options = []
                question.answer = answer
            else:
                question.answer = [item.upper() for item in answer]

        solution = result.get("solution")
        if include_solution and solution:
            question.solution = str(solution).strip()
        return question

    def list_subjects(self) -> list[str]:
        """返回可选科目列表（科目改为选择式录入，由设置界面维护）。"""
        if self._config_store is None:
            return list(DEFAULT_SUBJECTS)
        try:
            return list(self._config_store.load_subjects())
        except Exception:  # noqa: BLE001 - 配置读取失败回退默认科目
            return list(DEFAULT_SUBJECTS)

    def list_knowledge_points(self, subject: str | None = None) -> list[str]:
        """返回已有知识点（可按科目过滤），供录入与检索自动补全。"""
        try:
            return list(self._repository.list_knowledge_points(subject))
        except Exception:  # noqa: BLE001 - 补全数据非关键路径
            return []

    def list_sections(self, subject: str | None = None) -> dict[str, list[str]]:
        """返回知识板块与细分知识点（可按科目过滤），格式 ``{板块: [细分知识点, ...]}``。

        无配置或读取失败时返回默认值；``subject`` 为空时合并全部科目，
        供"选择板块后给出该板块知识点"的联动场景使用。
        """
        try:
            all_sections = (
                self._config_store.load_sections() if self._config_store else []
            )
        except Exception:  # noqa: BLE001 - 联动数据非关键路径
            all_sections = []
        sections = [
            KnowledgeSection(subject=s.subject, section=s.section, knowledge_points=list(s.knowledge_points))
            for s in (all_sections or [])
        ] or [
            KnowledgeSection(subject=subject, section=section, knowledge_points=list(points))
            for subject, groups in DEFAULT_KNOWLEDGE_SECTIONS.items()
            for section, points in groups.items()
        ]
        if subject is None:
            return {section.section: section.knowledge_points for section in sections}
        return {
            section.section: section.knowledge_points
            for section in sections
            if section.subject == subject
        }

    def statistics(self) -> dict[str, int]:
        """题库概览：总题数与各题型题量（用户需求：完成题库相关内容）。

        :return: ``{"total": 总数, "single": n, "multiple": n, "fill": n,
            "solution": n, "pending": n}``（pending 为难度待确认题量）
        """
        counts = self._repository.count_by_type()
        stats = {"total": sum(counts.values())}
        for question_type in QuestionType:
            stats[question_type.value] = counts.get(question_type.value, 0)
        pending = 0
        for question in self._repository.search(QuestionFilter(difficulty=Difficulty.PENDING)):
            pending += 1
        stats["pending"] = pending
        return stats

    def _cleanup_image(self, image_path: str | None) -> None:
        """删除题目 / 换图后清理本地图片文件（无其他题目引用时）。"""
        if not image_path or self._image_store is None:
            return
        try:
            if self._repository.count_by_image(image_path) == 0:
                self._image_store.delete(image_path)
        except Exception:  # noqa: BLE001 - 图片清理失败不影响主流程
            pass

    # ------------------------------------------------------------- 操作台账

    def list_operations(
        self, actions: list[QuestionOpAction] | None = None, limit: int | None = None
    ) -> list[QuestionOpRecord]:
        """读取题库操作台账（导入历史 / 编辑历史）。"""
        if self._op_repository is None:
            return []
        values: list[str] | None = None
        if actions:
            values = []
            for action in actions:
                values.append(
                    action.value
                    if isinstance(action, QuestionOpAction)
                    else QuestionOpAction(action).value
                )
        return self._op_repository.list_records(values, limit)

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _normalize_enums(question: Question) -> Question:
        """把枚举字段归一化为枚举成员，兼容外部传入的字符串取值。

        AI 返回、界面下拉与旧调用方都可能给出 ``"single"`` 这类字符串；
        若直接落库会在 ``question.type.value`` 处抛出
        ``'str' object has no attribute 'value'``，因此统一在服务入口收敛。

        :raises QuestionValidationError: 取值不在允许范围内（消息含字段与取值）
        """
        pairs = (
            ("题型", "type", QuestionType),
            ("难度", "difficulty", Difficulty),
            ("难度来源", "difficulty_source", DifficultySource),
            ("质量标记", "quality_flag", QualityFlag),
            ("来源", "source", QuestionSource),
        )
        for label, field_name, enum_cls in pairs:
            value = getattr(question, field_name, None)
            try:
                setattr(question, field_name, enum_cls(value))
            except (TypeError, ValueError) as exc:
                raise QuestionValidationError(
                    f"{label}取值非法：{value!r}（可选值："
                    + "、".join(member.value for member in enum_cls)
                    + "）"
                ) from exc
        return question

    def _analyze_if_automatic(self, question: Question, enabled: bool = False) -> None:
        """在用户已确认的前提下调用 AI 分析难度。

        用户需求：所有使用 AI 的内容都需手动确认，因此默认 ``enabled=False``
        时不会发起任何 AI 调用，难度保持"待确认"，由出题者手工设置。
        人工难度（difficulty_source = MANUAL）与已有难度值同样保持不变
        （需求 R4 第 4 条 / R5 第 4 条）。
        """
        if not enabled:
            return
        if question.difficulty_source is DifficultySource.MANUAL:
            return
        if question.difficulty is not Difficulty.PENDING:
            return
        difficulty = self._difficulty_service.analyze_silent(question)
        question.difficulty = difficulty
        if difficulty is not Difficulty.PENDING:
            self._repository.update(question)

    def _record(
        self,
        action: QuestionOpAction,
        question: Question,
        detail: str = "",
        batch_id: str | None = None,
    ) -> None:
        """写入一条题库操作记录；台账写入失败不影响主流程。"""
        if self._op_repository is None:
            return
        record = QuestionOpRecord(
            id="",
            action=action,
            question_id=question.id,
            subject=question.subject,
            stem_excerpt=question.stem[:60],
            batch_id=batch_id,
            detail=detail,
        )
        try:
            self._op_repository.record(record)
        except Exception:  # noqa: BLE001 - 台账非关键路径
            pass

    @staticmethod
    def _diff_detail(old: Question, new: Question) -> str:
        """比较新旧题目，生成可读的编辑说明。"""
        parts: list[str] = []
        if old.subject != new.subject:
            parts.append(f"科目：{old.subject or '—'} → {new.subject or '—'}")
        if old.type != new.type:
            parts.append(f"题型：{old.type.value} → {new.type.value}")
        if old.difficulty != new.difficulty:
            parts.append(f"难度：{old.difficulty.value} → {new.difficulty.value}")
        if old.quality_flag != new.quality_flag:
            parts.append(
                f"质量：{old.quality_flag.value} → {new.quality_flag.value}"
            )
        if old.stem != new.stem:
            parts.append("题干已修改")
        if old.answer != new.answer:
            parts.append("答案已修改")
        if old.image_path != new.image_path:
            parts.append("图片已更新")
        return "；".join(parts) if parts else "保存编辑（内容无变化）"

    def _parse_block(self, block: str) -> Question:
        """解析单个题块为候选题目（需求 R2）。"""
        fields: dict[str, str] = {}
        current: str | None = None
        for line in block.splitlines():
            match = _LABEL_LINE.match(line)
            alias = None
            if match:
                alias = _FIELD_ALIASES.get(match.group(1).strip().lower())
            if alias:
                current = alias
                fields[alias] = match.group(2).strip()
            elif current:
                # 未标注"选项："时，题干后紧跟的 A./B. 行按选项归类
                if current in ("stem", "options") and _OPTION_LINE.match(line.strip()):
                    current = "options"
                    fields["options"] = (
                        (fields.get("options", "") + "\n" + line).strip()
                    )
                else:
                    fields[current] = (fields[current] + "\n" + line).strip()

        if not fields:
            # 完全无字段标签：把 A./B. 行抽为选项，其余作为题干
            stem_lines: list[str] = []
            option_lines: list[str] = []
            for line in block.splitlines():
                if _OPTION_LINE.match(line.strip()):
                    option_lines.append(line)
                else:
                    stem_lines.append(line)
            fields["stem"] = "\n".join(stem_lines).strip()
            fields["options"] = "\n".join(option_lines)

        stem = fields.get("stem", "").strip() or block.strip()
        options = self._parse_options(fields.get("options", ""))
        question_type = self._parse_type(fields.get("type", ""), options, fields.get("answer", ""))
        if question_type in (QuestionType.SOLUTION, QuestionType.FILL):
            options = []
        return Question(
            id="",
            subject=fields.get("subject", "").strip(),
            knowledge_points=self._split_knowledge(fields.get("knowledge", "")),
            type=question_type,
            stem=stem,
            options=options,
            answer=self._parse_answer(fields.get("answer", ""), question_type),
            solution=fields.get("solution", "").strip() or None,
            difficulty=_DIFFICULTY_WORDS.get(
                fields.get("difficulty", "").strip().lower(), Difficulty.PENDING
            ),
            difficulty_source=(
                DifficultySource.MANUAL
                if fields.get("difficulty", "").strip()
                else DifficultySource.AI
            ),
        )

    @staticmethod
    def _parse_options(raw: str) -> list[Option]:
        """从"选项"段落解析选项列表。"""
        options: list[Option] = []
        for line in raw.splitlines():
            match = _OPTION_LINE.match(line.strip())
            if match:
                options.append(Option(key=match.group(1).upper(), text=match.group(2).strip()))
        return options

    @staticmethod
    def _parse_type(
        raw: str, options: list[Option], answer: str
    ) -> QuestionType:
        """推断题型：显式标注优先，其次按选项与答案形态判断。"""
        text = raw.strip().lower()
        for word, question_type in _TYPE_WORDS.items():
            if word in text:
                return question_type
        if len(options) >= 2:
            letters = re.findall(r"[A-Za-z]", answer)
            return QuestionType.SINGLE if len(letters) <= 1 else QuestionType.MULTIPLE
        return QuestionType.SOLUTION

    @staticmethod
    def _parse_answer(raw: str, question_type: QuestionType) -> list[str]:
        """解析答案：选择题取标号，填空题 / 解答题取参考答案文本。"""
        text = raw.strip()
        if not text:
            return []
        if question_type in (QuestionType.SOLUTION, QuestionType.FILL):
            return [text]
        return sorted({letter.upper() for letter in re.findall(r"[A-Za-z]", text)})

    @staticmethod
    def _split_knowledge(raw: str) -> list[str]:
        """拆分知识点（支持中英文逗号、顿号与空格分隔）。"""
        return [
            part.strip()
            for part in re.split(r"[,，、;；\s]+", raw or "")
            if part.strip()
        ]

    @staticmethod
    def _module_name(module: RecognizeModule) -> str:
        """模块的中文名（用于问题提示文案）。"""
        return _MODULE_NAMES.get(module, module.value)

    def _normalize_recognition(
        self,
        data: dict,
        requested: list[RecognizeModule] | None = None,
        options: list[Option] | None = None,
        subjects: list[str] | None = None,
    ) -> RecognitionReport:
        """把 AI 返回结果归一化为 :class:`RecognitionReport`。

        只保留 ``requested`` 中列出的模块（按需给出、一次返回）：未请求的字段
        不会出现在结果里，界面据此只回填用户勾选的内容。

        用户需求（AI 返回信息出问题时要提示）：AI 未返回某字段、或返回了无法
        识别的取值时，记入 ``issues`` 供界面弹窗；这类字段**不写入结果**，
        以免把无法识别的取值静默变成默认值。
        """
        wanted = list(requested) if requested is not None else list(RECOGNIZE_MODULES)
        result: dict = {}
        issues: list[str] = []
        configured_subjects = list(subjects or [])

        if RecognizeModule.SUBJECT in wanted:
            subject = str(data.get("subject", "")).strip()
            if not subject:
                issues.append("AI 未返回科目（subject）")
            elif configured_subjects and subject not in configured_subjects:
                issues.append(
                    f"AI 建议的科目「{subject}」不在科目列表中，"
                    "请先在「设置 -> 科目管理」维护"
                )
            else:
                result["subject"] = subject

        if RecognizeModule.KNOWLEDGE_POINTS in wanted:
            points = data.get("knowledge_points") or data.get("knowledge") or []
            section = ""
            if isinstance(points, str):
                points = self._split_knowledge(points)
            elif isinstance(points, dict):
                # 分级输出（先板块、再细分知识点），支持一道题涉及多个板块
                points, section = self._flatten_sectioned_points(points)
            else:
                points = []
            cleaned = [str(item).strip() for item in points if str(item).strip()]
            if cleaned:
                result["knowledge_points"] = cleaned
                if section:
                    result["section"] = section
            else:
                issues.append("AI 未返回知识点（knowledge_points）")

        type_raw = str(data.get("question_type", data.get("type", ""))).strip()
        if RecognizeModule.QUESTION_TYPE in wanted:
            question_type = next(
                (value for word, value in _TYPE_WORDS.items() if word in type_raw.lower()),
                None,
            )
            if question_type is None:
                issues.append(
                    "AI 未返回可识别的题型（question_type）"
                    if not type_raw
                    else f"AI 返回的题型无法识别：{type_raw[:30]!r}"
                )
            else:
                result["question_type"] = question_type

        if RecognizeModule.DIFFICULTY in wanted:
            difficulty_raw = str(data.get("difficulty", "")).strip().lower()
            difficulty = _DIFFICULTY_WORDS.get(difficulty_raw)
            if difficulty is None and difficulty_raw:
                difficulty = next(
                    (value for word, value in _DIFFICULTY_WORDS.items() if word in difficulty_raw),
                    None,
                )
            if difficulty is None:
                issues.append(
                    "AI 未返回难度（difficulty）"
                    if not difficulty_raw
                    else f"AI 返回的难度无法识别：{difficulty_raw[:30]!r}"
                )
            else:
                result["difficulty"] = difficulty

        if RecognizeModule.QUALITY_FLAG in wanted:
            quality_raw = str(data.get("quality_flag", "")).strip().lower()
            quality = _QUALITY_WORDS.get(quality_raw)
            if quality is None and quality_raw:
                quality = next(
                    (value for word, value in _QUALITY_WORDS.items() if word in quality_raw),
                    None,
                )
            if quality is None:
                issues.append(
                    "AI 未返回质量标记（quality_flag）"
                    if not quality_raw
                    else f"AI 返回的质量标记无法识别：{quality_raw[:30]!r}"
                )
            else:
                result["quality_flag"] = quality

        if RecognizeModule.ANSWER in wanted:
            answer = data.get("answer", data.get("参考答案", []))
            if isinstance(answer, str):
                fallback_type = result.get("question_type") or QuestionType.SINGLE
                if not type_raw:
                    fallback_type = self._parse_type("", list(options or []), answer)
                answer = self._parse_answer(answer, fallback_type)
            if not isinstance(answer, list):
                answer = []
            cleaned_answer = [
                str(item).strip() for item in answer if str(item).strip()
            ]
            if cleaned_answer:
                result["answer"] = cleaned_answer
            elif data.get("answer") in (None, "", []):
                issues.append("AI 未返回答案（answer）")
            else:
                issues.append("AI 返回的答案为空白")

        if RecognizeModule.STEM in wanted:
            stem = str(data.get("stem", "")).strip()
            if stem:
                result["stem"] = stem
            else:
                issues.append("AI 未返回题干（stem）")

        if RecognizeModule.OPTIONS in wanted:
            raw_options = data.get("options")
            if isinstance(raw_options, list):
                options = [
                    Option(key=str(item.get("key", "")).strip(), text=str(item.get("text", "")).strip())
                    for item in raw_options
                    if isinstance(item, dict)
                    and str(item.get("key", "")).strip()
                    and str(item.get("text", "")).strip()
                ]
                if options:
                    result["options"] = options
                else:
                    issues.append("AI 返回的选项缺少有效内容（options）")
            else:
                issues.append("AI 未返回有效选项（options）")

        if RecognizeModule.SOLUTION in wanted:
            solution = data.get("solution")
            result["solution"] = str(solution).strip() if solution else ""

        return RecognitionReport(fields=result, issues=issues)


# 兼容旧导入名：指向 QuestionService 上的规范定义
REQUIRED_MODULES = QuestionService.REQUIRED_MODULES
