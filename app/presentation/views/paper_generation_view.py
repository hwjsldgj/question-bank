"""组卷视图：条件配置 / 命中量统计 / 生成 / 分值编辑 / 导出（需求 R6-R12）。

界面结构：

- 选择题部分：启用开关 + 单选题 / 多选题各自的科目、**指定知识点**、
  难度、数量与命中量
- 填空题 / 解答题部分：同上（各题型独立启用）
- 生成试卷：调用 PaperComposer 完成"评分决策 -> 加权随机 -> AI 兜底"
- 试卷预览：分区 / 题型 / 题号 / 题干 / 难度 / 分值，支持按题型或逐题设置分值
- 导出：选择 TXT / PDF 与目标目录，调用 PaperExporter

命中量随条件输入实时刷新（需求 R6 第 2 / 3 条），使用 300ms 防抖定时器；
指定的知识点参与命中统计与组卷条件（用户需求：组卷环节可指定知识点）。

依赖：PySide6.QtCore / QtWidgets、app.container.Container、
      app.domain.entities.{criteria,paper,question}、app.domain.entities.configs、
      app.domain.enums、app.presentation.ui_utils
调用服务：PaperComposer / ScoreCalculator / PaperExporter / QuestionService
被使用：app.presentation.main_window
"""

import os
import re

