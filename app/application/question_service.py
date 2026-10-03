"""题目服务：题库 CRUD、批量粘贴解析、AI 辨识与可用量统计。

职责对应需求：

- R1：题目手工录入与维护（保存 / 编辑 / 删除）
- R2：批量粘贴录入（解析预览 -> 确认提交）
- R5：难度、标签与质量人工修正
- R6：题库检索与可用量统计
- 用户需求：AI 辨识科目 / 知识点 / 题型 / 难度 / 质量 / 答案 / 解析（结果仅供参考）
- 用户需求：题库操作台账（导入历史 / 编辑历史）

依赖（构造注入，全部为抽象）：
- app.interfaces.repositories.QuestionRepository
- app.interfaces.repositories.QuestionOpRepository（可选，操作台账）
- app.interfaces.repositories.ConfigStore（可选，科目列表与提示词）
- app.interfaces.ai_client.AIClient（可选，AI 辨识）
- app.domain.validators.question_validator.QuestionValidator
- app.application.difficulty_service.DifficultyService

被使用：app.presentation.views.question_bank_view、app.container
"""

import re
import uuid

from app.application.difficulty_service import DifficultyService
from app.application.prompt_utils import load_prompt_config, render
from app.config.settings import DEFAULT_PROMPT_CONFIG, DEFAULT_SUBJECTS
from app.domain.entities.question import Option, Question, QuestionFilter
from app.domain.entities.question_op import QuestionOpRecord
from app.domain.enums import (
    Difficulty,
    DifficultySource,
    QualityFlag,
    QuestionOpAction,
    QuestionSource,
    QuestionType,
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
        "knowledge_points": {"type": "array", "items": {"type": "string"}},
        "question_type": {"type": "string"},
        "difficulty": {"type": "string"},
        "quality_flag": {"type": "string"},
        "answer": {"type": "array", "items": {"type": "string"}},
        "solution": {"type": "string"},
    },
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


class QuestionService:
    """题目服务：题库维护的统一入口。"""

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

    def create_question(self, draft: Question) -> Question:
        """新增题目：校验通过后落库并触发 AI 难度分析（需求 R1 / R4）。"""
        self._normalize_enums(draft)
        self._validator.validate(draft)
        saved = self._repository.save(draft)
        self._analyze_if_automatic(saved)
        self._record(
            QuestionOpAction.CREATE,
            saved,
            detail=f"录入题目（{saved.type.value}）",
        )
        return saved

    def update_question(self, question_id: str, patch: dict) -> Question:
        """编辑题目：合并字段、校验后更新，保留 id 与使用记录（需求 R1 第 3 条）。"""
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
        self._analyze_if_automatic(updated)
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

    def reanalyze_difficulties(self, question_ids: list[str]) -> dict:
        """批量重析难度（仅 AI 来源题目，人工难度保持不变，需求 R5 第 4 条）。

        :return: 难度服务返回的统计摘要
        """
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

    def batch_commit(self, drafts: list[Question]) -> list[Question]:
        """批量写入确认后的候选题目（需求 R2 第 3 条）。"""
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
            self._analyze_if_automatic(saved)
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
        self, subject: str, difficulty: Difficulty, question_type: QuestionType
    ) -> int:
        """统计某组卷条件的命中题数量（需求 R6 第 2 / 3 条）。"""
        return self._repository.count_available(subject, difficulty, question_type)

    # ------------------------------------------------------------- AI 辨识

    def ai_configured(self) -> bool:
        """AI 服务是否已配置（未配置时界面禁用"AI 辨识"按钮）。"""
        return bool(self._ai_client is not None and self._ai_client.is_configured())

    def recognize_draft(
        self, stem: str, options: list[Option], include_solution: bool = True
    ) -> dict:
        """调用 AI 辨识题目字段，结果仅供参考（用户需求）。

        :param stem: 题干文本
        :param options: 当前已填选项（可为空）
        :param include_solution: 是否要求 AI 输出解析；为 False 时提示词明确
            要求不输出解析，且返回结果的 solution 恒为空（用户需求）
        :return: 归一化后的字段字典，键包含 subject / knowledge_points /
            question_type / difficulty / quality_flag / answer / solution
        :raises app.domain.errors.AIServiceError: 未配置或调用失败
        """
        if self._ai_client is None:
            raise AIServiceError("未接入 AI 客户端，无法进行 AI 辨识")
        subjects = self.list_subjects()
        prompts = load_prompt_config(self._config_store)
        prompt = render(
            prompts.recognize_prompt,
            DEFAULT_PROMPT_CONFIG.recognize_prompt,
            subjects="、".join(subjects),
            stem=stem,
            options="；".join(f"{o.key}. {o.text}" for o in options) or "无",
        )
        if not include_solution:
            prompt += "\n注意：本次不要输出解题解析，solution 请留空字符串。"
        data = self._ai_client.complete(prompt, RECOGNIZE_SCHEMA)
        result = self._normalize_recognition(data)
        if not include_solution:
            result["solution"] = ""
        return result

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

    def _analyze_if_automatic(self, question: Question) -> None:
        """难度来源为 AI 且尚未标注时执行难度分析。

        人工设置（difficulty_source = MANUAL）或已带难度值的题目保持不变
        （需求 R4 第 4 条 / R5 第 4 条）。
        """
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

    def _normalize_recognition(self, data: dict) -> dict:
        """把 AI 返回结果归一化为界面可直接使用的字段字典。"""
        subject = str(data.get("subject", "")).strip()
        points = data.get("knowledge_points") or data.get("knowledge") or []
        if isinstance(points, str):
            points = self._split_knowledge(points)
        if not isinstance(points, list):
            points = []

        type_raw = str(data.get("question_type", data.get("type", ""))).strip().lower()
        question_type = next(
            (value for word, value in _TYPE_WORDS.items() if word in type_raw),
            QuestionType.SINGLE,
        )

        answer = data.get("answer", [])
        if isinstance(answer, str):
            answer = self._parse_answer(answer, question_type)
        if not isinstance(answer, list):
            answer = []

        solution = data.get("solution")
        return {
            "subject": subject,
            "knowledge_points": [str(item).strip() for item in points if str(item).strip()],
            "question_type": question_type,
            "difficulty": _DIFFICULTY_WORDS.get(
                str(data.get("difficulty", "")).strip().lower(), Difficulty.PENDING
            ),
            "quality_flag": _QUALITY_WORDS.get(
                str(data.get("quality_flag", "")).strip().lower(), QualityFlag.NORMAL
            ),
            "answer": [str(item).strip() for item in answer if str(item).strip()],
            "solution": str(solution).strip() if solution else "",
        }
