# 接口文档（INTERFACES）

Feature Name: question-paper-generator
Updated: 2026-10-03

本文给出全部抽象接口与服务类的**方法签名、参数与返回、异常、实现者与调用者**，
以及关键调用链。文件级"谁依赖谁"见 `DEPENDENCIES.md`。

约定：

- 抽象接口位于 `app/interfaces/`，实现位于 `app/infrastructure/`，
  应用服务通过构造注入持有接口类型。
- 异常类型定义于 `app/domain/errors.py`。
- 各方法对应的需求编号以 (Rn) 标注。

## 1. 抽象接口（端口）

### 1.1 QuestionRepository —— 题目仓储

```python
class QuestionRepository(ABC):
    def save(self, question: Question) -> Question
    def get(self, question_id: str) -> Question | None
    def update(self, question: Question) -> Question
    def delete(self, question_id: str) -> None
    def search(self, question_filter: QuestionFilter) -> list[Question]
    def count_available(self, subject: str, difficulty: str, question_type: str) -> int
    def list_knowledge_points(self, subject: str | None = None) -> list[str]
    def count_by_type(self) -> dict[str, int]
    def count_by_image(self, image_path: str) -> int
```

| 项 | 说明 |
|----|------|
| 实现 | `infrastructure/repositories/question_repository.py::SQLiteQuestionRepository` |
| 调用方 | `application/question_service`、`application/paper_composer`、`application/question_generator` |
| 语义 | save 分配唯一 id (R1)；update 保留 id 与使用记录 (R1)；search 按 QuestionFilter 组合过滤 (R6) |
| 异常 | `sqlite3.Error` 由仓储向上传播，服务层转译为界面提示 |

### 1.2 UsageRepository —— 使用记录仓储

```python
class UsageRepository(ABC):
    def record_usage(self, question_ids: list[str], used_at: datetime) -> None
    def get(self, question_id: str) -> UsageRecord
    def get_many(self, question_ids: list[str]) -> dict[str, UsageRecord]
```

| 项 | 说明 |
|----|------|
| 实现 | `infrastructure/repositories/usage_repository.py::SQLiteUsageRepository` |
| 调用方 | `application/paper_composer`（组卷后写入）、`application/selection_scorer`（评分前读取） |
| 语义 | record_usage 单事务内 use_count+1 并更新 last_used_at (R13-1)；get 无记录返回零值记录 |
| 不变量 | use_count 每次入卷递增 1；last_used_at = 该次组卷时间（Correctness #10） |

### 1.3 TaskRepository —— 组卷任务仓储

```python
class TaskRepository(ABC):
    def save_task(self, task: GenerationTask) -> None
    def get_task(self, task_id: str) -> GenerationTask | None
    def list_tasks(self) -> list[GenerationTask]
```

| 项 | 说明 |
|----|------|
| 实现 | `infrastructure/repositories/task_repository.py::SQLiteTaskRepository` |
| 调用方 | `application/task_history_service` |
| 语义 | list_tasks 按创建时间倒序 (R14-2)；save_task 连同导出记录一并保存 (R14-1) |

### 1.4 ConfigStore —— 配置存储

```python
class ConfigStore(ABC):
    def load_ai_config(self) -> AIConfig
    def save_ai_config(self, config: AIConfig) -> None
    def load_scoring_config(self) -> ScoringConfig
    def save_scoring_config(self, config: ScoringConfig) -> None
    def load_prompt_config(self) -> PromptConfig      # AI 提示词（用户可改）
    def save_prompt_config(self, config: PromptConfig) -> None
    def load_subjects(self) -> list[str]              # 科目列表（选择式录入）
    def save_subjects(self, subjects: list[str]) -> None
```

