"""表现层共享工具：枚举标签、统一对话框与受限服务调用。

集中封装界面层的重复逻辑，供主窗口与三个视图复用：

- 枚举 -> 中文标签映射（下拉框、表格展示统一口径）
- 领域异常 / 未实现占位的统一提示。框架阶段应用服务多为
  ``raise NotImplementedError("TODO(...)")``，界面必须捕获后给出可读提示，
  避免尚未实现的业务导致程序崩溃
- 耗时操作期间的等待光标（需求 R17 第 3 条：展示进行中状态）

依赖：PySide6.QtCore、PySide6.QtWidgets、app.domain.enums、app.domain.errors
被使用：app.presentation.main_window、app.presentation.views.question_bank_view、
        app.presentation.views.paper_generation_view、
        app.presentation.views.history_view、app.presentation.views.settings_view
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QMessageBox, QWidget

from app.domain.enums import (
    Difficulty,
    ExportFormat,
    QualityFlag,
    QuestionOpAction,
    QuestionSource,
    QuestionType,
    SectionKind,
)
from app.domain.errors import DomainError

#: 题型 -> 中文标签
QUESTION_TYPE_LABELS: dict[QuestionType, str] = {
    QuestionType.SINGLE: "单选题",
    QuestionType.MULTIPLE: "多选题",
    QuestionType.SOLUTION: "解答题",
}

#: 难度 -> 中文标签
DIFFICULTY_LABELS: dict[Difficulty, str] = {
    Difficulty.EASY: "易",
    Difficulty.MEDIUM: "中",
    Difficulty.HARD: "难",
    Difficulty.PENDING: "待确认",
}

#: 质量标记 -> 中文标签
QUALITY_LABELS: dict[QualityFlag, str] = {
    QualityFlag.NORMAL: "普通",
    QualityFlag.QUALITY: "优质",
    QualityFlag.LOW: "低质",
}

#: 题目来源 -> 中文标签
SOURCE_LABELS: dict[QuestionSource, str] = {
    QuestionSource.BANK: "题库",
    QuestionSource.AI: "AI 生成",
}

#: 试卷分区 -> 中文标签
SECTION_LABELS: dict[SectionKind, str] = {
    SectionKind.CHOICE: "选择题部分",
    SectionKind.SOLUTION: "解答题部分",
}

#: 导出格式 -> 中文标签
EXPORT_FORMAT_LABELS: dict[ExportFormat, str] = {
    ExportFormat.TXT: "TXT 文本",
    ExportFormat.PDF: "PDF 文档",
}

#: 题库操作类型 -> 中文标签（导入历史 / 编辑历史）
OP_ACTION_LABELS: dict[QuestionOpAction, str] = {
    QuestionOpAction.CREATE: "录入",
    QuestionOpAction.UPDATE: "编辑",
    QuestionOpAction.DELETE: "删除",
    QuestionOpAction.IMPORT: "导入",
}


def info(parent: QWidget, text: str, title: str = "提示") -> None:
    """信息提示对话框。"""
    QMessageBox.information(parent, title, text)


def warning(parent: QWidget, text: str, title: str = "无法继续") -> None:
    """警告提示对话框（领域校验失败等）。"""
    QMessageBox.warning(parent, title, text)


def critical(parent: QWidget, text: str, title: str = "错误") -> None:
    """错误提示对话框（未预期的异常）。"""
    QMessageBox.critical(parent, title, text)


def confirm(parent: QWidget, text: str, title: str = "请确认") -> bool:
    """是 / 否确认框，默认选中"否"（避免误操作，需求 R1 删除等场景）。"""
    answer = QMessageBox.question(
        parent,
        title,
        text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


def run_guarded(
    parent: QWidget,
    func: Callable[..., Any],
    *args: Any,
    success_message: str | None = None,
    **kwargs: Any,
) -> tuple[bool, Any]:
    """调用服务方法并统一处理异常（界面层的安全调用入口）。

    - ``NotImplementedError``：框架占位方法，提示"功能尚未实现"
    - ``DomainError``：业务校验失败，展示原始可读消息
    - 其他异常：展示统一错误，保证界面不崩溃

    调用期间显示等待光标并刷新事件循环，满足"进行中状态"要求（R17-3）。

    :return: ``(是否成功, 返回值)``；失败时返回值为 ``None``。
    """
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    QApplication.processEvents()
    result: Any = None
    error: Exception | None = None
    try:
        result = func(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - 界面兜底，避免异常上抛导致崩溃
        error = exc
    finally:
        QApplication.restoreOverrideCursor()

    if error is not None:
        if isinstance(error, NotImplementedError):
            info(parent, f"该功能尚未实现（框架占位）。\n\n{error}")
        elif isinstance(error, DomainError):
            warning(parent, str(error))
        else:
            critical(parent, f"操作失败：{error}")
        return False, None

    if success_message:
        info(parent, success_message)
    return True, result


def safe_call(
    func: Callable[..., Any],
    *args: Any,
    default: Any = None,
    **kwargs: Any,
) -> Any:
    """静默调用：失败返回 ``default`` 且不弹窗。

    用于命中量统计、历史加载、配置读取等非关键展示，避免框架阶段
    反复弹出"尚未实现"提示干扰界面初始化。
    """
    try:
        return func(*args, **kwargs)
    except Exception:  # noqa: BLE001 - 静默降级
        return default


def select_combo_data(combo: QComboBox, value: Any) -> None:
    """按 ``itemData`` 选中下拉项；未找到时保持当前选择。

    使用显式循环而非 ``findData``，确保自定义枚举对象比较可靠。
    """
    for index in range(combo.count()):
        if combo.itemData(index) == value:
            combo.setCurrentIndex(index)
            return
