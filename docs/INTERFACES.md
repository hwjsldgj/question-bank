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
    def count_available(self, subject: str, difficulty: str, question_type: str,
                        knowledge_points: list[str] | None = None,
                        section: str | None = None) -> int
    def list_knowledge_points(self, subject: str | None = None) -> list[str]
    def count_by_type(self) -> dict[str, int]
    def count_by_image(self, image_path: str) -> int
```

| 项 | 说明 |
|----|------|
| 实现 | `infrastructure/repositories/question_repository.py::SQLiteQuestionRepository` |
| 调用方 | `application/question_service`、`application/paper_composer`、`application/question_generator` |
| 语义 | save 分配唯一 id (R1)；update 保留 id 与使用记录 (R1)；search 按 QuestionFilter 组合过滤 (R6)；count_available 的 `knowledge_points` 非空时按"命中任一指定知识点"统计，`section` 非空时按知识点板块过滤（可多个板块，命中任一即计入；用户需求：组卷可指定知识点与知识点板块） |
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
    def load_prompt_config(self) -> PromptConfig      # AI 提示词（总述 + 各模块，用户可改）
    def save_prompt_config(self, config: PromptConfig) -> None
    def load_subjects(self) -> list[str]              # 科目列表（选择式录入）
    def save_subjects(self, subjects: list[str]) -> None
    def load_sections(self) -> list[KnowledgeSection]   # 知识点板块列表（无配置时回退默认）
    def save_sections(self, sections: list[KnowledgeSection]) -> None
```

| 项 | 说明 |
|----|------|
| 实现 | `infrastructure/config_store.py::SQLiteConfigStore`（settings 键值表，JSON 值） |
| 调用方 | `app/container.py`（装配）、`presentation/views/settings_view`、`application/{question_service,difficulty_service}`（提示词与科目） |
| 语义 | 无记录 / 解析失败回退 `config/settings.py` 默认值；提示词为空时逐项回退默认模板；`PromptConfig.module_prompts` 按模块逐项合并（只改了部分模块时，其余模块仍用默认片段）；科目列表去重且保序，为空时回退默认科目；知识点板块映射按科目逐板块去重保序，无配置时回退默认板块 |
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
    def export(self, paper: Paper, target_dir: str | None = None,
               options: ExportOptions | None = None) -> str
```

| 项 | 说明 |
|----|------|
| 实现 | `infrastructure/exporters/md_exporter.py::MdExporter`（Markdown 源文件）、`infrastructure/exporters/pdf_exporter.py::PdfExporter`（由该 MD 用 pymd2pdf 转 PDF） |
| 调用方 | `application/paper_exporter`（按 ExportFormat 路由） |
| 语义 | 返回生成文件路径；排版契约：两部分分区 / 题型大题 / 小计与总分 / 卷末答案页 (R12)；`target_dir` 为 None 时写入工作区根目录下的固定导出目录（程序自建，用户不再指定） |
| 异常 | `ExportError`：目录不可写 / 渲染依赖缺失（PDF 缺 pymd2pdf 时提示改用 MD，R18-4） |

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

### 1.9 组卷条件值对象（R7 / 用户需求）

```python
@dataclass
class TypeRequirement:              # domain/entities/criteria.py
    question_type: QuestionType
    subject: str
    difficulty: Difficulty
    count: int
    knowledge_points: list[str] = field(default_factory=list)   # 组卷指定知识点
    section: str = ""                                           # 组卷指定知识点板块（可多个，不限为空）

@dataclass
class PaperCriteria:
    choice_enabled: bool
    solution_enabled: bool
    fill_enabled: bool
    choice_items: list[TypeRequirement]
    fill_items: list[TypeRequirement]
    solution_items: list[TypeRequirement]
    subject: str = ""                                          # 全局单科目
    def enabled_requirements(self) -> list[TypeRequirement]     # 顺序：选择 -> 填空 -> 解答