| 项 | 说明 |
|----|------|
| 实现 | `infrastructure/config_store.py::SQLiteConfigStore`（settings 键值表，JSON 值） |
| 调用方 | `app/container.py`（装配）、`presentation/views/settings_view`、`application/{question_service,difficulty_service}`（提示词与科目） |
| 语义 | 无记录 / 解析失败回退 `config/settings.py` 默认值；提示词为空时逐项回退默认模板；科目列表去重且保序，为空时回退默认科目 |
| 隐私 | API Key 仅存本机 settings 表，禁止外传或写日志 (R18) |

### 1.5 QuestionOpRepository —— 题库操作台账（用户需求）

```python
class QuestionOpRepository(ABC):
    def record(self, record: QuestionOpRecord) -> None
    def list_records(self, actions: list[str] | None = None,
                     limit: int | None = None) -> list[QuestionOpRecord]
```

| 项 | 说明 |
|----|------|
| 实现 | `infrastructure/repositories/question_op_repository.py::SQLiteQuestionOpRepository` |
| 调用方 | `application/question_service`（写入）、`application/question_history_service`（读取）、`app/container.py` |
| 语义 | 历史界面据此分两类展示：导入历史（手工录入 create + 批量导入 import）与编辑历史（update / delete） |

### 1.6 AIClient —— AI API 客户端

```python
class AIClient(ABC):
    def complete(self, prompt: str, response_schema: dict | None = None) -> dict
    def is_configured(self) -> bool
```

| 项 | 说明 |
|----|------|
| 实现 | `infrastructure/ai/ai_client.py::OpenAICompatibleAIClient`（OpenAI 兼容 /chat/completions） |
| 调用方 | `application/difficulty_service`（难度分析，R4）、`application/question_generator`（AI 补题，R10） |
| 异常 | `AIServiceError`：超时 / 网络失败 / 重试耗尽 / JSON 不合规 (R4-3、R15-4)；`AIConfigMissingError`：未配置 (R15-2) |
| 调用时序 | complete -> is_configured 前置校验 -> 请求（timeout=max_retries 取自 AIConfig）-> 解析 schema -> 返回 dict |

### 1.7 BaseExporter —— 试卷导出器

```python
class BaseExporter(ABC):
    def export(self, paper: Paper, target_dir: str,
               options: ExportOptions | None = None) -> str
```

| 项 | 说明 |
|----|------|
| 实现 | `infrastructure/exporters/txt_exporter.py::TxtExporter`、`infrastructure/exporters/pdf_exporter.py::PdfExporter` |
| 调用方 | `application/paper_exporter`（按 ExportFormat 路由） |
| 语义 | 返回生成文件路径；排版契约：两部分分区 / 题型大题 / 小计与总分 / 卷末答案页 (R12) |
| 异常 | `ExportError`：目录不可写 / 渲染依赖缺失（PDF 缺 reportlab 时提示改用 TXT，R18-4） |

### 1.8 LocalImageStore —— 题目图片本地存储（用户需求）

```python
class LocalImageStore:                      # infrastructure/image_store.py
    def __init__(self, root, subdir: str = "images") -> None
    def save(self, source: str | Path) -> str        # 复制进 images/，返回相对路径
    def resolve(self, relative: str | None) -> Path | None
    def delete(self, relative: str | None) -> None
    @staticmethod
    def is_supported(source) -> bool
```

- 数据库只存相对路径（如 `images/xxx.png`），图片文件位于数据库同级 `images/` 目录。
- 异常：`ImageImportError`（文件不存在 / 格式不支持）；支持 png / jpg / jpeg / bmp / gif / webp。
- 调用方：`presentation/views/question_bank_view`（选择图片、预览）；由容器持有具体实现。

## 2. 领域校验器

### 2.1 QuestionValidator（R3）

```python
class QuestionValidator:
    def validate(self, question: Question) -> None
    def validate_many(self, questions: list[Question]) -> list[Question]
```

- `validate`：非法时抛 `QuestionValidationError`，消息说明不一致原因。
  规则：单选 >=2 选项且答案恰 1 个 key；多选 >=2 选项且答案 >=1 个 key；
  填空题无选项且参考答案非空；解答题无选项且参考答案非空；科目 / 题干 / 知识点非空。