from PySide6.QtCore import Qt, QStringListModel, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
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
        self.reload_subjects()
        self.refresh_hit_counts()

    # ------------------------------------------------------------------ 构建

    def _build_ui(self) -> None:
        """构建组卷视图整体布局（单选 / 多选 / 填空 / 解答各自独立启用）。"""
        root = QVBoxLayout(self)
        root.addWidget(self._build_type_group(
            "单选题", "single", 5,
            {"enabled": "_single_enabled", "body": "_single_body",
             "subject": "_single_subject", "knowledge": "_single_knowledge",
             "difficulty": "_single_difficulty",
             "count": "_single_count", "hit": "_single_hit"},
        ))
        root.addWidget(self._build_type_group(
            "多选题", "multiple", 3,
            {"enabled": "_multiple_enabled", "body": "_multiple_body",
             "subject": "_multiple_subject", "knowledge": "_multiple_knowledge",
             "difficulty": "_multiple_difficulty",
             "count": "_multiple_count", "hit": "_multiple_hit"},
        ))
        root.addWidget(self._build_type_group(
            "填空题", "fill", 4,
            {"enabled": "_fill_enabled", "body": "_fill_body",
             "subject": "_fill_subject", "knowledge": "_fill_knowledge",
             "difficulty": "_fill_difficulty",
             "count": "_fill_count", "hit": "_fill_hit"},
        ))
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

    @staticmethod
    def _new_subject_combo() -> QComboBox:
        """构建科目下拉框：科目只能从设置中维护的列表选择（用户需求）。"""
        combo = QComboBox()
        combo.setMinimumWidth(120)
        return combo

    @staticmethod
    def _new_knowledge_combo() -> QComboBox:
        """构建知识点选择框（用户需求：组卷环节可指定知识点）。

        既可下拉选择已有知识点，也可直接输入；多个知识点用逗号 / 顿号分隔，
        留空表示不限。命中统计与组卷条件都按"命中其中任一知识点"处理。
        """
        combo = QComboBox()
        combo.setEditable(True)
        combo.setMinimumWidth(160)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        line_edit = combo.lineEdit()
        if line_edit is not None:
            line_edit.setPlaceholderText("不限（可多选，用逗号分隔）")
        return combo

    @staticmethod
    def parse_knowledge(text: str) -> list[str]:
        """把知识点输入文本拆分为知识点列表（支持中英文逗号、顿号与分号）。"""
        parts = [part.strip() for part in re.split(r"[,，、;；\s]+", text or "")]
        return [part for part in parts if part]

    def _build_type_group(
        self, title: str, prefix: str, default_count: int, attrs: dict
    ) -> QGroupBox:
        """构建某一题型独立的条件组（启用开关 + 科目 / 知识点 / 难度 / 数量 / 命中量）。

        单选与多选各自独立启用（用户需求：组卷时单选多选分开）。
        """
        group = QGroupBox(f"{title}部分")
        outer = QVBoxLayout(group)

        enabled = QCheckBox(f"启用{title}部分")
        enabled.toggled.connect(self._on_conditions_changed)
        outer.addWidget(enabled)

        body = QWidget()
        form = QFormLayout(body)
        subject = self._new_subject_combo()
        knowledge = self._new_knowledge_combo()
        difficulty = self._new_difficulty_combo()
        count = QSpinBox()
        count.setRange(1, 999)
        count.setValue(default_count)
        hit = QLabel("命中：—")
        form.addRow("科目", subject)
        form.addRow("指定知识点", knowledge)
        form.addRow("难度", difficulty)
        form.addRow("数量", count)
        form.addRow("", hit)
        outer.addWidget(body)
        body.setEnabled(enabled.isChecked())

        subject.currentIndexChanged.connect(self._on_conditions_changed)
        knowledge.currentTextChanged.connect(self._on_conditions_changed)
        difficulty.currentIndexChanged.connect(self._on_conditions_changed)
        count.valueChanged.connect(self._on_conditions_changed)

        setattr(self, attrs["enabled"], enabled)
        setattr(self, attrs["body"], body)
        setattr(self, attrs["subject"], subject)
        setattr(self, attrs["knowledge"], knowledge)
        setattr(self, attrs["difficulty"], difficulty)
        setattr(self, attrs["count"], count)
        setattr(self, attrs["hit"], hit)
        return group

    def _build_solution_group(self) -> QGroupBox:
        """构建解答题部分条件组（含指定知识点）。"""
        group = QGroupBox("解答题部分")
        outer = QVBoxLayout(group)

        self._solution_enabled = QCheckBox("启用解答题部分")
        self._solution_enabled.toggled.connect(self._on_conditions_changed)
        outer.addWidget(self._solution_enabled)

        body = QWidget()
        form = QFormLayout(body)
        self._solution_subject = self._new_subject_combo()
        self._solution_knowledge = self._new_knowledge_combo()
        self._solution_difficulty = self._new_difficulty_combo()
        self._solution_count = QSpinBox()
        self._solution_count.setRange(1, 999)
        self._solution_count.setValue(2)
        self._solution_hit = QLabel("命中：—")
        form.addRow("解答题 · 科目", self._solution_subject)
        form.addRow("解答题 · 指定知识点", self._solution_knowledge)
        form.addRow("解答题 · 难度", self._solution_difficulty)
        form.addRow("解答题 · 数量", self._solution_count)
        form.addRow("", self._solution_hit)
        outer.addWidget(body)

        self._solution_body = body
        body.setEnabled(self._solution_enabled.isChecked())

        self._solution_subject.currentIndexChanged.connect(self._on_conditions_changed)
        self._solution_knowledge.currentTextChanged.connect(self._on_conditions_changed)
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

    def reload_subjects(self) -> None:
        """按设置中的科目列表重建全部科目下拉框，并尽量保留当前选择（用户需求）。"""
        subjects = ui_utils.safe_call(
            self._question_service.list_subjects, default=None
        )
        if not subjects:
            return
        for combo in (
            self._single_subject,
            self._multiple_subject,
            self._fill_subject,
            self._solution_subject,
        ):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            for subject in subjects:
                combo.addItem(subject, subject)
            index = combo.findText(current)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)
        self.reload_knowledge_points()
        self.refresh_hit_counts()

    def reload_knowledge_points(self) -> None:
        """按题库已有知识点刷新四个指定知识点选择框（用户需求：组卷可指定知识点）。

        保留用户当前输入（含手写但题库中还不存在的知识点），只更新候选列表与补全。
        """
        points = ui_utils.safe_call(
            self._question_service.list_knowledge_points, default=None
        ) or []
        model = QStringListModel(list(points), self)
        for combo in (
            self._single_knowledge,
            self._multiple_knowledge,
            self._fill_knowledge,
            self._solution_knowledge,
        ):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(list(points))
            combo.setCurrentIndex(-1)
            combo.setEditText(current)
            combo.blockSignals(False)
            completer = QCompleter(model, combo)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            combo.setCompleter(completer)
        self.refresh_hit_counts()

    @staticmethod
    def _knowledge_of(combo: QComboBox) -> list[str]:
        """读取某条件组指定的知识点列表（空文本表示不限）。"""
        return PaperGenerationView.parse_knowledge(combo.currentText())

    # ------------------------------------------------------------- 条件与命中量

    def _on_conditions_changed(self) -> None:
        """条件变化：切换编辑区可用性并触发命中量防抖刷新。"""
        for body, enabled in (
            (self._single_body, self._single_enabled),
            (self._multiple_body, self._multiple_enabled),
            (self._fill_body, self._fill_enabled),
            (self._solution_body, self._solution_enabled),
        ):
            body.setEnabled(enabled.isChecked())
        self._hit_timer.start()

    def refresh_hit_counts(self) -> None:
        """实时更新四个题型的命中量（需求 R6 第 2 / 3 条，含指定知识点）。"""
        if self._single_subject.count() == 0:
            self.reload_subjects()
        self._update_hit(
            self._single_hit, self._single_subject, self._single_difficulty,
            QuestionType.SINGLE, self._single_knowledge,
        )
        self._update_hit(
            self._multiple_hit, self._multiple_subject, self._multiple_difficulty,
            QuestionType.MULTIPLE, self._multiple_knowledge,
        )
        self._update_hit(
            self._fill_hit, self._fill_subject, self._fill_difficulty,
            QuestionType.FILL, self._fill_knowledge,
        )
        self._update_hit(
            self._solution_hit, self._solution_subject, self._solution_difficulty,
            QuestionType.SOLUTION, self._solution_knowledge,
        )

    def _update_hit(
        self,
        label: QLabel,
        subject_edit: QComboBox,
        difficulty_combo: QComboBox,
        question_type: QuestionType,
        knowledge_combo: QComboBox | None = None,
    ) -> None:
        """查询某题型条件的命中题数量并写入标签（含指定知识点过滤）。"""
        subject = subject_edit.currentText().strip()
        if not subject:
            label.setText("命中：—（请先在设置中维护科目）")
            return
        difficulty = difficulty_combo.currentData()
        points = self._knowledge_of(knowledge_combo) if knowledge_combo else []
        count = ui_utils.safe_call(
            self._question_service.count_available,
            subject,
            difficulty,
            question_type,
            points,
            default=None,
        )
        text = "命中：—" if count is None else f"命中：{count} 道"
        if points:
            text += f"（知识点：{'、'.join(points)}）"
        label.setText(text)

    def _build_criteria(self) -> PaperCriteria:
        """根据界面控件构建组卷条件（需求 R7；含指定知识点）。"""
        single_enabled = self._single_enabled.isChecked()
        multiple_enabled = self._multiple_enabled.isChecked()
        fill_enabled = self._fill_enabled.isChecked()
        solution_enabled = self._solution_enabled.isChecked()

        choice_items: list[TypeRequirement] = []
        if single_enabled:
            choice_items.append(
                TypeRequirement(
                    question_type=QuestionType.SINGLE,
                    subject=self._single_subject.currentText().strip(),
                    difficulty=self._single_difficulty.currentData(),
                    count=self._single_count.value(),
                    knowledge_points=self._knowledge_of(self._single_knowledge),
                )
            )
        if multiple_enabled:
            choice_items.append(
                TypeRequirement(
                    question_type=QuestionType.MULTIPLE,
                    subject=self._multiple_subject.currentText().strip(),
                    difficulty=self._multiple_difficulty.currentData(),
                    count=self._multiple_count.value(),
                    knowledge_points=self._knowledge_of(self._multiple_knowledge),
                )
            )

        fill_item: TypeRequirement | None = None
        if fill_enabled:
            fill_item = TypeRequirement(
                question_type=QuestionType.FILL,
                subject=self._fill_subject.currentText().strip(),
                difficulty=self._fill_difficulty.currentData(),
                count=self._fill_count.value(),
                knowledge_points=self._knowledge_of(self._fill_knowledge),
            )

        solution_item: TypeRequirement | None = None
        if solution_enabled:
            solution_item = TypeRequirement(
                question_type=QuestionType.SOLUTION,
                subject=self._solution_subject.currentText().strip(),
                difficulty=self._solution_difficulty.currentData(),
                count=self._solution_count.value(),
                knowledge_points=self._knowledge_of(self._solution_knowledge),
            )

        return PaperCriteria(
            choice_enabled=single_enabled or multiple_enabled,
            solution_enabled=solution_enabled,
            choice_items=choice_items,
            solution_item=solution_item,
            fill_enabled=fill_enabled,
            fill_item=fill_item,
        )

    def apply_criteria(self, criteria: PaperCriteria) -> None:
        """回填历史组卷条件（需求 R14 第 3 条：仅回填条件，题单重新生成）。"""
        single = next(
            (i for i in criteria.choice_items if i.question_type == QuestionType.SINGLE),
            None,
        )
        multiple = next(
            (i for i in criteria.choice_items if i.question_type == QuestionType.MULTIPLE),
            None,
        )
        self._single_enabled.setChecked(single is not None)
        self._multiple_enabled.setChecked(multiple is not None)
        self._fill_enabled.setChecked(
            criteria.fill_enabled and criteria.fill_item is not None
        )
        self._solution_enabled.setChecked(
            criteria.solution_enabled and criteria.solution_item is not None
        )

        for item, combo, knowledge, difficulty, count in (
            (single, self._single_subject, self._single_knowledge,
             self._single_difficulty, self._single_count),
            (multiple, self._multiple_subject, self._multiple_knowledge,
             self._multiple_difficulty, self._multiple_count),
            (criteria.fill_item, self._fill_subject, self._fill_knowledge,
             self._fill_difficulty, self._fill_count),
            (criteria.solution_item, self._solution_subject, self._solution_knowledge,
             self._solution_difficulty, self._solution_count),
        ):
            if item is not None:
                self._fill_requirement(combo, knowledge, difficulty, count, item)
        self._on_conditions_changed()
        self.refresh_hit_counts()

    @staticmethod
    def _fill_requirement(
        subject_combo: QComboBox,
        knowledge_combo: QComboBox,
        difficulty_combo: QComboBox,
        count_spin: QSpinBox,
        requirement: TypeRequirement,
    ) -> None:
        """把单个题型要求回填到对应控件（科目不存在时临时补入，便于复用）。"""
        index = subject_combo.findText(requirement.subject)
        if index < 0 and requirement.subject:
            subject_combo.addItem(requirement.subject, requirement.subject)
            index = subject_combo.findText(requirement.subject)
        if index >= 0:
            subject_combo.setCurrentIndex(index)
        knowledge_combo.setEditText("，".join(requirement.knowledge_points or []))
        ui_utils.select_combo_data(difficulty_combo, requirement.difficulty)
        count_spin.setValue(max(1, int(requirement.count)))

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
        if not criteria.choice_enabled and not criteria.fill_enabled and not criteria.solution_enabled:
            ui_utils.warning(
                self, "请至少启用「单选题」「多选题」「填空题」或「解答题」中的一项。"
            )
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