```

- 每类题型可配置多条要求（界面按"知识点板块 / 知识点 × 难度"逐行配置题数），
  组卷时同题型的多条要求合并为一个分区，同卷按题目 id 去重。
- `knowledge_points` 为空表示不限；非空时命中其中任一知识点的题目才计入命中量与选题
  （用户需求：组卷环节可指定知识点）。
- `section` 为空表示不限；非空时只统计 / 选取命中该板块的题目。一道题可属于多个板块
  （`Question.section` 用"、"分隔，如 `代数、几何`），板块可写多个（用逗号 / 顿号分隔），
  命中其中任一板块即计入；界面按所选板块过滤知识点候选
  （用户需求：组卷可选知识点板块作为限定）。
- 界面在每个题型分组内保留原条件控件（知识点板块 / 知识点 / 难度 / 数量 / 命中量），
  其中知识点板块与知识点是标签输入框（`ui_utils.TagInput`）：输入即给候选标签，
  选中或回车加入已选，标签平级、可叠加、可删除且为并列筛选（命中任一即匹配）；
  候选只随当前输入刷新，已选标签不影响候选；下面追加该题型的配置表
  （序号 / 题型 / 知识点板块 / 知识点 / 难度 / 数量 / 命中题数）：
  "添加到配置表"把当前条件追加为一行，可改难度、改数量、删除行；
  数量为 0 的行不参与组卷与配比统计。

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
def count_available(self, subject: str, difficulty: Difficulty, question_type: QuestionType,
                    knowledge_points: list[str] | None = None) -> int
        # knowledge_points 非空时只统计命中其中任一知识点的题目（用户需求：组卷可指定知识点）
# 用户需求追加：
def list_subjects(self) -> list[str]                     # 可选科目（设置中维护）
def list_knowledge_points(self, subject: str | None = None) -> list[str]
        # 知识点字典，供录入 / 检索自动补全与组卷指定知识点
def list_sections(self, subject: str | None = None) -> dict[str, list[str]]
        # {板块 -> 细分知识点列表}，subject 为空时合并全部科目；
        # 录入页按科目联动板块、按板块过滤知识点候选
def statistics(self) -> dict[str, int]                   # 题库概览：总题数与各题型题量
def delete_questions(self, question_ids: list[str]) -> int       # 批量删除
def set_quality_flag_many(self, question_ids: list[str], flag: QualityFlag) -> int
def reanalyze_difficulties(self, question_ids: list[str], confirmed: bool = False) -> dict
def all_question_ids(self) -> list[str]
def ai_configured(self) -> bool                          # AI 是否已配置（决定按钮可用性）
def recognize_draft(self, stem: str, options: list[Option],
                    include_solution: bool = True, confirmed: bool = False,
                    modules: list[RecognizeModule] | list[str] | None = None) -> dict
        # 模块化输出：只把 modules 指明的模块（科目 / 知识点 / 题型 / 难度 / 质量 /
        # 答案 / 解析）拼进提示词与期望结构，一次调用返回全部所需字段；
        # 未请求的字段不出现在结果里；include_solution=False 时提示词与期望结构
        # 均不含解析且结果 solution 恒为空串（用户需求：按需给出、一次返回）
        # 返回键仅含被请求模块对应的键
def recognize_draft_report(self, stem, options, include_solution=True,
                           confirmed=False, modules=None) -> RecognitionReport
        # 同 recognize_draft，但额外返回"AI 返回内容的问题清单"：
        # RecognitionReport(fields: dict, issues: list[str])（用户需求：返回信息有问题
        # 时弹窗提示）；无法识别的字段不写入 fields，避免静默套用默认值
@staticmethod module_states(question) -> list[tuple[RecognizeModule, bool]]
        # 逐项检查各模块是否已填写（题干与选项不在其中，须人工填写）
@classmethod missing_modules(question) -> list[RecognizeModule]
@classmethod required_missing_modules(question) -> list[RecognizeModule]   # 科目 / 知识点 / 答案
@staticmethod apply_recognition(question, result, include_solution=True) -> Question
        # 把 AI 结果写回题目草稿（批量导入场景）
        # 保存 / 导入前的逐项检查与 AI 填充均基于以上方法（用户需求）
def list_operations(self, actions=None, limit=None) -> list[QuestionOpRecord]
        # 导入历史 / 编辑历史台账
```

**模块化 AI 辨识（用户需求）**：`RecognizeModule`（`app/domain/enums.py`）定义
`subject / knowledge_points / question_type / difficulty / quality_flag / answer / solution`
七个模块；`app/config/settings.py` 的 `DEFAULT_MODULE_PROMPTS` 为每个模块提供一段默认输出
提示词，用户可在「设置 -> AI 设置」中逐模块修改（`PromptConfig.module_prompts`），
总述模板 `PromptConfig.recognize_prompt` 用 `{modules}` 占位符接收被勾选模块的拼装结果。
界面上勾选模块 -> 一次 AI 调用 -> 只回填勾选的字段。
自定义总述未使用 `{modules}` 时，服务层只追加"总述里还没提到"的模块要求，
避免同一字段（如难度）在提示词里出现两次。