- 枚举容错：`QuestionService` 在入库前统一把 `type / difficulty /
  difficulty_source / quality_flag / source` 归一化为枚举成员（接受 `"single"`
  这类字符串），仓储层 `_to_row` 亦做同样兜底，避免
  `'str' object has no attribute 'value'`；取值非法时抛出带可选值的可读错误。
- `validate_many`：批量粘贴场景，返回通过列表，失败信息聚合抛出。
- 调用方：`application/question_service`（入库前）、`application/question_generator`（AI 题校验，R10-4）。

### 2.2 ScoreValidator（R11-4）

```python
class ScoreValidator:
    def validate(self, paper: Paper) -> None
```

- 校验每道题均有生效分值且总分一致，非法抛 `ScoreValidationError`。
- 调用方：`application/paper_exporter`（导出前拦截）。

## 3. 应用服务公开方法

### 3.1 QuestionService（R1 / R2 / R5 / R6）

```python
QuestionService(repository: QuestionRepository,
                validator: QuestionValidator,
                difficulty_service: DifficultyService)

def create_question(self, draft: Question) -> Question          # 校验 -> 落库 -> 触发难度分析
def update_question(self, question_id: str, patch: dict) -> Question
def delete_question(self, question_id: str) -> None
def set_quality_flag(self, question_id: str, flag: QualityFlag) -> None
def batch_parse(self, raw_text: str) -> list[Question]           # 粘贴文本 -> 候选题（含"待修正"标记）
def batch_commit(self, drafts: list[Question]) -> list[Question]
def search(self, question_filter: QuestionFilter) -> list[Question]
def count_available(self, subject: str, difficulty: Difficulty, question_type: QuestionType) -> int
# 用户需求追加：
def list_subjects(self) -> list[str]                     # 可选科目（设置中维护）
def list_knowledge_points(self, subject: str | None = None) -> list[str]
        # 知识点字典，供录入 / 检索自动补全
def statistics(self) -> dict[str, int]                   # 题库概览：总题数与各题型题量
def delete_questions(self, question_ids: list[str]) -> int       # 批量删除
def set_quality_flag_many(self, question_ids: list[str], flag: QualityFlag) -> int
def reanalyze_difficulties(self, question_ids: list[str]) -> dict  # 批量重析难度
def all_question_ids(self) -> list[str]
def ai_configured(self) -> bool                          # AI 是否已配置（决定按钮可用性）
def recognize_draft(self, stem: str, options: list[Option],
                    include_solution: bool = True) -> dict
        # AI 辨识科目 / 知识点 / 题型 / 难度 / 质量 / 答案 / 解析；结果仅供参考，
        # include_solution=False 时要求 AI 不输出解析（用户需求）
def list_operations(self, actions=None, limit=None) -> list[QuestionOpRecord]
        # 导入历史 / 编辑历史台账
```

**AI 确认约定（用户需求）**：所有会调用 AI 的方法都必须显式确认，未确认时拒绝执行：

```text
create_question(draft, analyze_difficulty=False)      # True 才调用 AI 分析难度
update_question(id, patch, analyze_difficulty=False)
batch_commit(drafts, analyze_difficulty=False)
recognize_draft(stem, options, include_solution=True, confirmed=False)   # True 才调用 AI
reanalyze_difficulties(ids, confirmed=False)                             # True 才调用 AI
PaperComposer.generate(criteria, allow_ai_supplement=False)               # True 才允许 AI 补题
QuestionGenerator.generate_questions(..., allow_ai=False)                 # True 才调用 AI
```

界面在每次 AI 动作前弹出确认框（「AI 分析 / AI 辨识 / 允许 AI 补题 / 跳过」），
用户确认后才传对应标志；拒绝时不发起任何 AI 请求。

