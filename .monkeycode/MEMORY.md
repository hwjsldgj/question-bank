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

[Project Knowledge Summary]
- Date: 2026-10-04
- Context: 实现"AI 辨识模块化提示词 / 保存导入逐项检查 / 组卷指定知识点"并验证时发现
- Category: Testing Methods | Troubleshooting & Debugging | Environment Configuration
- Instructions:
  - 本机环境无 pytest、无 PySide6：`python3 -m pytest tests/` 无法直接运行；可用工作区内
    带最小 `pytest` shim（fixture / raises / importorskip）的临时脚本跑 tests/ 中不依赖
    PySide6 的用例，GUI 用例（tests/test_presentation_smoke.py）会因缺 PySide6 整模块跳过
  - 验证顺序建议：`python -m compileall -q app tests main.py` + 工作区临时脚本（用后即删）
  - 不要用 `tempfile.TemporaryDirectory()` 写临时库：它会 chmod 0o700，在本机沙箱下目录
    会变成不可读也不可删（连 `cmd rmdir` / `icacls` 都被拒），临时目录统一用 pytest 的
    `tmp_path` fixture
  - 临时验证目录放在工作区内的 `_tmp_*` 子目录并在脚本结束时删除，不要用系统 %TEMP%
  - 删除工作区内的临时目录可能需要一次完全权限（danger-full-access）批准，工作区根上的
    Everyone 拒绝项是沙箱预期设置，不要手工改 ACL
