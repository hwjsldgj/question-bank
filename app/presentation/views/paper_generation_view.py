"""组卷视图：条件配置 / 命中量统计 / 生成 / 分值编辑 / 导出（需求 R6-R12）。

界面结构：

- 选择题部分：启用开关 + 单选题 / 多选题各自的科目、难度、数量与命中量
- 解答题部分：启用开关 + 科目、难度、数量与命中量
- 生成试卷：调用 PaperComposer 完成"评分决策 -> 加权随机 -> AI 兜底"
- 试卷预览：分区 / 题型 / 题号 / 题干 / 难度 / 分值，支持按题型或逐题设置分值
- 导出：选择 TXT / PDF 与目标目录，调用 PaperExporter

命中量随条件输入实时刷新（需求 R6 第 2 / 3 条），使用 300ms 防抖定时器。

依赖：PySide6.QtCore / QtWidgets、app.container.Container、
      app.domain.entities.{criteria,paper,question}、app.domain.entities.configs、
      app.domain.enums、app.presentation.ui_utils
调用服务：PaperComposer / ScoreCalculator / PaperExporter / QuestionService
被使用：app.presentation.main_window
"""

import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.domain.entities.configs import ExportOptions
from app.domain.entities.criteria import PaperCriteria, TypeRequirement
from app.domain.entities.paper import Paper, Section
from app.domain.entities.question import Question
from app.domain.enums import Difficulty, ExportFormat, QuestionType
from app.presentation import ui_utils