调用方：`presentation/views/question_bank_view`（录入 / 编辑 / 检索 / AI 辨识）、
`presentation/views/history_view`（经 QuestionHistoryService 读取台账）。

### 3.1.1 QuestionHistoryService（用户需求：历史中的导入 / 编辑历史）

```python
QuestionHistoryService(op_repository: QuestionOpRepository)

def list_import_history(self, limit: int = 500) -> list[QuestionOpRecord]
def list_edit_history(self, limit: int = 500) -> list[QuestionOpRecord]
```

调用方：`presentation/views/history_view`。

### 3.2 DifficultyService（R4 / R5）

```python
DifficultyService(ai_client: AIClient, config_store: ConfigStore | None = None)

def analyze(self, question: Question) -> Difficulty        # 失败抛 AIServiceError
def analyze_silent(self, question: Question) -> Difficulty # 失败返回 PENDING，不抛异常
def batch_reanalyze(self, question_ids: list[str]) -> dict # 存量题重析：人工难度不覆盖，
                                                           # 返回 {total, updated, skipped, failed}
```

| 项 | 说明 |
|----|------|
| 构造 | `DifficultyService(ai_client, config_store=None, question_repository=None)` |
| 提示词 | 取自 ConfigStore 的 PromptConfig（设置界面可改，改后立即生效） |

调用方：`application/question_service`（analyze_silent）、`question_bank_view`（手动重析，可选）。

### 3.3 SelectionScorer（R8，核心算法）

```python
SelectionScorer(usage_repository: UsageRepository,
                cooldown_policy: CooldownPolicy,
                config: ScoringConfig)

def score(self, candidates: list[Question], context: ScoringContext) -> list[ScoredQuestion]
def difficulty_match_factor(self, question: Question, context: ScoringContext) -> float
def knowledge_coverage_factor(self, question: Question, context: ScoringContext) -> float
def quality_factor(self, question: Question) -> float
```

- 评分公式：`score = w1*难度匹配 + w2*知识点覆盖 + w3*质量 - w4*频次惩罚 - w5*近期惩罚`。
- `score` 返回按评分降序的 `ScoredQuestion` 列表（weight = score，供 WeightedSampler 使用）。
- 调用方：`application/paper_composer`。

### 3.4 CooldownPolicy（R13）

```python
CooldownPolicy(config: ScoringConfig)

def in_cooldown(self, record: UsageRecord, now: datetime) -> bool
def recency_penalty(self, record: UsageRecord, now: datetime) -> float   # 间隔越短越大，窗口内加重
def use_count_penalty(self, record: UsageRecord) -> float                # 次数越多越大
def relax_factor(self, relax_level: int) -> float                        # 放宽系数，(0, 1]
def window_delta(config: ScoringConfig) -> timedelta                     # days 模式换算
```

调用方：`application/selection_scorer`；`paper_composer` 在窗口内题量不足时提高 relax_level。

### 3.5 WeightedSampler（R9）

```python
WeightedSampler(rng: random.Random | None = None, epsilon: float = 1e-6)

def sample(self, scored: list[ScoredQuestion], k: int) -> list[ScoredQuestion]
```

- 不放回加权随机；权重 `max(score, epsilon)` 恒正（Correctness #6 / #7）。
- rng 可注入：测试用固定种子复现。
- 调用方：`application/paper_composer`。

### 3.6 PaperComposer（R7-R10 / R13，核心编排）

```python
PaperComposer(question_repository: QuestionRepository,
              usage_repository: UsageRepository,
              selection_scorer: SelectionScorer,
              weighted_sampler: WeightedSampler,
              question_generator: QuestionGenerator,
              score_calculator: ScoreCalculator,
              config: ScoringConfig)

def generate(self, criteria: PaperCriteria) -> Paper
# 内部私有步骤：
def _validate_criteria(self, criteria: PaperCriteria) -> None          # 全停用 / 数量非法 -> CriteriaValidationError
def _select_for_requirement(self, requirement: TypeRequirement) -> list[Question]
def _record_usage(self, questions: list[Question]) -> None
```

