"""表现层共享工具：枚举标签、统一对话框、多值输入控件与受限服务调用。

集中封装界面层的重复逻辑，供主窗口与三个视图复用：

- 枚举 -> 中文标签映射（下拉框、表格展示统一口径）
- 领域异常 / 未实现占位的统一提示。框架阶段应用服务多为
  ``raise NotImplementedError("TODO(...)")``，界面必须捕获后给出可读提示，
  避免尚未实现的业务导致程序崩溃
- 耗时操作期间的等待光标（需求 R17 第 3 条：展示进行中状态）
- 表格行距、可编辑多值下拉框与标签式多值输入框（TagInput）

依赖：PySide6.QtCore、PySide6.QtWidgets、app.domain.enums、app.domain.errors
被使用：app.presentation.main_window、app.presentation.views.question_bank_view、
        app.presentation.views.paper_generation_view、
        app.presentation.views.history_view、app.presentation.views.settings_view
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QStringListModel, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.domain.enums import (
    Difficulty,
    ExportFormat,
    QualityFlag,
    QuestionOpAction,
    QuestionSource,
    QuestionType,
    RecognizeModule,
    SectionKind,
)
from app.domain.errors import DomainError

#: 题型 -> 中文标签
QUESTION_TYPE_LABELS: dict[QuestionType, str] = {
    QuestionType.SINGLE: "单选题",
    QuestionType.MULTIPLE: "多选题",
    QuestionType.FILL: "填空题",
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
    SectionKind.FILL: "填空题部分",
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

#: AI 辨识模块 -> 中文标签（模块化输出与逐项检查统一口径）
RECOGNIZE_MODULE_LABELS: dict[RecognizeModule, str] = {
    RecognizeModule.SUBJECT: "科目",
    RecognizeModule.KNOWLEDGE_POINTS: "知识点",
    RecognizeModule.QUESTION_TYPE: "题型",
    RecognizeModule.DIFFICULTY: "难度",
    RecognizeModule.QUALITY_FLAG: "质量标记",
    RecognizeModule.ANSWER: "答案",
    RecognizeModule.SOLUTION: "解析",
    RecognizeModule.STEM: "题干",
    RecognizeModule.OPTIONS: "选项",
}

#: 表格紧凑行高（用户需求：减小科目 / 题型 / 难度 / 质量 / 图片 / 使用次数
#: 等短列所在行的高度）
COMPACT_ROW_HEIGHT = 18

#: 表格最小行高
COMPACT_MIN_ROW_HEIGHT = 16


def make_rows_compact(table) -> None:
    """收紧表格行距（各视图表格统一使用，避免行高参差不齐）。"""
    table.verticalHeader().setDefaultSectionSize(COMPACT_ROW_HEIGHT)
    table.verticalHeader().setMinimumSectionSize(COMPACT_MIN_ROW_HEIGHT)


def new_multi_combo(placeholder: str = "", minimum_width: int = 140) -> QComboBox:
    """构建可填多个取值的下拉框（知识点板块 / 知识点这类多值字段）。

    下拉给出候选，文本框可手写多个取值（用逗号 / 顿号分隔）。
    """
    combo = QComboBox()
    combo.setEditable(True)
    combo.setMinimumWidth(minimum_width)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    line_edit = combo.lineEdit()
    if line_edit is not None and placeholder:
        line_edit.setPlaceholderText(placeholder)
    return combo


def reload_combo_candidates(combo: QComboBox, candidates: list[str]) -> None:
    """刷新可编辑下拉框的候选并重建补全器（保留用户已输入文本）。

    候选项以 ``itemData`` 保存取值本身，便于 ``select_combo_data`` 直接定位。
    """
    current = combo.currentText()
    names = [str(name) for name in candidates]
    combo.blockSignals(True)
    combo.clear()
    for name in names:
        combo.addItem(name, name)
    combo.setCurrentIndex(-1)
    combo.setEditText(current)
    combo.blockSignals(False)
    completer = QCompleter(QStringListModel(names, combo), combo)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    combo.setCompleter(completer)


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


def confirm_action(
    parent: QWidget,
    text: str,
    title: str = "请确认",
    accept_text: str = "确定",
    reject_text: str = "取消",
) -> bool:
    """带自定义按钮文案的确认框（如"AI 分析 / 取消"）。

    :return: 点击接受按钮返回 True，否则 False
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(text)
    accept_button = box.addButton(accept_text, QMessageBox.ButtonRole.AcceptRole)
    box.addButton(reject_text, QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is accept_button


def choose_action(
    parent: QWidget,
    text: str,
    title: str = "请确认",
    actions: list[tuple[str, str]] | None = None,
) -> str | None:
    """多按钮选择框，返回被点击按钮的键（用于"AI 填充 / 手动补齐 / 取消"三选一）。

    :param text: 提示正文（逐项检查结果等）
    :param actions: ``[(键, 按钮文案)]``；最后一个按钮承担"取消 / 拒绝"角色，
        直接关闭对话框时返回 ``None``
    :return: 被点击按钮的键；未选择任何按钮时返回 ``None``
    """
    options = actions or [("ok", "确定"), ("cancel", "取消")]
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(text)
    mapping: dict[object, str] = {}
    for index, (key, label) in enumerate(options):
        role = (
            QMessageBox.ButtonRole.AcceptRole
            if index < len(options) - 1
            else QMessageBox.ButtonRole.RejectRole
        )
        mapping[box.addButton(label, role)] = key
    box.exec()
    return mapping.get(box.clickedButton())


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


class _FlowLayout(QLayout):
    """自动换行的流式布局：标签可叠加成多行（Qt 官方 FlowLayout 的精简版）。"""

    def __init__(self, parent: QWidget | None = None, margin: int = 0, spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 - Qt 命名约定
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 - Qt 命名约定
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 - Qt 命名约定
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802 - Qt 命名约定
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt 命名约定
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt 命名约定
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt 命名约定
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt 命名约定
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt 命名约定
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(
            margins.left() + margins.right(), margins.top() + margins.bottom()
        )

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        """按行摆放子项，超出宽度时换行；返回所需高度。"""
        margins = self.contentsMargins()
        area = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x, y, line_height = area.x(), area.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self.spacing()
            if next_x - self.spacing() > area.right() and line_height > 0:
                x = area.x()
                y = y + line_height + self.spacing()
                next_x = x + hint.width() + self.spacing()
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


class TagInput(QWidget):
    """标签式多值输入框（用户需求：搜索选标签、标签可叠加可删除、并列筛选）。

    - 输入即在下拉里给出候选标签；候选只由当前输入文本过滤，
      已选标签不会从候选中消失（用户需求：候选仅随当前输入刷新）
    - 选中候选或回车把当前输入加入已选标签，输入框清空后可继续输入
    - 标签平级、可叠加（自动换行）、点标签上的 × 删除
    - 多个标签是并列关系，调用方按"命中任一即匹配"使用
    """

    #: 用户增删标签时发出（程序化 :meth:`set_values` 不发）
    changed = Signal()

    def __init__(self, placeholder: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: list[str] = []
        self._candidates: list[str] = []

        self._tag_host = QWidget(self)
        self._tag_layout = _FlowLayout(self._tag_host)
        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText(placeholder)
        self._completer = QCompleter([], self._edit)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion
        )
        self._edit.setCompleter(self._completer)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._tag_host)
        layout.addWidget(self._edit)

        self._completer.activated.connect(self._on_candidate_activated)
        self._edit.returnPressed.connect(self._on_return_pressed)
        self._tag_host.setVisible(False)

    # ------------------------------------------------------------------ 取值

    def values(self) -> list[str]:
        """已选标签（按加入顺序）。"""
        return list(self._values)

    def set_values(self, values: Any) -> None:
        """整体替换已选标签（程序化调用，不发 ``changed``）。"""
        self._values = []
        for value in values or []:
            self._append_value(value)
        self._render_tags()

    def candidates(self) -> list[str]:
        """当前候选标签池。"""
        return list(self._candidates)

    def set_candidates(self, candidates: Any) -> None:
        """刷新候选标签池（保留已选标签与当前输入）。"""
        self._candidates = [str(value) for value in candidates or []]
        self._completer.setModel(
            QStringListModel(self._candidates, self._completer)
        )

    def clear_input(self) -> None:
        """清空输入框（不影响已选标签）。"""
        self._edit.clear()

    def placeholder(self) -> str:
        """输入框的占位提示文本。"""
        return self._edit.placeholderText()

    # ------------------------------------------------------------------ 交互

    def _on_candidate_activated(self, text: str) -> None:
        """下拉候选中选中一项：加入已选标签，可继续输入下一个。"""
        self._add_value(text)

    def _on_return_pressed(self) -> None:
        """回车：把当前输入加入已选标签（候选里没有的也可手写）。"""
        self._add_value(self._edit.text())

    def _add_value(self, raw: Any) -> None:
        value = str(raw).strip()
        if value and value not in self._values:
            self._values.append(value)
            self._render_tags()
            self.changed.emit()
        self.clear_input()
        self._edit.setFocus()

    def _append_value(self, raw: Any) -> None:
        value = str(raw).strip()
        if value and value not in self._values:
            self._values.append(value)

    def _remove_value(self, value: str) -> None:
        if value in self._values:
            self._values.remove(value)
            self._render_tags()
            self.changed.emit()

    def _render_tags(self) -> None:
        """重建标签行：每个标签 = 文本 + × 删除按钮。"""
        while self._tag_layout.count():
            item = self._tag_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for value in self._values:
            self._tag_layout.addWidget(self._build_tag(value))
        self._tag_host.setVisible(bool(self._values))

    def _build_tag(self, value: str) -> QWidget:
        """构建单个标签（文本 + 删除按钮）。"""
        tag = QFrame(self._tag_host)
        tag.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(tag)
        layout.setContentsMargins(6, 0, 2, 0)
        layout.setSpacing(2)
        layout.addWidget(QLabel(value, tag))
        remove = QToolButton(tag)
        remove.setText("×")
        remove.setAutoRaise(True)
        remove.setToolTip(f"删除标签：{value}")
        remove.clicked.connect(
            lambda _checked=False, name=value: self._remove_value(name)
        )
        layout.addWidget(remove)
        return tag
