"""组卷视图：配置 / 配比统计 / 生成 / 分值编辑 / 导出（需求 R6-R12）。

界面结构（用户需求）：

- 组卷科目：一次组卷只针对一个科目
- 四个题型分组（单选 / 多选 / 填空 / 解答）：保留原分组容器与原有条件控件
  （启用开关 + 知识点板块 / 知识点 / 难度 / 数量 / 命中量），并在其下**追加配置表**，
  显示当前题型已添加的条目（序号 / 题型 / 知识点板块 / 知识点 / 难度 / 数量 / 命中题数）；
  知识点板块与知识点用标签输入框：输入即给候选标签，选中或回车加入已选，
  标签平级、可叠加、可删除，多个标签是并列筛选（命中任一即匹配，用户需求）；
  点"添加到配置表"把当前条件追加为一行，可改难度、改数量、删除行；
  选定知识点板块后知识点候选只保留该板块的细分知识点（用户需求：板块作为限定），
  只配数量，不勾选单题
- 配比统计预览：跨题型汇总（题型 / 难度 / 知识点板块 / 知识点 / 配置题数 / 命中题数），
  只显示统计表，不显示题目正文
- 生成试卷：调用 PaperComposer（题库不足按实际可提供数量出卷）
- 试卷预览与分值：原有展示与分值设置逻辑不变，表格高度为原 3 倍
- 导出：选择 MD / PDF 并导出到工作区根目录下程序自建的导出文件夹（用户不再指定路径），
  PDF 由同一次导出的 Markdown 源文件转换而来

数据流：上方配置 -> 各题型配置表与中间统计实时更新（300ms 防抖）；
下方预览在点击"生成试卷"时按最新配置渲染。

依赖：PySide6.QtCore / QtWidgets、app.container.Container、
      app.domain.entities.{criteria,paper,question}、app.domain.entities.configs、
      app.domain.enums、app.presentation.ui_utils
调用服务：PaperComposer / ScoreCalculator / PaperExporter / QuestionService
被使用：app.presentation.main_window
"""

from pathlib import Path
import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config.settings import DEFAULT_EXPORT_DIR
from app.domain.entities.configs import ExportOptions
from app.domain.entities.criteria import PaperCriteria, TypeRequirement
from app.domain.entities.paper import Paper, Section
from app.domain.entities.question import Question, split_sections
from app.domain.enums import Difficulty, ExportFormat, QuestionType
from app.domain.errors import DomainError
from app.presentation import ui_utils

#: 题型顺序：选择 -> 填空 -> 解答（与 PaperCriteria.enabled_requirements 一致）
_TYPE_ORDER: tuple[QuestionType, ...] = (
    QuestionType.SINGLE,
    QuestionType.MULTIPLE,
    QuestionType.FILL,
    QuestionType.SOLUTION,
)

#: 题型 -> 分组标题
_TYPE_GROUP_TITLES: dict[QuestionType, str] = {
    QuestionType.SINGLE: "单选题部分",
    QuestionType.MULTIPLE: "多选题部分",
    QuestionType.FILL: "填空题部分",
    QuestionType.SOLUTION: "解答题部分",
}

#: 各题型数量控件的默认值（沿用原有默认）
_TYPE_DEFAULT_COUNT: dict[QuestionType, int] = {
    QuestionType.SINGLE: 5,
    QuestionType.MULTIPLE: 3,
    QuestionType.FILL: 4,
    QuestionType.SOLUTION: 2,
}

#: 配置表列：序号 / 题型 / 知识点板块 / 知识点 / 难度 / 数量 / 命中题数
_CONFIG_COLUMNS: tuple[str, ...] = (
    "序号",
    "题型",
    "知识点板块",
    "知识点",
    "难度",
    "数量",
    "命中题数",
)

#: 知识点板块 / 知识点留空时在配置表中显示的占位文本（对应该行"不限"）
_ANY_LABEL = "不限"

#: 三级难度（组卷不接受"待确认"）
_DIFFICULTIES: tuple[Difficulty, ...] = (
    Difficulty.EASY,
    Difficulty.MEDIUM,
    Difficulty.HARD,
)

#: 原中间汇总表的高度（配置表与汇总表高度的基准）
_SUMMARY_TABLE_HEIGHT = 120

#: 配置表与中间汇总表的高度 = 原中间汇总表高度 × 2（用户需求：两者都加高）
_TABLE_HEIGHT = _SUMMARY_TABLE_HEIGHT * 2

#: 试卷预览表格高度 = 原始高度 × 本系数（用户需求：高度为原 3 倍）
_PREVIEW_HEIGHT_FACTOR = 3

#: 难度标签 -> 枚举（配置行以标签文本存储，便于直接用表格编辑）
_DIFFICULTY_BY_LABEL: dict[str, Difficulty] = {
    ui_utils.DIFFICULTY_LABELS[difficulty]: difficulty for difficulty in _DIFFICULTIES
}


