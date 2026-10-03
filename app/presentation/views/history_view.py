"""历史视图：组卷历史 / 导入历史 / 编辑历史（用户需求：历史与设置分开）。

界面结构（三个页签）：

- 组卷历史：任务列表（创建时间 / 条件摘要 / 总分 / 导出记录），
  可将选中任务的条件回填到组卷视图（需求 R14 第 2 / 3 条）
- 导入历史：批量导入题目的台账（时间 / 科目 / 题干摘要 / 批次 / 说明）
- 编辑历史：单题录入、编辑与删除的台账（时间 / 操作 / 科目 / 题干摘要 / 说明）

依赖：PySide6.QtCore / QtWidgets、app.container.Container、
      app.domain.entities.{criteria,task}、app.presentation.ui_utils
调用服务：TaskHistoryService / QuestionHistoryService
被使用：app.presentation.main_window
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.domain.entities.criteria import PaperCriteria
from app.domain.entities.task import GenerationTask
from app.presentation import ui_utils


class HistoryView(QWidget):
    """历史视图：组卷历史与题库操作台账（导入 / 编辑）。"""

    #: 请求复用历史组卷条件（携带 PaperCriteria），供主窗口回填组卷视图。
    reuse_criteria_requested = Signal(object)

    def __init__(self, container) -> None:
        """注入容器、构建界面并加载历史数据。"""
        super().__init__()
        self._container = container
        self._history_service = container.task_history_service
        self._question_history_service = container.question_history_service
        self._tasks: list[GenerationTask] = []

        self._build_ui()
        self.reload_tasks()
        self.reload_question_history()

    # ------------------------------------------------------------------ 构建

    def _build_ui(self) -> None:
        """构建三个历史页签。"""
        root = QVBoxLayout(self)
        self._inner_tabs = QTabWidget(self)
        self._inner_tabs.addTab(self._build_task_tab(), "组卷历史")
        self._inner_tabs.addTab(self._build_import_tab(), "导入历史")
        self._inner_tabs.addTab(self._build_edit_tab(), "编辑历史")
        root.addWidget(self._inner_tabs)

    def _build_task_tab(self) -> QWidget:
        """构建组卷历史页。"""
        page = QWidget()
        layout = QVBoxLayout(page)

        self._history_table = QTableWidget(0, 4)
        self._history_table.setHorizontalHeaderLabels(
            ["创建时间", "组卷条件", "总分", "导出记录"]
        )
        self._history_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._history_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._history_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._history_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._history_table)

        button_row = QHBoxLayout()
        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self.reload_tasks)
        reuse_button = QPushButton("复用配置")
        reuse_button.clicked.connect(self._on_reuse)
        button_row.addWidget(refresh_button)
        button_row.addWidget(reuse_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self._history_status = QLabel("尚未加载")
        layout.addWidget(self._history_status)
        return page

    def _build_import_tab(self) -> QWidget:
        """构建导入历史页（批量导入题目的台账）。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(
            QLabel("记录每次批量导入（粘贴解析 / 批量入库）的时间、科目与批次。")
        )

        self._import_table = QTableWidget(0, 5)
        self._import_table.setHorizontalHeaderLabels(
            ["时间", "科目", "题干摘要", "批次", "说明"]
        )
        self._configure_readonly_table(self._import_table, stretch_column=2)
        layout.addWidget(self._import_table)

        button_row = QHBoxLayout()
        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self.reload_question_history)
        button_row.addWidget(refresh_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self._import_status = QLabel("尚未加载")
        layout.addWidget(self._import_status)
        return page

    def _build_edit_tab(self) -> QWidget:
        """构建编辑历史页（单题录入 / 编辑 / 删除的台账）。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(
            QLabel("记录题目的录入、编辑（含难度与质量修正）与删除操作。")
        )

        self._edit_table = QTableWidget(0, 5)
        self._edit_table.setHorizontalHeaderLabels(
            ["时间", "操作", "科目", "题干摘要", "变更说明"]
        )
        self._configure_readonly_table(self._edit_table, stretch_column=4)
        layout.addWidget(self._edit_table)

        button_row = QHBoxLayout()
        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self.reload_question_history)
        button_row.addWidget(refresh_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self._edit_status = QLabel("尚未加载")
        layout.addWidget(self._edit_status)
        return page

    @staticmethod
    def _configure_readonly_table(table: QTableWidget, stretch_column: int) -> None:
        """统一设置只读、按行选择与末列拉伸。"""
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.horizontalHeader().setSectionResizeMode(
            stretch_column, QHeaderView.ResizeMode.Stretch
        )

    # --------------------------------------------------------------- 加载

    def reload_tasks(self) -> None:
        """加载组卷历史（初始化与跨视图刷新使用，静默失败）。"""
        tasks = ui_utils.safe_call(self._history_service.list_tasks, default=None)
        if tasks is None:
            self._tasks = []
            self._render_tasks([])
            self._history_status.setText("组卷历史尚未实现（框架占位）")
            return
        self._tasks = tasks
        self._render_tasks(tasks)
        self._history_status.setText(f"共 {len(tasks)} 条组卷记录")

    def reload_question_history(self) -> None:
        """加载导入历史与编辑历史（静默失败，不阻塞界面）。"""
        imports = ui_utils.safe_call(
            self._question_history_service.list_import_history, default=[]
        ) or []
        edits = ui_utils.safe_call(
            self._question_history_service.list_edit_history, default=[]
        ) or []

        self._render_operation_table(
            self._import_table,
            imports,
            detail_column=4,
            columns=("subject", "stem", "batch", "detail"),
        )
        self._render_operation_table(
            self._edit_table,
            edits,
            detail_column=4,
            columns=("action", "subject", "stem", "detail"),
        )
        self._import_status.setText(f"共 {len(imports)} 条导入记录")
        self._edit_status.setText(f"共 {len(edits)} 条编辑记录")

    def _render_operation_table(
        self,
        table: QTableWidget,
        records: list,
        detail_column: int,
        columns: tuple[str, ...],
    ) -> None:
        """渲染操作台账表：columns 决定列顺序（action / subject / stem / batch / detail）。"""
        table.setRowCount(0)
        for record in records:
            row = table.rowCount()
            table.insertRow(row)
            values = [self._format_time(record.created_at)]
            for name in columns:
                if name == "action":
                    values.append(ui_utils.OP_ACTION_LABELS.get(record.action, ""))
                elif name == "subject":
                    values.append(record.subject or "—")
                elif name == "stem":
                    values.append(record.stem_excerpt or "—")
                elif name == "batch":
                    values.append(record.batch_id or "—")
                else:
                    values.append(record.detail or "—")
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(str(value)))

    @staticmethod
    def _format_time(value) -> str:
        """时间格式化展示（缺省为破折号）。"""
        return value.strftime("%Y-%m-%d %H:%M") if value is not None else "—"

    def _render_tasks(self, tasks: list[GenerationTask]) -> None:
        """渲染组卷历史表（需求 R14 第 2 条）。"""
        self._history_table.setRowCount(0)
        for task in tasks:
            row = self._history_table.rowCount()
            self._history_table.insertRow(row)
            values = [
                self._format_time(task.created_at),
                self._criteria_summary(task.criteria),
                f"{task.total_score:g}",
                self._exports_summary(task),
            ]
            for column, value in enumerate(values):
                self._history_table.setItem(
                    row, column, QTableWidgetItem(str(value))
                )

    def _on_reuse(self) -> None:
        """读取选中任务的条件并请求主窗口回填组卷表单（需求 R14 第 3 条）。"""
        row = self._history_table.currentRow()
        if row < 0 or row >= len(self._tasks):
            ui_utils.info(self, "请先在历史列表中选择一条组卷记录。")
            return
        task = self._tasks[row]
        ok, criteria = ui_utils.run_guarded(
            self, self._history_service.reuse_criteria, task.id
        )
        if ok and criteria is not None:
            self.reuse_criteria_requested.emit(criteria)

    @staticmethod
    def _criteria_summary(criteria: PaperCriteria) -> str:
        """把组卷条件渲染为一行摘要。"""
        parts: list[str] = []
        if criteria.choice_enabled:
            for item in criteria.choice_items:
                parts.append(
                    f"{ui_utils.QUESTION_TYPE_LABELS.get(item.question_type, '')}"
                    f"×{item.count}（{item.subject}/"
                    f"{ui_utils.DIFFICULTY_LABELS.get(item.difficulty, '')}）"
                )
        if criteria.fill_enabled and criteria.fill_item is not None:
            item = criteria.fill_item
            parts.append(
                f"填空题×{item.count}（{item.subject}/"
                f"{ui_utils.DIFFICULTY_LABELS.get(item.difficulty, '')}）"
            )
        if criteria.solution_enabled and criteria.solution_item is not None:
            item = criteria.solution_item
            parts.append(
                f"解答题×{item.count}（{item.subject}/"
                f"{ui_utils.DIFFICULTY_LABELS.get(item.difficulty, '')}）"
            )
        return "；".join(parts) if parts else "—"

    @staticmethod
    def _exports_summary(task: GenerationTask) -> str:
        """把任务的导出记录渲染为一行摘要（需求 R12 第 8 条）。"""
        if not task.export_records:
            return "—"
        return "、".join(
            record.format.value.upper() for record in task.export_records
        )
