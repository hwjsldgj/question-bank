# AGENTS.md

给 AI 的入口笔记。**先读完这份，再改代码**。

## 必读文档

1. `docs/ARCHITECTURE.md` — 分层、依赖方向、核心流程、关键设计决策
2. `docs/INTERFACES.md` — 所有端口签名、实现、调用方
3. `docs/DEPENDENCIES.md` — 文件级依赖关系
4. `待完成工作.md` — 未完成项

## 跑起来

python main.py              # GUI（先 splash，再主窗口）
python -m pytest tests/ -q  # 测试

`main.py`：`build_container()` → 建表/迁移 → `MainWindow`。

## 环境常量（`app/config/settings.py`）

| 常量 | 用途 |
|---|---|
| `DEFAULT_DB_PATH` | `question_bank.db`（项目根）|
| `DEFAULT_IMAGE_DIR` | `images/`（题库图片，相对 db）|
| `TYPST_EXE` | Typst 编译器绝对路径 |
| `TYPST_GAOKAO_ROOT` | 原始 `.typ` 真题目录 |
| `EXPORT_FIGURES_DIR` | `exports/figures` |
| `DEFAULT_PDF_BROWSER_PATHS` | Edge 可执行文件候选 |
| `DEFAULT_SCORING_CONFIG` | 评分权重默认值 |

## 分层速查（详见 ARCHITECTURE.md）

presentation  → 只调 application
application   → 只依赖 domain + interfaces（不能 import infrastructure）
infrastructure → 实现 interfaces，依赖 domain + config
domain        → 零外部依赖
container.py  → 唯一能 import 具体实现的地方（组合根）

**违反依赖方向 = 架构破坏**。

## 端口（interfaces/）

| 端口 | 实现 | 谁调 |
|---|---|---|
| `QuestionRepository` | SQLiteQuestionRepository | QuestionService / PaperComposer / QuestionGenerator |
| `UsageRepository` | SQLiteUsageRepository | PaperComposer（写）/ SelectionScorer（读）|
| `TaskRepository` | SQLiteTaskRepository | TaskHistoryService |
| `QuestionOpRepository` | SQLiteQuestionOpRepository | QuestionService（写）/ QuestionHistoryService（读）|
| `ConfigStore` | SQLiteConfigStore | container / SettingsView / QuestionService / DifficultyService |
| `AIClient` | OpenAICompatibleAIClient | DifficultyService / QuestionGenerator |
| `BaseExporter` | MdExporter / PdfExporter | PaperExporter |

`LocalImageStore`（`infrastructure/image_store.py`）不是 ABC，是直接注入的具体类。

## 应用服务分工（application/）

| 服务 | 职责 |
|---|---|
| `QuestionService` | 题库 CRUD / 批量粘贴解析 / 检索统计 / AI 辨识 / 台账记录 |
| `QuestionHistoryService` | 导入历史 / 编辑历史 |
| `DifficultyService` | AI 难度分析 / 批量重析 |
| `CooldownPolicy` | 冷却窗口惩罚 |
| `SelectionScorer` | 选题评分（难度 / 知识点 / 质量 / 频次 / 近期）|
| `WeightedSampler` | 加权随机抽样 |
| `QuestionGenerator` | AI 补题 |
| `PaperComposer` | 组卷总编排 |
| `ScoreCalculator` | 分值 / 总分计算 |
| `PaperExporter` | 按格式分发导出 |
| `TaskHistoryService` | 组卷历史与配置复用 |
| `paper_import.py` | 从 `.typ` 源码解析出 Question 草稿 |

## 本地 AI 模型

| 模型 | 位置 | 用法 |
|---|---|---|
| 难度分类 | `models/difficulty_model/` | 懒加载，CPU 单题 < 1 秒 |
| 知识点分类 | 待接入 | 见待办 |

- 启动**不预热**（首次调用加载）
- 加载代理：`app/infrastructure/ai/lazy_local_classifier.py`
- 分类器：`app/infrastructure/ai/local_difficulty_classifier.py`
- 调试 tab 可开关：禁用本地 / 禁用 API / 禁用全部 AI

## 数据库 schema

表 `questions` 关键字段：

| 字段 | 说明 |
|---|---|
| `id` | 主键，形如 `2026_上海春季卷_q00013`（q 路径）或 `2016_上海卷文科_fig00012`（fig 路径）|
| `subject` | 科目 |
| `section` | 知识点板块，多板块用"、"分隔 |
| `knowledge_points` | 细分知识点（JSON 数组）|
| `type` | `single` / `multiple` / `fill` / `solution` |
| `stem` / `options` / `answer` / `solution` | 题干 / 选项 JSON / 答案 JSON / 解析 |
| `difficulty` | `easy` / `medium` / `hard` / `pending` |
| `difficulty_source` | `ai` / `manual` |
| `quality_flag` | `normal` / 其它 |
| `typst_source` | 含图题的 Typst 源码（**仅 `_fig` 路径有**）|
| `image_path` | 手工导入的图片相对路径 |

⚠️ **`_q` 路径不提取 `typst_source`** —— 见待办。

## 典型工作流

### 改一处渲染规则

1. 找 `md_exporter.py::_ttl_conv_math`（**注意有 2 处，改最后一个**）
2. `python -m py_compile app/infrastructure/exporters/md_exporter.py`
3. **完全关闭 GUI**（任务管理器确认 python.exe 退出）
4. `python main.py` 重启
5. 导出 PDF 验证
6. 全库扫描确认残留 = 0