class PaperGenerationView(QWidget):
    """组卷视图：题库优先、评分随机的组卷与导出界面。"""

    def __init__(self, container) -> None:
        """注入容器、构建界面并初始化命中量。"""
        super().__init__()
        self._container = container
        self._composer = container.paper_composer
        self._score_calculator = container.score_calculator
        self._exporter = container.paper_exporter
        self._question_service = container.question_service

        self._paper: Paper | None = None
        self._row_map: list[tuple[Section, Question]] = []

        self._hit_timer = QTimer(self)
        self._hit_timer.setSingleShot(True)
        self._hit_timer.setInterval(300)
        self._hit_timer.timeout.connect(self.refresh_hit_counts)

        self._build_ui()
        self.refresh_hit_counts()

    # ------------------------------------------------------------------ 构建

    def _build_ui(self) -> None:
        """构建组卷视图整体布局。"""
        root = QVBoxLayout(self)
        root.addWidget(self._build_choice_group())
        root.addWidget(self._build_solution_group())

        self._generate_button = QPushButton("生成试卷")
        self._generate_button.clicked.connect(self._on_generate)
        root.addWidget(self._generate_button)

        root.addWidget(self._build_result_group())
        root.addWidget(self._build_export_group())

        self._status = QLabel("就绪")
        root.addWidget(self._status)

    @staticmethod
    def _new_difficulty_combo() -> QComboBox:
        """构建只含三级难度的下拉框（组卷不接受"待确认"）。"""
        combo = QComboBox()
        for difficulty in (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD):
            combo.addItem(ui_utils.DIFFICULTY_LABELS[difficulty], difficulty)
        ui_utils.select_combo_data(combo, Difficulty.MEDIUM)
        return combo

    def _build_choice_group(self) -> QGroupBox:
        """构建选择题部分条件组（单选 / 多选）。"""
        group = QGroupBox("选择题部分")
        outer = QVBoxLayout(group)

        self._choice_enabled = QCheckBox("启用选择题部分")
        self._choice_enabled.toggled.connect(self._on_conditions_changed)
        outer.addWidget(self._choice_enabled)

        body = QWidget()
        form = QFormLayout(body)

        self._single_subject = QLineEdit()
        self._single_difficulty = self._new_difficulty_combo()
        self._single_count = QSpinBox()
        self._single_count.setRange(1, 999)
        self._single_count.setValue(5)
        self._single_hit = QLabel("命中：—")
        form.addRow("单选 · 科目", self._single_subject)
        form.addRow("单选 · 难度", self._single_difficulty)
        form.addRow("单选 · 数量", self._single_count)
        form.addRow("", self._single_hit)

        self._multiple_subject = QLineEdit()
        self._multiple_difficulty = self._new_difficulty_combo()
        self._multiple_count = QSpinBox()
        self._multiple_count.setRange(1, 999)
        self._multiple_count.setValue(3)
        self._multiple_hit = QLabel("命中：—")
        form.addRow("多选 · 科目", self._multiple_subject)
        form.addRow("多选 · 难度", self._multiple_difficulty)
        form.addRow("多选 · 数量", self._multiple_count)
        form.addRow("", self._multiple_hit)

        outer.addWidget(body)
        self._choice_body = body
        body.setEnabled(self._choice_enabled.isChecked())

        for subject in (self._single_subject, self._multiple_subject):
            subject.textChanged.connect(self._on_conditions_changed)
        for combo in (self._single_difficulty, self._multiple_difficulty):
            combo.currentIndexChanged.connect(self._on_conditions_changed)
        for spin in (self._single_count, self._multiple_count):
            spin.valueChanged.connect(self._on_conditions_changed)
        return group

    def _build_solution_group(self) -> QGroupBox:
        """构建解答题部分条件组。"""
        group = QGroupBox("解答题部分")
        outer = QVBoxLayout(group)

        self._solution_enabled = QCheckBox("启用解答题部分")
        self._solution_enabled.toggled.connect(self._on_conditions_changed)
        outer.addWidget(self._solution_enabled)

        body = QWidget()
        form = QFormLayout(body)
        self._solution_subject = QLineEdit()
        self._solution_difficulty = self._new_difficulty_combo()
        self._solution_count = QSpinBox()
        self._solution_count.setRange(1, 999)
        self._solution_count.setValue(2)
        self._solution_hit = QLabel("命中：—")
        form.addRow("解答题 · 科目", self._solution_subject)
        form.addRow("解答题 · 难度", self._solution_difficulty)
        form.addRow("解答题 · 数量", self._solution_count)
        form.addRow("", self._solution_hit)
        outer.addWidget(body)

        self._solution_body = body
        body.setEnabled(self._solution_enabled.isChecked())

        self._solution_subject.textChanged.connect(self._on_conditions_changed)
        self._solution_difficulty.currentIndexChanged.connect(
            self._on_conditions_changed
        )
        self._solution_count.valueChanged.connect(self._on_conditions_changed)
        return group

    def _build_result_group(self) -> QGroupBox:
        """构建试卷预览与分值编辑区。"""
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
        """构建导出区：格式、目录与导出按钮。"""
        group = QGroupBox("导出")
        layout = QHBoxLayout(group)

        self._format_combo = QComboBox()
        formats = ui_utils.safe_call(self._exporter.supported_formats, default=None)
        if not formats:
            formats = [ExportFormat.TXT, ExportFormat.PDF]
        for fmt in formats:
            self._format_combo.addItem(
                ui_utils.EXPORT_FORMAT_LABELS.get(fmt, str(fmt)), fmt
            )

        self._target_dir_edit = QLineEdit(os.getcwd())
        browse_button = QPushButton("浏览…")
        browse_button.clicked.connect(self._on_browse_dir)
        export_button = QPushButton("导出试卷")
        export_button.clicked.connect(self._on_export)

        layout.addWidget(QLabel("格式"))
        layout.addWidget(self._format_combo)
        layout.addWidget(QLabel("目录"))
        layout.addWidget(self._target_dir_edit, 1)
        layout.addWidget(browse_button)
        layout.addWidget(export_button)
        return group

    # ------------------------------------------------------------- 条件与命中量

    def _on_conditions_changed(self) -> None:
        """条件变化：切换编辑区可用性并触发命中量防抖刷新。"""
        self._choice_body.setEnabled(self._choice_enabled.isChecked())
        self._solution_body.setEnabled(self._solution_enabled.isChecked())
        self._hit_timer.start()

    def refresh_hit_counts(self) -> None:
        """实时更新三个题型的命中量（需求 R6 第 2 / 3 条）。"""
        self._update_hit(
            self._single_hit, self._single_subject, self._single_difficulty,
            QuestionType.SINGLE,
        )
        self._update_hit(
            self._multiple_hit, self._multiple_subject, self._multiple_difficulty,
            QuestionType.MULTIPLE,
        )
        self._update_hit(
            self._solution_hit, self._solution_subject, self._solution_difficulty,
            QuestionType.SOLUTION,
        )

    def _update_hit(
        self,
        label: QLabel,
        subject_edit: QLineEdit,
        difficulty_combo: QComboBox,
        question_type: QuestionType,
    ) -> None:
        """查询某题型条件的命中题数量并写入标签。"""
        subject = subject_edit.text().strip()
        if not subject:
            label.setText("命中：—（请填科目）")
            return
        difficulty = difficulty_combo.currentData()
        count = ui_utils.safe_call(
            self._question_service.count_available,
            subject,
            difficulty,
            question_type,
            default=None,
        )
        label.setText("命中：—" if count is None else f"命中：{count} 道")

    def _build_criteria(self) -> PaperCriteria:
        """根据界面控件构建组卷条件（需求 R7）。"""
        choice_enabled = self._choice_enabled.isChecked()
        solution_enabled = self._solution_enabled.isChecked()

        choice_items: list[TypeRequirement] = []
        if choice_enabled:
            choice_items.append(
                TypeRequirement(
                    question_type=QuestionType.SINGLE,
                    subject=self._single_subject.text().strip(),
                    difficulty=self._single_difficulty.currentData(),
                    count=self._single_count.value(),
                )
            )
            choice_items.append(
                TypeRequirement(
                    question_type=QuestionType.MULTIPLE,
                    subject=self._multiple_subject.text().strip(),
                    difficulty=self._multiple_difficulty.currentData(),
                    count=self._multiple_count.value(),
                )
            )

        solution_item: TypeRequirement | None = None
        if solution_enabled:
            solution_item = TypeRequirement(
                question_type=QuestionType.SOLUTION,
                subject=self._solution_subject.text().strip(),
                difficulty=self._solution_difficulty.currentData(),
                count=self._solution_count.value(),
            )

        return PaperCriteria(
            choice_enabled=choice_enabled,
            solution_enabled=solution_enabled,
            choice_items=choice_items,
            solution_item=solution_item,
        )

    def apply_criteria(self, criteria: PaperCriteria) -> None:
        """回填历史组卷条件（需求 R14 第 3 条：仅回填条件，题单重新生成）。"""
        self._choice_enabled.setChecked(criteria.choice_enabled)
        self._solution_enabled.setChecked(criteria.solution_enabled)
        for item in criteria.choice_items:
            if item.question_type == QuestionType.SINGLE:
                self._fill_requirement(
                    self._single_subject, self._single_difficulty,
                    self._single_count, item,
                )
            elif item.question_type == QuestionType.MULTIPLE:
                self._fill_requirement(
                    self._multiple_subject, self._multiple_difficulty,
                    self._multiple_count, item,
                )
        if criteria.solution_item is not None:
            self._fill_requirement(
                self._solution_subject, self._solution_difficulty,
                self._solution_count, criteria.solution_item,
            )
        self.refresh_hit_counts()

    @staticmethod
    def _fill_requirement(
        subject_edit: QLineEdit,
        difficulty_combo: QComboBox,
        count_spin: QSpinBox,
        requirement: TypeRequirement,
    ) -> None:
        """把单个题型要求回填到对应控件。"""
        subject_edit.setText(requirement.subject)
        ui_utils.select_combo_data(difficulty_combo, requirement.difficulty)
        count_spin.setValue(max(1, int(requirement.count)))

    # --------------------------------------------------------------- 生成

    def _on_generate(self) -> None:
        """执行组卷（需求 R7-R10 / R13）。"""
        criteria = self._build_criteria()
        if not criteria.choice_enabled and not criteria.solution_enabled:
            ui_utils.warning(self, "请至少启用「选择题部分」或「解答题部分」。")
            return
        ok, paper = ui_utils.run_guarded(
            self, self._composer.generate, criteria, success_message="试卷已生成"
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

    def _on_browse_dir(self) -> None:
        """选择导出目录。"""
        current = self._target_dir_edit.text().strip() or os.getcwd()
        directory = QFileDialog.getExistingDirectory(self, "选择导出目录", current)
        if directory:
            self._target_dir_edit.setText(directory)

    def _on_export(self) -> None:
        """导出试卷为 TXT / PDF（需求 R12 / R18）。"""
        if self._paper is None:
            ui_utils.info(self, "请先生成试卷。")
            return
        target_dir = self._target_dir_edit.text().strip()
        if not target_dir:
            ui_utils.warning(self, "请先选择导出目录。")
            return
        fmt = self._format_combo.currentData()
        ok, path = ui_utils.run_guarded(
            self,
            self._exporter.export,
            self._paper,
            fmt,
            target_dir,
            ExportOptions(),
        )
        if ok:
            ui_utils.info(self, f"导出成功：\n{path}")
