# 自动出题与组卷工具（question-paper-generator）

面向教师与培训人员的桌面端自动出题与组卷工具：手工建库（选择题 + 解答题）、
AI API 自动标注难度（易/中/难）、按"评分决策 + 加权随机"选题
（近期重复抑制）、导出 TXT / PDF 试卷（卷末附答案页）。

- 需求文档：`.monkeycode/specs/question-paper-generator/requirements.md`
- 技术设计：`.monkeycode/specs/question-paper-generator/design.md`
- 架构说明：`docs/ARCHITECTURE.md`
- 依赖关系：`docs/DEPENDENCIES.md`
- 接口文档：`docs/INTERFACES.md`

## 功能特性

- 题库管理：单选 / 多选 / 解答题的手工录入、批量粘贴、检索与质量标记
- AI 难度分析：OpenAI 兼容 API，失败自动降级为"待确认"
- 组卷引擎：选择题部分与解答题部分均可选；题库优先、AI 补题兜底
- 选题算法：难度匹配 / 知识点覆盖 / 使用频次 / 最近使用 / 人工质量
  五因子评分决策，再按评分加权随机抽样
- 近期重复抑制：使用记录 + 冷却窗口，最近用过的题目尽量少出现
- 试卷导出：TXT / PDF，按部分与题型分区、含小计与总分、卷末答案页

## 目录结构

```text
app/
├── domain/          领域层：实体、枚举、校验器（零外部依赖）
├── interfaces/      接口层：仓储 / AI 客户端 / 导出器抽象（端口）
├── application/     应用服务层：评分、抽样、组卷编排等用例
├── infrastructure/  基础设施层：SQLite 仓储、AI 客户端、TXT/PDF 导出
├── presentation/    表现层：PySide6 主窗口与三个视图
├── config/          默认配置（评分权重 / 冷却窗口 / AI 参数）
└── container.py     组合根：装配完整对象图
main.py              程序入口
docs/                架构 / 依赖 / 接口文档
tests/               冒烟测试（含表现层离屏测试）与专项用例骨架
```

分层依赖方向与强制规则见 `docs/ARCHITECTURE.md`。

## 快速开始

```bash
# 安装依赖（含桌面 GUI、PDF 渲染、AI 访问与测试框架）
pip install -r requirements.txt

# 启动桌面应用
python main.py

# 运行测试
python -m pytest tests/ -v
```

首次启动自动在本地创建 `question_bank.db`（SQLite，需求 R18：数据仅存本机）。
AI 功能需在"历史与设置"页配置 API 地址、Key 与模型名称；未配置时
题库管理与库内组卷仍可正常使用。

## 当前状态：表现层完成，业务待实现

分层架构、接口契约、组合根装配、数据表结构与**完整 GUI**（主窗口 + 三视图）
已完成；业务方法仍以 `raise NotImplementedError("TODO(需求编号)")` 标注。
界面已按需求 R1-R15 完成表单、列表、信号与交互，并通过 `ui_utils.run_guarded`
统一捕获"尚未实现"的服务调用并给出可读提示，因此界面可正常演示、不会崩溃。
实现业务时全库检索 `TODO(` 即可定位待办，各方法的职责与协作对象见
`docs/INTERFACES.md`。

| 层 | 完成情况 |
|----|----------|
| domain（实体 / 枚举 / 异常） | 完成 |
| interfaces（六个抽象接口） | 完成 |
| container 组合根装配 | 完成 |
| infrastructure（连接 / 建表 / 配置存取） | 完成（框架管道） |
| infrastructure（仓储 CRUD / AI / 导出渲染） | 骨架 + TODO |
| application（全部服务） | 骨架 + TODO |
| presentation（主窗口 / 三视图 / 共享工具） | 完成（界面 + 信号；业务调用经服务层） |
| tests（冒烟） | 通过 |
| tests（评分 / 抽样 / 组卷等专项） | 用例规划就绪，待业务实现后启用 |