### 写一个数据修复脚本

1. 参考 `scripts/repair_missing_typst_source.py`
2. 备份 db（`Copy-Item question_bank.db question_bank_backup_YYYYMMDD.db`）
3. 脚本先扫后改，打印"需修复 N 条"
4. 改完再扫一次，确认 0
5. 脚本入库（db 不在 git，脚本可重放）

### 改 UI

1. `app/presentation/views/` 下对应视图
2. UI 通过 `ui_utils.run_guarded` / `safe_call` 调服务
3. 用 `ui_utils.make_rows_compact` 统一表格样式

## 测试

`pytest tests/ -q`。有历史遗留失败（见 `待完成工作.md` 的"立即做"），不是近期改动引入的。

## 导出产物结构

exports/
├── 试卷_YYYYMMDD_HHMMSS.pdf   # 最终产物
└── figures/
    ├── g_<题1>_<题2>.png       # 相邻含图题合并
    ├── <题id>.png              # 单题题干图
    └── <题id>__optA.png        # 选项图（A/B/C/D 分开）

MD 中间产物默认删（调试 tab 可保留）。导出目录由程序指定。

## 关键位置

| 改什么 | 去哪 |
|---|---|
| 导出渲染（Typst→LaTeX）| `app/infrastructure/exporters/md_exporter.py` |
| Typst 图渲染 PNG | `app/infrastructure/exporters/typst_renderer.py` |
| PDF 生成（HTML / MathJax / CSS）| `app/infrastructure/exporters/pdf_exporter.py` |
| 组卷算法 / 去重 | `app/application/paper_composer.py` |
| 评分因子 | `app/application/selection_scorer.py` |
| 数据模型 / 表结构 | `app/infrastructure/database/schema.py` |
| 导入 .typ 解析 | `app/application/paper_import.py` |
| GUI 组卷页 | `app/presentation/views/paper_generation_view.py` |
| GUI 题库页 | `app/presentation/views/question_bank_view.py` |
| 数据修复脚本 | `scripts/repair_missing_typst_source.py` |

## 业务概念

- **科目**：全局单科目（高考数学）
- **知识点三级**：科目 → 板块 → 细分知识点；`Question.section` 存板块（"、" 分隔多个），`Question.knowledge_points` 存细分
- **题型**：`QuestionType`（SINGLE / MULTIPLE / FILL / SOLUTION）
- **难度**：`Difficulty`（EASY / MEDIUM / HARD / PENDING）；`difficulty_source` 区分 ai / manual
- **组卷条件**：`PaperCriteria`（每题型多条 `TypeRequirement`）；同题型多条合并成一分区，全卷去重
- **AI 调用**：全部需用户确认（`confirmed=True`）；返回有 `issues` 时弹窗

## 数据

- SQLite `question_bank.db`（**不在 git 里**，`*.db` 被忽略）
- **数据库改动必须写成 `scripts/*.py` 脚本**（可重放）

## 改代码后必做

1. `python -m py_compile <改的文件>`
2. **完全关闭 GUI 再重开**（Python 不热加载）
3. 遇到怪问题先删 `__pycache__`

## 已知坑

1. **`md_exporter.py` 有 2 处 `_ttl_conv_math` 定义**，**最后一个生效**
2. **`_HTML_TEMPLATE` 的 `{}`** 必须写成 `{{ }}`，否则 `.format(body=body)` 报 KeyError
3. **PowerShell here-string 里的反斜杠**容易翻倍，改完必须 `py_compile`
4. **Typst 多页输出**：compile 命令需 `--pages 1`
5. **Typst 无关函数损坏会拖垮整份编译**：`_sanitize_typst_source` 只保留被 `#figure` 引用的 `#let`
6. **Typst 组合语法 `in.not` / `subset.not`** 要先于 `in` / `subset` 匹配
7. **数学里的 `*` 会被 Markdown 当强调**，需改成 `^{*}` 或 `\ast`
8. **MathJax SVG 输出斜体是字形路径**，CSS 覆盖不了——必须用 CHTML（`tex-chtml.js`）

## 渲染转换流程（改 md_exporter 前必读）

`typst_to_latex`：
1. 用 `\x00M{n}\x00` 保存 `$...$` 块
2. `$` 外：`_ttl_wrap_bare`
3. `$` 内：`_ttl_conv_math`
4. 还原 `$...$` 块

`_ttl_conv_math` 调用顺序（**顺序重要**）：
_ttl_normalize_unicode
→ _ttl_fix_coslr
→ _ttl_replace_func（frac / sqrt / root / abs / arrow / mat / cases ...）
→ _ttl_fix_subsup
→ _ttl_fix_multi_supsub_v3
→ _ttl_fix_asterisk
→ _ttl_apply_words（含 notin / therefore / quad glue 补丁）

## 提交约定

- commit message **中文**，格式：`类型(范围): 描述`
- 类型：`feat` / `fix` / `docs` / `chore` / `perf` / `refactor`
- 范围：`exporter` / `renderer` / `view` / `composer` / `scripts` 等

## 文档原则

- **不写会变的数字**（题数、行数、大小、通过数）
- 待完成工作只列未完成项
- 工作日志只记已完成
