# User Instruction Memory

This file records user instructions, preferences, and teachings for reference in future interactions.

## Format

### User Instruction Entry
User instruction entries should follow this format:

[User Instruction Summary]
- Date: [YYYY-MM-DD]
- Context: [Mentioned scenario or time]
- Instructions:
  - [Content of user teaching or instruction, described line by line]

### Project Knowledge Entry
Entries discovered by the Agent during task execution should follow this format:

[Project Knowledge Summary]
- Date: [YYYY-MM-DD]
- Context: Discovered by Agent while performing [specific task description]
- Category: [Operations & Deployment|Build Methods|Testing Methods|Troubleshooting & Debugging|Workflow & Collaboration|Environment Configuration]
- Instructions:
  - [Specific knowledge points, described line by line]

## Deduplication Strategy
- Before adding a new entry, check for similar or identical instructions.
- If a duplicate is found, skip the new entry or merge it with the existing one.
- When merging, update the context or date information.
- This helps avoid redundant entries and keeps the memory file tidy.

## Entries

[User Instruction Summary]
- Date: 2026-10-03
- Context: 用户委托搭建"自动出题与组卷工具"项目框架时明确要求
- Instructions:
  - 完成开发任务后必须提交 git（用户原话："记得提交 git"）
  - 代码必须采用分层架构、模块化结构（presentation -> application -> interfaces <- infrastructure，domain 为最底层）
  - 每个模块必须有完整注释说明其作用；依赖关系与接口定义/调用需有专门文档（docs/DEPENDENCIES.md、docs/INTERFACES.md）
  - 业务方法用 `raise NotImplementedError("TODO(需求编号)")` 标注占位，通过全库检索 `TODO(` 定位待办

[Project Knowledge Summary]
- Date: 2026-10-03
- Context: 搭建 question-paper-generator 框架并运行冒烟测试时验证
- Category: Build Methods | Testing Methods
- Instructions:
  - 测试命令：`python3 -m pytest tests/ -q`（冒烟测试 6 项已启用，专项用例以 pytest.mark.skip 占位）
  - 语法检查：`python3 -m compileall -q app main.py tests`
  - 依赖安装需用 `pip3 install --break-system-packages`；PySide6 体积大，前台安装易超时，应使用后台终端安装
  - GUI 冒烟可用 `QT_QPA_PLATFORM=offscreen` 无显示环境验证主窗口装配
  - 需求与设计文档位于 `.monkeycode/specs/question-paper-generator/`（requirements.md / design.md），需求编号 R1-R18 与代码 TODO 标注一一对应