class _DifficultyDelegate(QStyledItemDelegate):
    """难度列编辑器：只能选择易 / 中 / 难。

    用委托按需创建编辑器而不是常驻控件：配置表行数可能很多，
    常驻控件会让界面卡住（用户反馈的"选择科目无响应"）。
    """

    def createEditor(self, parent, option, index):  # noqa: N802 - Qt 命名约定
        """返回难度下拉框编辑器。"""
        combo = QComboBox(parent)
        for difficulty in _DIFFICULTIES:
            combo.addItem(ui_utils.DIFFICULTY_LABELS[difficulty])
        return combo


class _CountDelegate(QStyledItemDelegate):
    """数量列编辑器：0-999 的整数输入框。"""

    def createEditor(self, parent, option, index):  # noqa: N802 - Qt 命名约定
        """返回数量输入框编辑器。"""
        editor = QSpinBox(parent)
        editor.setRange(0, 999)
        return editor

    def setEditorData(self, editor, index) -> None:  # noqa: N802 - Qt 命名约定
        """把单元格数值写入编辑器（文本转整数，非法值按 0 处理）。"""
        try:
            editor.setValue(int(index.data(Qt.ItemDataRole.EditRole) or 0))
        except (TypeError, ValueError):
            editor.setValue(0)


class PaperGenerationView(QWidget):
    """组卷视图：按题型逐个添加"知识点 / 难度 / 数量"配置，顺序取题。"""

    #: 导出进度文字（后台线程发出，主线程显示；避免用户以为程序卡死）
    export_progress = Signal(str)

    #: 导出结束：``(是否成功, 文件路径或异常对象)``
    export_finished = Signal(bool, object)

    def __init__(self, container) -> None:
        """注入容器、构建界面并刷新知识点候选与命中量。"""
        super().__init__()
        self._container = container
        self._composer = container.paper_composer
        self._score_calculator = container.score_calculator
        self._exporter = container.paper_exporter
        self._question_service = container.question_service

        self._paper: Paper | None = None
        self._row_map: list[tuple[Section, Question]] = []
        self._type_tables: dict[QuestionType, QTableWidget] = {}
        self._type_bodies: dict[QuestionType, QWidget] = {}
        self._type_enabled: dict[QuestionType, QCheckBox] = {}
        self._type_sections: dict[QuestionType, ui_utils.TagInput] = {}
        self._type_knowledge: dict[QuestionType, ui_utils.TagInput] = {}
        self._type_difficulty: dict[QuestionType, QComboBox] = {}
        self._type_count: dict[QuestionType, QSpinBox] = {}
        self._type_hit: dict[QuestionType, QLabel] = {}
        self._sections_map: dict[str, list[str]] = {}
        self._subject_points: list[str] = []
        self._exporting = False

        self._hit_timer = QTimer(self)
        self._hit_timer.setSingleShot(True)
        self._hit_timer.setInterval(300)
        self._hit_timer.timeout.connect(self.refresh_hit_counts)

        self._build_ui()
        self.export_progress.connect(self._on_export_progress)
        self.export_finished.connect(self._on_export_finished)
        self.reload_subjects()
        self.refresh_hit_counts()

    # ------------------------------------------------------------------ 构建

    def _build_ui(self) -> None:
        """构建组卷视图整体布局（配置区 / 配比统计 / 试卷预览 / 导出）。"""
        root = QVBoxLayout(self)
        root.addWidget(self._build_subject_group())
        for question_type in _TYPE_ORDER:
            root.addWidget(self._build_type_group(question_type))

        self._generate_button = QPushButton("生成试卷")
        self._generate_button.clicked.connect(self._on_generate)
        root.addWidget(self._generate_button)

        root.addWidget(self._build_stats_group())
        root.addWidget(self._build_result_group())
        root.addWidget(self._build_export_group())

        self._status = QLabel("就绪")
        root.addWidget(self._status)

    def _build_subject_group(self) -> QGroupBox:
        """构建全局科目选择区（一次组卷只针对一个科目）。"""
        group = QGroupBox("组卷科目")
        layout = QHBoxLayout(group)
        self._subject_combo = self._new_subject_combo()
        self._subject_combo.currentIndexChanged.connect(self._on_subject_changed)
        layout.addWidget(QLabel("科目"))
        layout.addWidget(self._subject_combo)
        layout.addWidget(QLabel("（一次组卷只针对一个科目）"))
        layout.addStretch(1)
        return group

    @staticmethod
    def _new_subject_combo() -> QComboBox:
        """构建科目下拉框：科目只能从设置中维护的列表选择（用户需求）。"""
        combo = QComboBox()
        combo.setMinimumWidth(120)
        return combo

    @staticmethod
    def _new_difficulty_combo() -> QComboBox:
        """构建只含三级难度的下拉框（组卷不接受"待确认"）。"""
        combo = QComboBox()
        for difficulty in _DIFFICULTIES:
            combo.addItem(ui_utils.DIFFICULTY_LABELS[difficulty], difficulty)
        ui_utils.select_combo_data(combo, Difficulty.MEDIUM)
        return combo

    @staticmethod
    def _new_section_input() -> ui_utils.TagInput:
        """构建知识点板块标签输入框（用户需求：可按多个板块并列限定）。"""
        return ui_utils.TagInput("输入板块名，选候选或回车加入")

    @staticmethod
    def _new_knowledge_input() -> ui_utils.TagInput:
        """构建知识点标签输入框（多知识点为并列筛选）。"""
        return ui_utils.TagInput("输入知识点，选候选或回车加入")

    @staticmethod
    def parse_knowledge(text: str) -> list[str]:
        """把知识点输入文本拆分为知识点列表（支持中英文逗号、顿号与分号）。"""
        return split_sections(text)

    def _build_type_group(self, question_type: QuestionType) -> QGroupBox:
        """构建单个题型分组：原条件控件（含知识点板块）+ 追加的配置表。"""
        title = _TYPE_GROUP_TITLES[question_type]
        group = QGroupBox(title)
        outer = QVBoxLayout(group)

        enabled = QCheckBox(f"启用{title}")
        enabled.toggled.connect(self._on_conditions_changed)
        outer.addWidget(enabled)

        body = QWidget()
        body_layout = QVBoxLayout(body)

        # 原条件控件：知识点板块 / 知识点 / 难度 / 数量（只配数量，不勾选单题）；
        # 板块与知识点用标签输入框：标签平级、可叠加、可删除，作为并列筛选（用户需求）
        section = self._new_section_input()
        knowledge = self._new_knowledge_input()
        difficulty = self._new_difficulty_combo()
        count = QSpinBox()
        count.setRange(1, 999)
        count.setValue(_TYPE_DEFAULT_COUNT[question_type])
        hit = QLabel("命中：—")
        form = QFormLayout()
        form.addRow("知识点板块", section)
        form.addRow("知识点", knowledge)
        form.addRow("难度", difficulty)
        form.addRow("数量", count)
        form.addRow("", hit)
        body_layout.addLayout(form)

        section.changed.connect(
            lambda target=question_type: self._on_section_changed(target)
        )
        knowledge.changed.connect(self._on_conditions_changed)
        difficulty.currentIndexChanged.connect(self._on_conditions_changed)

        # 追加的配置表：显示当前题型已添加的条目（不含题目正文）
        table = QTableWidget(0, len(_CONFIG_COLUMNS))
        table.setHorizontalHeaderLabels(list(_CONFIG_COLUMNS))
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table.setMaximumHeight(_TABLE_HEIGHT)
        table.setMinimumHeight(_TABLE_HEIGHT)
        table.setItemDelegateForColumn(4, _DifficultyDelegate(table))
        table.setItemDelegateForColumn(5, _CountDelegate(table))
        table.itemChanged.connect(self._on_conditions_changed)
        ui_utils.make_rows_compact(table)

        add_button = QPushButton("添加到配置表")
        add_button.clicked.connect(
            lambda _checked=False, target=question_type: self._add_from_controls(target)
        )
        remove_button = QPushButton("删除选中行")
        remove_button.clicked.connect(
            lambda _checked=False, target=table: self._remove_selected_rows(target)
        )
        button_row = QHBoxLayout()
        button_row.addWidget(add_button)
        button_row.addWidget(remove_button)
        button_row.addStretch(1)
        body_layout.addLayout(button_row)
        body_layout.addWidget(table)

        outer.addWidget(body)
        body.setEnabled(enabled.isChecked())

        self._type_tables[question_type] = table
        self._type_bodies[question_type] = body
        self._type_enabled[question_type] = enabled
        self._type_sections[question_type] = section
        self._type_knowledge[question_type] = knowledge
        self._type_difficulty[question_type] = difficulty
        self._type_count[question_type] = count
        self._type_hit[question_type] = hit
        return group

    def _build_stats_group(self) -> QGroupBox:
        """构建配比统计预览区（跨题型汇总，只显示统计表）。"""
        group = QGroupBox("配比统计预览")
        layout = QVBoxLayout(group)

        self._stats_table = QTableWidget(0, 6)
        self._stats_table.setHorizontalHeaderLabels(
            ["题型", "难度", "知识点板块", "知识点", "配置题数", "命中题数"]
        )
        self._stats_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._stats_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._stats_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self._stats_table.setMinimumHeight(_TABLE_HEIGHT)
        self._stats_table.setMaximumHeight(_TABLE_HEIGHT)
        ui_utils.make_rows_compact(self._stats_table)
        layout.addWidget(self._stats_table)
        return group

    def _build_result_group(self) -> QGroupBox:
        """构建试卷预览与分值编辑区（原有逻辑与分值逻辑不变）。"""
        group = QGroupBox("试卷预览与分值")
        layout = QVBoxLayout(group)

        self._result_table = QTableWidget(0, 6)
        self._result_table.setHorizontalHeaderLabels(
            ["部分", "题型", "题号", "题干", "难度", "分值"]
        )
        self._result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._result_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._result_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._result_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        # 高度为原 3 倍（用户需求）
        self._result_table.setMinimumHeight(
            self._result_table.sizeHint().height() * _PREVIEW_HEIGHT_FACTOR
        )
        ui_utils.make_rows_compact(self._result_table)
        layout.addWidget(self._result_table)

        score_row = QHBoxLayout()
        self._type_score_spin = QDoubleSpinBox()
        self._type_score_spin.setRange(0.0, 1000.0)
        self._type_score_spin.setDecimals(2)
        self._type_score_spin.setValue(5.0)
        apply_type_button = QPushButton("按题型设置统一分值")
        apply_type_button.clicked.connect(self._on_apply_type_score)

        self._question_score_spin = QDoubleSpinBox()
        self._question_score_spin.setRange(0.0, 1000.0)
        self._question_score_spin.setDecimals(2)
        self._question_score_spin.setValue(5.0)
        apply_question_button = QPushButton("为选中题设置分值")
        apply_question_button.clicked.connect(self._on_apply_question_score)

        score_row.addWidget(QLabel("单题分值"))
        score_row.addWidget(self._type_score_spin)
        score_row.addWidget(apply_type_button)
        score_row.addSpacing(20)
        score_row.addWidget(QLabel("逐题分值"))
        score_row.addWidget(self._question_score_spin)
        score_row.addWidget(apply_question_button)
        score_row.addStretch(1)
        layout.addLayout(score_row)

        self._total_label = QLabel("总分：—")
        layout.addWidget(self._total_label)
        return group

    def _build_export_group(self) -> QGroupBox:
        """构建导出区：格式 + 固定导出目录展示 + 导出按钮（用户需求）。"""
        group = QGroupBox("导出")
        layout = QHBoxLayout(group)

        self._format_combo = QComboBox()
        formats = ui_utils.safe_call(self._exporter.supported_formats, default=None)
        if not formats:
            formats = [ExportFormat.MD, ExportFormat.PDF]
        for fmt in formats:
            self._format_combo.addItem(
                ui_utils.EXPORT_FORMAT_LABELS.get(fmt, str(fmt)), fmt
            )

        self._export_button = QPushButton("导出试卷")
        self._export_button.clicked.connect(self._on_export)

        layout.addWidget(QLabel("格式"))
        layout.addWidget(self._format_combo)
        layout.addWidget(
            QLabel(f"导出目录：{Path(DEFAULT_EXPORT_DIR).resolve()}（程序自动创建）"), 1
        )
        layout.addWidget(self._export_button)
        return group

    # --------------------------------------------------------------- 配置行

    @property
    def _subject(self) -> str:
        """当前全局科目（供命中统计与条件构建使用）。"""
        return self._subject_combo.currentText().strip()

    def reload_subjects(self) -> None:
        """按设置中的科目列表重建科目下拉框，并刷新知识点候选（用户需求）。"""
        subjects = ui_utils.safe_call(
            self._question_service.list_subjects, default=None
        )
        if not subjects:
            return
        current = self._subject_combo.currentText()
        self._subject_combo.blockSignals(True)
        self._subject_combo.clear()
        for subject in subjects:
            self._subject_combo.addItem(subject, subject)
        index = self._subject_combo.findText(current)
        self._subject_combo.setCurrentIndex(index if index >= 0 else 0)
        self._subject_combo.blockSignals(False)
        self.reload_knowledge_points()

    def reload_knowledge_points(self) -> None:
        """按当前科目刷新知识点板块候选、各题型的知识点候选与命中量。

        板块选定后只补全该板块的细分知识点（与题库录入页一致，用户需求）；
        保留用户当前输入（含手写但题库中还不存在的知识点）。
        """
        subject = self._subject
        sections = ui_utils.safe_call(
            self._question_service.list_sections, subject, default=None
        ) or {}
        self._sections_map = {
            str(name): [str(point) for point in points]
            for name, points in sections.items()
        }
        self._subject_points = list(
            ui_utils.safe_call(
                self._question_service.list_knowledge_points, subject, default=None
            )
            or []
        )
        for section_input in self._type_sections.values():
            section_input.set_candidates(list(self._sections_map))
        for question_type in _TYPE_ORDER:
            self._refresh_knowledge_candidates(question_type)
        self.refresh_hit_counts()

    def _section_of(self, question_type: QuestionType) -> str:
        """读取某题型选定的知识点板块标签（多个用"、"拼接；未选返回空串）。"""
        return "、".join(self._type_sections[question_type].values())

    def _refresh_knowledge_candidates(self, question_type: QuestionType) -> None:
        """按该题型选定的板块刷新知识点候选（多个板块取并集，未选则用科目全部）。

        候选池与已选知识点标签无关（用户需求：候选仅随当前输入刷新）。
        """
        selected = self._type_sections[question_type].values()
        if selected:
            points = [
                point
                for name in selected
                for point in self._sections_map.get(name, [])
            ]
        else:
            points = list(self._subject_points)
        self._type_knowledge[question_type].set_candidates(
            list(dict.fromkeys(points))
        )

    def _on_section_changed(self, question_type: QuestionType) -> None:
        """板块标签变化：刷新该题型的知识点候选并刷新命中量。"""
        self._refresh_knowledge_candidates(question_type)
        self._on_conditions_changed()

    def _on_subject_changed(self) -> None:
        """科目变化：刷新板块 / 知识点候选与命中量（配置行保持不动）。"""
        self.reload_knowledge_points()

    def _add_from_controls(self, question_type: QuestionType) -> None:
        """把当前条件（知识点板块 / 知识点 / 难度 / 数量）追加为配置表的一行。"""
        knowledge = self._type_knowledge[question_type]
        difficulty = self._type_difficulty[question_type].currentData()
        if difficulty is None:
            return
        table = self._type_tables[question_type]
        self._append_row(
            table,
            question_type,
            self._section_of(question_type),
            "，".join(knowledge.values()),
            Difficulty(difficulty),
            self._type_count[question_type].value(),
        )
        knowledge.set_values([])
        self._on_conditions_changed()

    def _append_row(
        self,
        table: QTableWidget,
        question_type: QuestionType,
        section_text: str,
        point_text: str,
        difficulty: Difficulty,
        count: int,
    ) -> None:
        """追加一条配置行（序号自动编号，难度与数量在单元格内编辑）。"""
        row = table.rowCount()
        table.setRowCount(row + 1)
        self._write_row(
            table, row, question_type, section_text, point_text, difficulty, count
        )

    def _write_row(
        self,
        table: QTableWidget,
        row: int,
        question_type: QuestionType,
        section_text: str,
        point_text: str,
        difficulty: Difficulty,
        count: int,
    ) -> None:
        """写入一行配置：序号 / 题型 / 知识点板块 / 知识点只读，难度与数量可编辑。"""
        index_item = QTableWidgetItem(str(row + 1))
        index_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        type_item = QTableWidgetItem(
            ui_utils.QUESTION_TYPE_LABELS.get(question_type, "")
        )
        section_item = QTableWidgetItem(section_text or _ANY_LABEL)
        point_item = QTableWidgetItem(point_text or _ANY_LABEL)
        difficulty_item = QTableWidgetItem(ui_utils.DIFFICULTY_LABELS[difficulty])
        count_item = QTableWidgetItem(str(count))
        count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        hit_item = QTableWidgetItem("—")
        hit_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        for item in (index_item, type_item, section_item, point_item, hit_item):
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        for column, item in enumerate(
            (
                index_item,
                type_item,
                section_item,
                point_item,
                difficulty_item,
                count_item,
                hit_item,
            )
        ):
            table.setItem(row, column, item)

    @staticmethod
    def _row_values(
        table: QTableWidget, row: int
    ) -> tuple[str, str, Difficulty | None, int]:
        """读取一行配置：``(知识点板块, 知识点, 难度, 数量)``；难度无法识别返回 None。"""
        section_item = table.item(row, 2)
        point_item = table.item(row, 3)
        difficulty_item = table.item(row, 4)
        if section_item is None or point_item is None or difficulty_item is None:
            return ("", "", None, 0)
        return (
            "" if section_item.text() == _ANY_LABEL else section_item.text(),
            "" if point_item.text() == _ANY_LABEL else point_item.text(),
            _DIFFICULTY_BY_LABEL.get(difficulty_item.text()),
            PaperGenerationView._item_count(table.item(row, 5)),
        )

    @staticmethod
    def _item_count(item: QTableWidgetItem | None) -> int:
        """读取数量单元格数值（非法文本按 0 处理）。"""
        try:
            return int(item.text()) if item is not None else 0
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _renumber(table: QTableWidget) -> None:
        """重排配置表序号列（删除行后调用）。"""
        table.blockSignals(True)
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is not None:
                item.setText(str(row + 1))
        table.blockSignals(False)

    def _remove_selected_rows(self, table: QTableWidget) -> None:
        """删除配置表中选中的行（用户需求：配置行可手动删除）。"""
        rows = sorted({index.row() for index in table.selectedIndexes()}, reverse=True)
        for row in rows:
            table.removeRow(row)
        self._renumber(table)
        self._on_conditions_changed()

    def _read_rows(
        self, table: QTableWidget
    ) -> list[tuple[str, str, Difficulty, int]]:
        """读取配置表的有效行：``(知识点板块, 知识点, 难度, 数量)``。"""
        rows: list[tuple[str, str, Difficulty, int]] = []
        for row in range(table.rowCount()):
            section_text, point_text, difficulty, count = self._row_values(table, row)
            if difficulty is None:
                continue
            rows.append((section_text, point_text, difficulty, count))
        return rows

    # ------------------------------------------------------------- 条件与统计

    def _on_conditions_changed(self) -> None:
        """配置变化：切换分组可用性并触发命中量与统计的防抖刷新。"""
        for question_type, enabled in self._type_enabled.items():
            self._type_bodies[question_type].setEnabled(enabled.isChecked())
        self._hit_timer.start()

    def _count_hits(
        self,
        question_type: QuestionType,
        section_text: str,
        difficulty: Difficulty,
        point_text: str,
    ) -> int | None:
        """查询"科目 + 题型 + 知识点板块 + 难度 + 知识点"组合的题库命中题数。"""
        return ui_utils.safe_call(
            self._question_service.count_available,
            self._subject,
            difficulty,
            question_type,
            self.parse_knowledge(point_text),
            section_text or None,
            default=None,
        )

    def refresh_hit_counts(self) -> None:
        """刷新各题型配置表的命中题数列与中间配比统计（需求 R6 第 2 / 3 条）。"""
        stats: list[tuple[str, str, str, str, int, int | None]] = []
        for question_type in _TYPE_ORDER:
            table = self._type_tables[question_type]
            enabled = self._type_enabled[question_type].isChecked()
            table.blockSignals(True)
            for row in range(table.rowCount()):
                section_text, point_text, difficulty, count = self._row_values(
                    table, row
                )
                if difficulty is None:
                    continue
                hits = self._count_hits(
                    question_type, section_text, difficulty, point_text
                )
                hit_item = table.item(row, 6)
                if hit_item is not None:
                    hit_item.setText("—" if hits is None else str(hits))
                if enabled and count > 0:
                    stats.append(
                        (
                            ui_utils.QUESTION_TYPE_LABELS.get(question_type, ""),
                            ui_utils.DIFFICULTY_LABELS.get(difficulty, ""),
                            section_text or _ANY_LABEL,
                            point_text or _ANY_LABEL,
                            count,
                            hits,
                        )
                    )
            table.blockSignals(False)
            self._update_hit_label(question_type)
        self._render_stats(stats)

    def _update_hit_label(self, question_type: QuestionType) -> None:
        """刷新当前题型条件控件的命中量标签（含指定板块与知识点）。"""
        label = self._type_hit[question_type]
        difficulty = self._type_difficulty[question_type].currentData()
        if not self._subject:
            label.setText("命中：—（请先在设置中维护科目）")
            return
        if difficulty is None:
            label.setText("命中：—")
            return
        section_text = self._section_of(question_type)
        points = self._type_knowledge[question_type].values()
        hits = self._count_hits(
            question_type, section_text, Difficulty(difficulty), "、".join(points)
        )
        text = "命中：—" if hits is None else f"命中：{hits} 道"
        limits: list[str] = []
        if section_text:
            limits.append(f"板块：{section_text}")
        if points:
            limits.append(f"知识点：{'、'.join(points)}")
        if limits:
            text += f"（{'；'.join(limits)}）"
        label.setText(text)

    def _render_stats(
        self, rows: list[tuple[str, str, str, str, int, int | None]]
    ) -> None:
        """把统计行写入中间配比统计表（只显示统计，不显示题目正文）。"""
        self._stats_table.setRowCount(0)
        for values in rows:
            row = self._stats_table.rowCount()
            self._stats_table.insertRow(row)
            texts = [
                values[0],
                values[1],
                values[2],
                values[3],
                str(values[4]),
                "—" if values[5] is None else str(values[5]),
            ]
            for column, text in enumerate(texts):
                self._stats_table.setItem(row, column, QTableWidgetItem(text))

    @staticmethod
    def _items_of(
        criteria: PaperCriteria, question_type: QuestionType
    ) -> list[TypeRequirement]:
        """读取历史条件中某题型的全部出题要求。"""
        if question_type in (QuestionType.SINGLE, QuestionType.MULTIPLE):
            return [
                item
                for item in criteria.choice_items
                if item.question_type == question_type
            ]
        if question_type == QuestionType.FILL:
            return list(criteria.fill_items)
        return list(criteria.solution_items)

    def _build_criteria(self) -> PaperCriteria:
        """按配置表构建组卷条件（每条配置行 -> 一条 TypeRequirement）。"""
        subject = self._subject
        items: dict[QuestionType, list[TypeRequirement]] = {
            question_type: [] for question_type in _TYPE_ORDER
        }
        for question_type in _TYPE_ORDER:
            if not self._type_enabled[question_type].isChecked():
                continue
            for section_text, point_text, difficulty, count in self._read_rows(
                self._type_tables[question_type]
            ):
                if count <= 0:
                    continue
                items[question_type].append(
                    TypeRequirement(
                        question_type=question_type,
                        subject=subject,
                        difficulty=difficulty,
                        count=count,
                        knowledge_points=self.parse_knowledge(point_text),
                        section=section_text,
                    )
                )
        return PaperCriteria(
            choice_enabled=(
                self._type_enabled[QuestionType.SINGLE].isChecked()
                or self._type_enabled[QuestionType.MULTIPLE].isChecked()
            ),
            solution_enabled=self._type_enabled[QuestionType.SOLUTION].isChecked(),
            choice_items=items[QuestionType.SINGLE] + items[QuestionType.MULTIPLE],
            fill_enabled=self._type_enabled[QuestionType.FILL].isChecked(),
            fill_items=items[QuestionType.FILL],
            solution_items=items[QuestionType.SOLUTION],
            subject=subject,
        )

    def apply_criteria(self, criteria: PaperCriteria) -> None:
        """回填历史组卷条件（需求 R14 第 3 条：仅回填条件，题单重新生成）。"""
        subject = criteria.subject or next(
            (item.subject for item in criteria.enabled_requirements()), ""
        )
        index = self._subject_combo.findText(subject)
        if index >= 0:
            self._subject_combo.blockSignals(True)
            self._subject_combo.setCurrentIndex(index)
            self._subject_combo.blockSignals(False)

        for question_type in _TYPE_ORDER:
            items = self._items_of(criteria, question_type)
            enabled = self._type_enabled[question_type]
            enabled.blockSignals(True)
            enabled.setChecked(bool(items))
            enabled.blockSignals(False)
            self._type_bodies[question_type].setEnabled(bool(items))
            self._fill_rows(question_type, items)

        self.reload_knowledge_points()

    def _fill_rows(
        self, question_type: QuestionType, items: list[TypeRequirement]
    ) -> None:
        """重建某题型的配置表：把历史条件的各条要求逐行写入。"""
        table = self._type_tables[question_type]
        table.blockSignals(True)
        table.setRowCount(len(items))
        for row, item in enumerate(items):
            self._write_row(
                table,
                row,
                question_type,
                item.section,
                "，".join(item.knowledge_points or []),
                item.difficulty,
                int(item.count),
            )
        table.blockSignals(False)
        self._apply_controls_from_items(question_type, items)

    def _apply_controls_from_items(
        self, question_type: QuestionType, items: list[TypeRequirement]
    ) -> None:
        """把历史条件里的板块与知识点回填到该题型的条件控件上。"""
        if not items:
            return
        first = items[0]
        if first.section:
            # 板块可多个，按标签整段回填（用户需求）
            self._type_sections[question_type].set_values(
                split_sections(first.section)
            )
        self._type_knowledge[question_type].set_values(
            list(first.knowledge_points or [])
        )

    # --------------------------------------------------------------- 生成

    def _confirm_ai_supplement(self) -> bool:
        """组卷前询问是否允许 AI 补题（用户需求：AI 使用需手动确认）。"""
        if not self._question_service.ai_configured():
            return False
        return ui_utils.confirm_action(
            self,
            "组卷时若题库题量不足，可能需要调用 AI 补题。\n\n"
            "是否允许本次组卷使用 AI 补题？（选「仅用题库」则不足部分不补）",
            title="AI 补题确认",
            accept_text="允许 AI 补题",
            reject_text="仅用题库",
        )

    def _on_generate(self) -> None:
        """执行组卷（需求 R7-R10 / R13）。"""
        criteria = self._build_criteria()
        if not criteria.enabled_requirements():
            ui_utils.warning(self, "请先为要出题的题型添加配置行，并配置大于 0 的题数。")
            return
        allow_ai = self._confirm_ai_supplement()
        ok, paper = ui_utils.run_guarded(
            self,
            self._composer.generate,
            criteria,
            allow_ai,
            success_message="试卷已生成",
        )
        if not ok or paper is None:
            return
        self._paper = paper
        self._render_paper(paper)
        self._update_total()
        self._status.setText(f"已生成 {len(paper.questions())} 道题")

    def _render_paper(self, paper: Paper) -> None:
        """把试卷内容渲染到预览表，并记录行 -> (分区, 题目) 映射。"""
        self._result_table.setRowCount(0)
        self._row_map = []
        if paper is None:
            return
        for section in paper.sections:
            for index, question in enumerate(section.questions, start=1):
                row = self._result_table.rowCount()
                self._result_table.insertRow(row)
                score = section.score_of(question.id)
                values = [
                    ui_utils.SECTION_LABELS.get(section.section_kind, ""),
                    ui_utils.QUESTION_TYPE_LABELS.get(question.type, ""),
                    str(index),
                    question.stem,
                    ui_utils.DIFFICULTY_LABELS.get(question.difficulty, ""),
                    self._format_score(score),
                ]
                for column, value in enumerate(values):
                    self._result_table.setItem(
                        row, column, QTableWidgetItem(str(value))
                    )
                self._row_map.append((section, question))

    @staticmethod
    def _format_score(score: float | None) -> str:
        """格式化分值展示（未设置为破折号）。"""
        return "—" if score is None else f"{score:g}"

    def _update_total(self) -> None:
        """刷新总分显示（需求 R11 第 3 条）。"""
        if self._paper is None:
            self._total_label.setText("总分：—")
            return
        total = ui_utils.safe_call(
            self._score_calculator.total_score, self._paper, default=None
        )
        self._total_label.setText("总分：—" if total is None else f"总分：{total:g} 分")

    def _on_apply_type_score(self) -> None:
        """按题型统一设置分值（需求 R11 第 1 / 2 条）。"""
        if self._paper is None:
            ui_utils.info(self, "请先生成试卷。")
            return
        score = self._type_score_spin.value()

        def apply_all() -> None:
            for section in self._paper.sections:
                self._score_calculator.set_type_score(section, score)

        ok, _ = ui_utils.run_guarded(
            self, apply_all, success_message=f"已按题型设置单题分值 {score:g} 分"
        )
        if ok:
            self._render_paper(self._paper)
            self._update_total()

    def _on_apply_question_score(self) -> None:
        """为预览表中选中的单道题设置分值（需求 R11 第 1 条）。"""
        if self._paper is None:
            ui_utils.info(self, "请先生成试卷。")
            return
        row = self._result_table.currentRow()
        if row < 0 or row >= len(self._row_map):
            ui_utils.info(self, "请先在试卷预览中选择一道题目。")
            return
        section, question = self._row_map[row]
        score = self._question_score_spin.value()
        ok, _ = ui_utils.run_guarded(
            self,
            self._score_calculator.set_question_score,
            section,
            question.id,
            score,
            success_message=f"已为选中题设置分值 {score:g} 分",
        )
        if ok:
            self._render_paper(self._paper)
            self._update_total()

    # --------------------------------------------------------------- 导出

    def _on_export(self) -> None:
        """导出试卷为 MD / PDF（需求 R12 / R18）。

        导出目录固定在工作区根目录下的导出文件夹，不再由用户指定；
        PDF 由同一次导出的 Markdown 源文件转换而来。
        转换放到后台线程执行（用户需求：导出时界面不得无响应），
        主线程只负责显示进度与结果。
        """
        if self._paper is None:
            ui_utils.info(self, "请先生成试卷。")
            return
        if self._exporting:
            ui_utils.info(self, "正在导出，请稍候…")
            return
        self._exporting = True
        self._export_button.setEnabled(False)
        self._status.setText("正在导出…")
        fmt = self._format_combo.currentData()
        threading.Thread(
            target=self._export_in_background,
            args=(self._paper, fmt),
            name="paper-export",
            daemon=True,
        ).start()

    def _export_in_background(self, paper: Paper, fmt) -> None:
        """后台线程：执行导出并通过信号回报进度与结果（不触碰控件）。"""
        try:
            path = self._exporter.export(
                paper, fmt, None, ExportOptions(), self.export_progress.emit
            )
        except Exception as exc:  # noqa: BLE001 - 统一由主线程转成可读提示
            self.export_finished.emit(False, exc)
            return
        self.export_finished.emit(True, str(path))

    def _on_export_progress(self, message: str) -> None:
        """主线程：显示后台线程上报的导出进度。"""
        self._status.setText(message)

    def _on_export_finished(self, ok: bool, payload: object) -> None:
        """主线程：导出结束，恢复按钮并提示结果。"""
        self._exporting = False
        self._export_button.setEnabled(True)
        if ok:
            self._status.setText(f"已导出：{payload}")
            ui_utils.info(self, f"导出成功：\n{payload}")
            return
        self._status.setText(f"导出失败：{payload}")
        if isinstance(payload, DomainError):
            ui_utils.warning(self, str(payload))
        elif isinstance(payload, NotImplementedError):
            ui_utils.info(self, f"该功能尚未实现（框架占位）。\n\n{payload}")
        else:
            ui_utils.critical(self, f"导出失败：{payload}")