**知识点板块分级提示词（用户需求）**：`module_prompts["knowledge_points"]` 不再笼统要求
"知识点数组"，而是要求 AI 先判断题目涉及哪些知识点板块（只从
`DEFAULT_KNOWLEDGE_SECTIONS` / 用户配置的板块列表里选，可涉及多个板块），
再对每个板块细化到细分知识点，输出 `{"板块名": ["细分知识点", ...]}` 对象。
服务层 `_format_sections_for_prompt()` 把"科目-板块-知识点"扁平为
"板块名：细分知识点"清单填入 `{sections}`；`_flatten_sectioned_points()` 把
AI 返回的分级结构扁平为知识点列表并提取所属板块（多板块用"、"拼接），
写入 `Question.section` 与 `Question.knowledge_points`。

**难度提示词只维护一处（用户需求）**：`PromptConfig` 不再有 `difficulty_prompt` 字段
（旧配置里的该键在读取时被忽略）。`module_prompts["difficulty"]` 既用于 AI 辨识的难度
字段，也由 `DifficultyService.analyze` 作为难度分析的输出要求——框架常量
`app/config/settings.py::DIFFICULTY_ANALYSIS_FRAME` 负责补上 `{type} {stem} {options}
{answer}` 等题目信息，因此设置界面只有一个「难度」提示词编辑框。

**AI 返回内容问题的弹窗约定（用户需求）**：`recognize_draft_report().issues` 收集
"AI 未返回 X"、"AI 返回的难度无法识别：'…'"、"AI 建议的科目不在科目列表中"等问题，
界面统一弹窗提示（批量导入时按题汇总为一次弹窗）；无法识别的取值不会写回表单。
`DifficultyService` 遇到无法识别的难度抛 `AIServiceError`（经 `run_guarded` 弹窗提示）。

**逐项检查约定（用户需求）**：保存题目与批量导入前，界面用
`QuestionService.module_states()` 逐项列出各模块的填写状态，弹窗询问是否让 AI 填充
缺失项（「AI 填充缺失项 / 手动补齐（跳过 AI）/ 取消」）；题干与选项必须由出题者填写。
批量粘贴在「解析预览」时先行检查并可当场让 AI 填充（`_import_checked` 记录已询问过，
「确认提交」只在必填项仍缺失时阻断）；保存题目则在点击保存时检查。
科目 / 知识点 / 答案为必填模块（`REQUIRED_MODULES`），难度 / 解析 / 质量标记缺失时允许
直接保存。

**AI 确认约定（用户需求）**：所有会调用 AI 的方法都必须显式确认，未确认时拒绝执行：

```text
create_question(draft, analyze_difficulty=False)      # True 才调用 AI 分析难度
update_question(id, patch, analyze_difficulty=False)
batch_commit(drafts, analyze_difficulty=False)
recognize_draft(stem, options, include_solution=True, confirmed=False, modules=None)  # True 才调用 AI
recognize_draft_report(同左, ...)                     # 同上，并返回问题清单供弹窗
reanalyze_difficulties(ids, confirmed=False)                             # True 才调用 AI
PaperComposer.generate(criteria, allow_ai_supplement=False)               # True 才允许 AI 补题
QuestionGenerator.generate_questions(..., allow_ai=False)                 # True 才调用 AI
```

界面在每次 AI 动作前弹出确认框（「AI 分析 / AI 辨识 / AI 填充缺失项 / 允许 AI 补题 / 跳过」），
用户确认后才传对应标志；拒绝时不发起任何 AI 请求。
批量导入时逐题逐项检查后一次性确认，随后每题各调用一次 AI（每次只请求该题缺失的模块）。

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

def export(self, paper: Paper, fmt: ExportFormat, target_dir: str | None = None,
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
PaperGenerationView（导出目录固定为工作区根目录下的导出文件夹，程序自建）
  -> PaperExporter.export(paper, fmt, target_dir=None)
       -> ScoreValidator.validate(paper)                       [R11-4]
       -> BaseExporter.export(paper, target_dir, options)      [R12]
            MdExporter   标准库渲染 Markdown 源文件（.md）
            PdfExporter  先由 MdExporter 产出同名 .md，
                         再用 pymd2pdf 转成同名 .pdf（惰性导入）
```

## 5. 数据表与接口的对应

| 表 | 读写接口 | 说明 |
|----|----------|------|
| questions | QuestionRepository | 题目主表（section 列为后加字段，旧库自动补列） |
| knowledge_points | QuestionRepository（save/update 同步） | 知识点字典 |
| question_usage | UsageRepository | 使用记录（R13） |
| generation_tasks | TaskRepository | 组卷任务 |
| task_exports | TaskRepository（save_task 一并写入） | 导出记录 |
| settings | ConfigStore | AI / 评分 / 提示词 / 科目配置（JSON 键值） |
| question_operations | QuestionOpRepository | 题库操作台账（导入历史 / 编辑历史） |
