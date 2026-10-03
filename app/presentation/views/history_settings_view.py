"""历史与设置视图：组卷历史 / AI 配置 / 评分与冷却配置（需求 R14 / R15 / R8 / R13）。

界面结构（内嵌三个子页签）：

- 组卷历史：任务列表（创建时间 / 条件摘要 / 总分 / 导出记录），
  可将选中任务的条件回填到组卷视图（需求 R14 第 2 / 3 条）
- AI 设置：base_url / api_key / model / 超时 / 重试（需求 R15）。
  API Key 仅保存本机，界面以密码框显示
- 评分与冷却：五项评分权重、冷却窗口计量方式与长度、抽样权重下限
  （需求 R8 第 7 条 / R13 第 4 条）

保存设置后发出 ``config_changed`` 信号，由主窗口刷新状态栏与命中量。

依赖：PySide6.QtCore / QtWidgets、app.container.Container、
      app.domain.entities.{criteria,task,configs}、app.domain.enums、
      app.presentation.ui_utils
调用服务：TaskHistoryService / ConfigStore
被使用：app.presentation.main_window
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.domain.entities.configs import AIConfig, ScoringConfig
from app.domain.entities.criteria import PaperCriteria
from app.domain.entities.task import GenerationTask
from app.domain.enums import CooldownMode
from app.presentation import ui_utils


class HistorySettingsView(QWidget):
    """历史与设置视图：历史复用、AI 配置与评分/冷却配置。"""

    #: 配置保存后发出，供主窗口刷新 AI 状态与命中量。
    config_changed = Signal()

    #: 请求复用历史组卷条件（携带 PaperCriteria），供主窗口回填组卷视图。
    reuse_criteria_requested = Signal(object)

    def __init__(self, container) -> None:
        """注入容器、构建界面并加载历史与配置。"""
        super().__init__()
        self._container = container
        self._history_service = container.task_history_service
        self._config_store = container.config_store
        self._tasks: list[GenerationTask] = []

        self._build_ui()
        self._load_ai_config()
        self._load_scoring_config()
        self.reload_tasks()

    # ------------------------------------------------------------------ 构建

    def _build_ui(self) -> None:
        """构建三个子页签。"""
        root = QVBoxLayout(self)
        self._inner_tabs = QTabWidget(self)
        self._inner_tabs.addTab(self._build_history_tab(), "组卷历史")
        self._inner_tabs.addTab(self._build_ai_tab(), "AI 设置")
        self._inner_tabs.addTab(self._build_scoring_tab(), "评分与冷却")
        root.addWidget(self._inner_tabs)

    def _build_history_tab(self) -> QWidget:
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

    def _build_ai_tab(self) -> QWidget:
        """构建 AI 设置页（需求 R15）。"""
        page = QWidget()
        form = QFormLayout(page)

        self._ai_base_url = QLineEdit()
        self._ai_base_url.setPlaceholderText("https://api.example.com/v1")
        self._ai_api_key = QLineEdit()
        self._ai_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._ai_api_key.setPlaceholderText("仅保存在本机，不写日志、不外传")
        self._ai_model = QLineEdit()
        self._ai_model.setPlaceholderText("如 deepseek-chat")
        self._ai_timeout = QSpinBox()
        self._ai_timeout.setRange(1000, 600000)
        self._ai_timeout.setSingleStep(1000)
        self._ai_timeout.setSuffix(" ms")
        self._ai_timeout.setValue(30000)
        self._ai_retries = QSpinBox()
        self._ai_retries.setRange(0, 10)
        self._ai_retries.setValue(2)

        form.addRow("接口地址", self._ai_base_url)
        form.addRow("API Key", self._ai_api_key)
        form.addRow("模型名称", self._ai_model)
        form.addRow("请求超时", self._ai_timeout)
        form.addRow("失败重试", self._ai_retries)

        save_button = QPushButton("保存 AI 配置")
        save_button.clicked.connect(self._on_save_ai)
        form.addRow(save_button)

        self._ai_status = QLabel("")
        form.addRow(self._ai_status)
        return page

    def _build_scoring_tab(self) -> QWidget:
        """构建评分与冷却设置页（需求 R8 / R13）。"""
        page = QWidget()
        form = QFormLayout(page)

        self._weight_difficulty = self._new_weight_spin()
        self._weight_knowledge = self._new_weight_spin()
        self._weight_quality = self._new_weight_spin()
        self._weight_use_count = self._new_weight_spin()
        self._weight_recency = self._new_weight_spin()

        self._cooldown_mode = QComboBox()
        self._cooldown_mode.addItem("按天数", CooldownMode.DAYS)
        self._cooldown_mode.addItem("按最近组卷任务数", CooldownMode.TASKS)
        self._cooldown_value = QSpinBox()
        self._cooldown_value.setRange(0, 3650)
        self._cooldown_value.setValue(30)

        self._epsilon = QDoubleSpinBox()
        self._epsilon.setRange(0.0, 1.0)
        self._epsilon.setDecimals(6)
        self._epsilon.setSingleStep(0.000001)
        self._epsilon.setValue(0.000001)

        form.addRow("难度匹配权重", self._weight_difficulty)
        form.addRow("知识点覆盖权重", self._weight_knowledge)
        form.addRow("人工质量权重", self._weight_quality)
        form.addRow("使用频次惩罚系数", self._weight_use_count)
        form.addRow("最近使用惩罚系数", self._weight_recency)
        form.addRow("冷却窗口计量", self._cooldown_mode)
        form.addRow("冷却窗口长度", self._cooldown_value)
        form.addRow("抽样权重下限", self._epsilon)

        button_row = QHBoxLayout()
        save_button = QPushButton("保存评分与冷却配置")
        save_button.clicked.connect(self._on_save_scoring)
        default_button = QPushButton("恢复默认值")
        default_button.clicked.connect(
            lambda _checked=False: self._fill_scoring_form(ScoringConfig())
        )
        button_row.addWidget(save_button)
        button_row.addWidget(default_button)
        button_row.addStretch(1)
        holder = QWidget()
        holder.setLayout(button_row)
        form.addRow(holder)
        return page

    @staticmethod
    def _new_weight_spin() -> QDoubleSpinBox:
        """构建评分权重输入框。"""
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 10.0)
        spin.setDecimals(2)
        spin.setSingleStep(0.05)
        return spin

    # --------------------------------------------------------------- 历史

    def reload_tasks(self) -> None:
        """加载历史任务（初始化与跨视图刷新使用，静默失败）。"""
        tasks = ui_utils.safe_call(self._history_service.list_tasks, default=None)
        if tasks is None:
            self._tasks = []
            self._render_tasks([])
            self._history_status.setText("历史功能尚未实现（框架占位）")
            return
        self._tasks = tasks
        self._render_tasks(tasks)
        self._history_status.setText(f"共 {len(tasks)} 条组卷记录")

    def _render_tasks(self, tasks: list[GenerationTask]) -> None:
        """渲染历史任务表（需求 R14 第 2 条）。"""
        self._history_table.setRowCount(0)
        for task in tasks:
            created = (
                task.created_at.strftime("%Y-%m-%d %H:%M")
                if task.created_at is not None
                else "—"
            )
            row = self._history_table.rowCount()
            self._history_table.insertRow(row)
            values = [
                created,
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

    # --------------------------------------------------------------- AI 配置

    def _load_ai_config(self) -> None:
        """从配置存储读取 AI 配置并回填表单（需求 R15）。"""
        config = ui_utils.safe_call(self._config_store.load_ai_config, default=None)
        if config is None:
            return
        self._ai_base_url.setText(config.base_url)
        self._ai_api_key.setText(config.api_key)
        self._ai_model.setText(config.model)
        self._ai_timeout.setValue(max(1000, int(config.timeout_ms)))
        self._ai_retries.setValue(max(0, int(config.max_retries)))
        self._update_ai_status_label(config)

    def _update_ai_status_label(self, config: AIConfig) -> None:
        """更新 AI 配置状态文字。"""
        if config.is_configured():
            self._ai_status.setText("当前状态：已配置，难度分析与 AI 补题可用")
        else:
            self._ai_status.setText("当前状态：未配置，难度分析与 AI 补题不可用")

    def _on_save_ai(self) -> None:
        """保存 AI 配置（需求 R15 第 1 / 3 / 5 条）。"""
        config = AIConfig(
            base_url=self._ai_base_url.text().strip(),
            api_key=self._ai_api_key.text().strip(),
            model=self._ai_model.text().strip(),
            timeout_ms=self._ai_timeout.value(),
            max_retries=self._ai_retries.value(),
        )
        ok, _ = ui_utils.run_guarded(
            self,
            self._config_store.save_ai_config,
            config,
            success_message="AI 配置已保存，用于后续 AI 调用",
        )
        if ok:
            self._update_ai_status_label(config)
            self.config_changed.emit()

    # ---------------------------------------------------------- 评分与冷却配置

    def _load_scoring_config(self) -> None:
        """读取评分与冷却配置并回填表单。"""
        config = ui_utils.safe_call(
            self._config_store.load_scoring_config, default=None
        )
        if config is None:
            return
        self._fill_scoring_form(config)

    def _fill_scoring_form(self, config: ScoringConfig) -> None:
        """把评分配置写入表单控件。"""
        self._weight_difficulty.setValue(config.weight_difficulty)
        self._weight_knowledge.setValue(config.weight_knowledge_coverage)
        self._weight_quality.setValue(config.weight_quality)
        self._weight_use_count.setValue(config.weight_use_count)
        self._weight_recency.setValue(config.weight_recency)
        ui_utils.select_combo_data(self._cooldown_mode, config.cooldown_mode)
        self._cooldown_value.setValue(int(config.cooldown_value))
        self._epsilon.setValue(config.epsilon)

    def _on_save_scoring(self) -> None:
        """保存评分与冷却配置（需求 R8 第 7 条 / R13 第 4 条）。"""
        config = ScoringConfig(
            weight_difficulty=self._weight_difficulty.value(),
            weight_knowledge_coverage=self._weight_knowledge.value(),
            weight_quality=self._weight_quality.value(),
            weight_use_count=self._weight_use_count.value(),
            weight_recency=self._weight_recency.value(),
            cooldown_mode=self._cooldown_mode.currentData(),
            cooldown_value=self._cooldown_value.value(),
            epsilon=self._epsilon.value(),
        )
        ok, _ = ui_utils.run_guarded(
            self,
            self._config_store.save_scoring_config,
            config,
            success_message="评分与冷却配置已保存，用于后续组卷",
        )
        if ok:
            self.config_changed.emit()
