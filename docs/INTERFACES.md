# 接口文档（INTERFACES）

Feature Name: question-paper-generator
Updated: 2026-10-18

本文给出全部抽象接口与服务类的**方法签名、参数与返回、异常、实现者与调用者**，以及关键调用链。

约定：
- 抽象接口位于 `app/interfaces/`，实现位于 `app/infrastructure/`，应用服务通过构造注入持有接口类型。
- 异常类型定义于 `app/domain/errors.py`。

## 1. 抽象接口（端口）

### 1.1 QuestionRepository —— 题目仓储

```python
class QuestionRepository(ABC):
    def save(self, question: Question) -> Question
    def get(self, question_id: str) -> Question | None
    def update(self, question: Question) -> Question
    def delete(self, question_id: str) -> None
    def search(self, question_filter: QuestionFilter) -> list[Question]
    def count_available(self, subject: str, difficulty: str, question_type: str, knowledge_points: list[str] | None = None, section: str | None = None) -> int
    def list_knowledge_points(self, subject: str | None = None) -> list[str]
    def count_by_type(self) -> dict[str, int]
    def count_by_image(self, image_path: str) -> int
```

| 项 | 说明 |
|----|------|
| 实现 | `SQLiteQuestionRepository` |
| 调用方 | `QuestionService`、`PaperComposer`、`QuestionGenerator` |
| 语义 | save 分配唯一 id；update 保留 id；search 组合过滤；`count_available` 支持多知识点、多板块过滤（命中任一即计入）。 |

### 1.2 UsageRepository —— 使用记录仓储

```python
class UsageRepository(ABC):
    def record_usage(self, question_ids: list[str], used_at: datetime) -> None
    def get(self, question_id: str) -> UsageRecord
    def get_many(self, question_ids: list[str]) -> dict[str, UsageRecord]
```

| 实现 | `SQLiteUsageRepository` |
| 调用方 | `PaperComposer`、`SelectionScorer` |

### 1.3 TaskRepository —— 组卷任务仓储

```python
class TaskRepository(ABC):
    def save_task(self, task: GenerationTask) -> None
    def get_task(self, task_id: str) -> GenerationTask | None
    def list_tasks(self) -> list[GenerationTask]
```

| 实现 | `SQLiteTaskRepository` |
| 调用方 | `TaskHistoryService` |

### 1.4 QuestionOpRepository —— 题库操作台账

```python
class QuestionOpRepository(ABC):
    def record(self, record: QuestionOpRecord) -> None
    def list_records(self, actions: list[str] | None = None, limit: int | None = None) -> list[QuestionOpRecord]
```

| 实现 | `SQLiteQuestionOpRepository` |
| 调用方 | `QuestionService`、`QuestionHistoryService` |

### 1.5 ConfigStore —— 配置存储

```python
class ConfigStore(ABC):
    def load_debug_config(self) -> DebugConfig
    def save_debug_config(self, config: DebugConfig) -> None
    def load_ai_config(self) -> AIConfig
    def save_ai_config(self, config: AIConfig) -> None
    def load_scoring_config(self) -> ScoringConfig
    def save_scoring_config(self, config: ScoringConfig) -> None
    def load_prompt_config(self) -> PromptConfig
    def save_prompt_config(self, config: PromptConfig) -> None
    def load_subjects(self) -> list[str]
    def save_subjects(self, subjects: list[str]) -> None
    def load_sections(self) -> list[KnowledgeSection]
    def save_sections(self, sections: list[KnowledgeSection]) -> None
```

| 实现 | `SQLiteConfigStore` |
| 调用方 | `container`、`SettingsView`、`QuestionService`、`DifficultyService` |

### 1.6 AIClient —— 云端 AI API 客户端

```python
class AIClient(ABC):
    def complete(self, prompt: str, response_schema: dict | None = None) -> dict
    def is_configured(self) -> bool
```

| 实现 | `OpenAICompatibleAIClient` |
| 调用方 | `DifficultyService`、`QuestionGenerator` |

### 1.7 ILocalAIEngine —— 本地四核 AI 推理引擎（新增）

```python
class ILocalAIEngine(ABC):
    def warm_up(self) -> None
    def predict_all(self, stem: str, options: str = "", answer: str = "") -> dict
```

| 项 | 说明 |
|----|------|
| 实现 | `LocalAIEngine` |
| 调用方 | `QuestionService`、`MainWindow` |
| 语义 | 延迟加载四大模型。`predict_all` 返回 `{"type", "section", "knowledge_points", "difficulty"}`，自带 80% 置信度阈值与规则兜底。 |

### 1.8 BaseExporter —— 试卷导出器

```python
class BaseExporter(ABC):
    def export(self, paper: Paper, target_dir: str | None = None, options: ExportOptions | None = None, progress: ProgressCallback | None = None) -> str
```

| 实现 | `MdExporter`、`PdfExporter` |
| 调用方 | `PaperExporter` |

---

## 2. 事件总线（表现层基础设施）

由于本地模型加载和网络调用是异步的，系统在表现层引入了 `SignalBus`（`app/presentation/signal_bus.py`）：
- `status_message = Signal(str)`：用于向主窗口左下角推送动态文本。
- 各组件（如 `LocalAIEngine` 的加载回调、UI 的后台推理线程）主动 `emit`，主窗口通过 `connect` 接收，实现状态解耦。

---

## 3. 应用服务公开方法摘要

### 3.1 QuestionService
| 方法 | 说明 |
|---|---|
| `create_question` | 校验 -> 落库 -> 本地或云端难度分析 |
| `update_question` | 更新题目，保留使用记录 |
| `batch_commit` | 批量导入，支持缺失字段拦截与 AI 识别 |
| `recognize_draft_report` | 云端 AI 模块化辨识，返回 `RecognitionReport(fields, issues)` |
| `recognize_draft` | （旧版保留）仅返回 fields |
| `list_operations` | 读取台账历史 |
| `ai_configured` | 云端 API 是否可用 |

### 3.2 PaperComposer
| 方法 | 说明 |
|---|---|
| `generate` | 条件校验 -> 检索 -> 评分（待实现） -> 抽样（待实现） -> 记录使用 -> 组卷 |

### 3.3 SelectionScorer（核心算法，待补全）
| 方法 | 说明 |
|---|---|
| `score` | 综合五因子打分（难度/覆盖/质量/频次/近期） |
| `difficulty_match_factor` | 难度匹配计算 |
| `knowledge_coverage_factor` | 知识点覆盖度计算 |
| `quality_factor` | 人工质量因子 |

### 3.4 DifficultyService
| 方法 | 说明 |
| --- | --- |
| `analyze` | 强制走云端或指定策略，返回 Difficulty |
| `analyze_silent` | 降级包装，失败返回 PENDING |
```

---

如果你不想手动复制，也可以直接跑下面这条命令，我帮你安全覆盖写入：

```powershell
[Console]::OutputEncoding = [Text.Encoding]::UTF8
cd E:\code\question-bank

@'
from pathlib import Path

content = '''# 接口文档（INTERFACES）

Feature Name: question-paper-generator
Updated: 2026-10-18

本文给出全部抽象接口与服务类的**方法签名、参数与返回、异常、实现者与调用者**，以及关键调用链。

约定：
- 抽象接口位于 `app/interfaces/`，实现位于 `app/infrastructure/`，应用服务通过构造注入持有接口类型。
- 异常类型定义于 `app/domain/errors.py`。