调用方：`presentation/views/paper_generation_view`。

### 3.7 ScoreCalculator（R11 / R12-6）

```python
ScoreCalculator()

def set_type_score(self, section: Section, per_question_score: float) -> None
def set_question_score(self, section: Section, question_id: str, score: float) -> None
def section_subtotal(self, section: Section) -> float
def total_score(self, paper: Paper) -> float
def build_answer_page(self, paper: Paper) -> None    # 解答题答案含参考答案与解析
```

调用方：`application/paper_composer`、`paper_generation_view`。

### 3.8 PaperExporter（R12 / R18）

```python
PaperExporter(exporters: dict[ExportFormat, BaseExporter],
              score_validator: ScoreValidator)

def export(self, paper: Paper, fmt: ExportFormat, target_dir: str,
           options: ExportOptions | None = None) -> str
def supported_formats(self) -> list[ExportFormat]
```

异常：`ScoreValidationError`（缺分值阻止导出）、`ExportError`。
调用方：`paper_generation_view`。

### 3.9 TaskHistoryService（R14）

```python
TaskHistoryService(task_repository: TaskRepository)

def save_task(self, task: GenerationTask) -> None
def attach_export_record(self, task_id: str, file_path: str, fmt: str) -> None
def list_tasks(self) -> list[GenerationTask]
def reuse_criteria(self, task_id: str) -> PaperCriteria   # 仅回填条件，题单允许不同
```

调用方：`history_view`；`paper_composer` 组卷完成后保存任务。

## 4. 关键调用链（接口视角）

### 4.1 入库链

```text
QuestionBankView
  -> QuestionService.create_question(draft)
       -> QuestionValidator.validate(draft)                    [R3]
       -> QuestionRepository.save(draft)                       [R1]
       -> DifficultyService.analyze_silent(saved)
            -> AIClient.complete(prompt)                       [R4]
            -> 失败 => 返回 PENDING，不阻塞入库
```

### 4.2 组卷链

```text
PaperGenerationView
  -> PaperComposer.generate(criteria)
       -> _validate_criteria(criteria)                         [R7]
       -> QuestionRepository.search(filter)                    [R6/R8-1]
       -> UsageRepository.get_many(ids)                        [R13]
       -> SelectionScorer.score(candidates, ctx)
            -> CooldownPolicy.recency_penalty / use_count_penalty
       -> WeightedSampler.sample(scored, k)                    [R9]
       -> [不足] QuestionGenerator.generate_questions(...)      [R10]
            -> AIClient.complete(prompt, schema)
            -> QuestionValidator.validate(生成题)               [R10-4]
            -> QuestionRepository.save(AI 题, source=ai)
       -> UsageRepository.record_usage(selected, now)          [R13-1]
       -> ScoreCalculator.total_score(paper)                   [R11]
       -> TaskHistoryService.save_task(task)                   [R14]
```

### 4.3 导出链

```text
PaperGenerationView
  -> PaperExporter.export(paper, fmt, target_dir)
       -> ScoreValidator.validate(paper)                       [R11-4]
       -> BaseExporter.export(paper, target_dir, options)      [R12]
            TxtExporter  标准库渲染
            PdfExporter  reportlab 渲染（惰性导入）
```

## 5. 数据表与接口的对应

| 表 | 读写接口 | 说明 |
|----|----------|------|
| questions | QuestionRepository | 题目主表 |
| knowledge_points | QuestionRepository（save/update 同步） | 知识点字典 |
| question_usage | UsageRepository | 使用记录（R13） |
| generation_tasks | TaskRepository | 组卷任务 |
| task_exports | TaskRepository（save_task 一并写入） | 导出记录 |
| settings | ConfigStore | AI / 评分 / 提示词 / 科目配置（JSON 键值） |
| question_operations | QuestionOpRepository | 题库操作台账（导入历史 / 编辑历史） |
