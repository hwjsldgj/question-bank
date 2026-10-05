"""组卷视图：配置 / 配比统计 / 生成 / 分值编辑 / 导出（需求 R6-R12）。

界面结构（用户需求：按题型分组配置"知识点 × 难度"的题数）：

- 组卷科目：一次组卷只针对一个科目
- 四个题型分组（单选 / 多选 / 填空 / 解答）：保留原分组容器，内部改为配置表
  （序号 / 知识点 / 难度 / 数量）；配置行按当前科目的知识点 × 易中难自动生成，
  可改数量、改难度、删除行，只配数量、不勾选单题
- 配比统计预览：只显示统计表（题型 / 难度 / 知识点 / 配置题数 / 命中题数），
  不含题目正文，随上方配置实时刷新
- 生成试卷：调用 PaperComposer（题库不足按实际可提供数量出卷）
- 试卷预览与分值：原有展示与分值设置逻辑不变，表格高度为原 3 倍
- 导出：选择 TXT / PDF 与目标目录，调用 PaperExporter

数据流：上方配置 -> 中间统计实时更新（300ms 防抖）；下方预览在点击
"生成试卷"时按最新配置渲染。

依赖：PySide6.QtCore / QtWidgets、app.container.Container、
      app.domain.entities.{criteria,paper,question}、app.domain.entities.configs、
      app.domain.enums、app.presentation.ui_utils
调用服务：PaperComposer / ScoreCalculator / PaperExporter / QuestionService
被使用：app.presentation.main_window
"""

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
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

#: 配置行展开用的三级难度（组卷不接受"待确认"）
_DIFFICULTIES: tuple[Difficulty, ...] = (
    Difficulty.EASY,
    Difficulty.MEDIUM,
    Difficulty.HARD,
)

#: 单个题型配置表的最大高度（内部滚动，避免知识点过多时挤占下方预览）
_CONFIG_TABLE_HEIGHT = 160

#: 试卷预览表格高度 = 原始高度 × 本系数（用户需求：高度为原 3 倍）
_PREVIEW_HEIGHT_FACTOR = 3


class PaperGenerationView(QWidget):
    """组卷视图：按"知识点 × 难度"配置题数，题库优先、顺序取题。"""

    def __init__(self, container) -> None:
        """注入容器、构建界面并初始化配置行与统计。"""
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

        self._hit_timer = QTimer(self)
        self._hit_timer.setSingleShot(True)
        self._hit_timer.setInterval(300)
        self._hit_timer.timeout.connect(self.refresh_hit_counts)

        self._build_ui()
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
        layout.addWidget(QLabel("（配置行按该科目的知识点 × 难度自动生成）"))
        layout.addStretch(1)
        return group

    @staticmethod
    def _new_difficulty_combo() -> QComboBox:
        """构建只含三级难度的下拉框（组卷不接受"待确认"）。"""
        combo = QComboBox()
        for difficulty in _DIFFICULTIES:
            combo.addItem(ui_utils.DIFFICULTY_LABELS[difficulty], difficulty)
        ui_utils.select_combo_data(combo, Difficulty.MEDIUM)
        return combo

    @staticmethod
    def _new_subject_combo() -> QComboBox:
        """构建科目下拉框：科目只能从设置中维护的列表选择（用户需求）。"""
        combo = QComboBox()
        combo.setMinimumWidth(120)
        return combo

    def _build_type_group(self, question_type: QuestionType) -> QGroupBox:
        """构建单个题型分组：启用开关 + 配置表（序号 / 知识点 / 难度 / 数量）。"""
        title = _TYPE_GROUP_TITLES[question_type]
        group = QGroupBox(title)
        outer = QVBoxLayout(group)

        enabled = QCheckBox(f"启用{title}")
        enabled.toggled.connect(self._on_conditions_changed)
        outer.addWidget(enabled)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["序号", "知识点", "难度", "数量"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setMaximumHeight(_CONFIG_TABLE_HEIGHT)
        body_layout.addWidget(table)

        remove_button = QPushButton("删除选中行")
        remove_button.clicked.connect(
            lambda _checked=False, target=table: self._remove_selected_rows(target)
        )
        button_row = QHBoxLayout()
        button_row.addWidget(remove_button)
        button_row.addStretch(1)
        body_layout.addLayout(button_row)

        outer.addWidget(body)
        body.setEnabled(enabled.isChecked())

        self._type_tables[question_type] = table
        self._type_bodies[question_type] = body
        self._type_enabled[question_type] = enabled
        return group

    def _build_stats_group(self) -> QGroupBox:
        """构建配比统计预览区（只显示统计表，不显示题目正文）。"""
        group = QGroupBox("配比统计预览")
        layout = QVBoxLayout(group)

        self._stats_table = QTableWidget(0, 5)
        self._stats_table.setHorizontalHeaderLabels(
            ["题型", "难度", "知识点", "配置题数", "命中题数"]
        )
        self._stats_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._stats_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._stats_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._stats_table.setMinimumHeight(120)
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

    # --------------------------------------------------------------- 配置行

    @property
    def _subject(self) -> str:
        """当前全局科目（供配置行与条件构建使用）。"""
        return self._subject_combo.currentText().strip()

    def reload_subjects(self) -> None:
        """按设置中的科目列表重建科目下拉框，并按新科目重建配置行（用户需求）。"""
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
        self._sync_rows(force=True)
        self.refresh_hit_counts()

    def reload_knowledge_points(self) -> None:
        """按题库现有知识点补充配置行（新增知识点补行，已改数量与已删行不动）。"""
        self._sync_rows(force=False)
        self.refresh_hit_counts()

    def _sync_rows(self, force: bool) -> None:
        """同步四个题型配置表与知识点列表。

        :param force: True 时清空重建（科目变化）；False 时只为新知识点补行
        """
        points = ui_utils.safe_call(
            self._question_service.list_knowledge_points, self._subject, default=None
        ) or []
        for table in self._type_tables.values():
            if force:
                table.setRowCount(0)
            known = {
                table.item(row, 1).text() for row in range(table.rowCount())
            }
            for point in points:
                if point in known:
                    continue
                for difficulty in _DIFFICULTIES:
                    self._append_row(table, point, difficulty, 0)
            self._renumber(table)

    def _append_row(
        self, table: QTableWidget, point: str, difficulty: Difficulty, count: int
    ) -> None:
        """追加一条配置行（序号自动编号，难度与数量用控件承载）。"""
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        table.setItem(row, 1, QTableWidgetItem(point))

        combo = self._new_difficulty_combo()
        ui_utils.select_combo_data(combo, difficulty)
        combo.currentIndexChanged.connect(self._on_conditions_changed)
        table.setCellWidget(row, 2, combo)

        spin = QSpinBox()
        spin.setRange(0, 999)
        spin.setValue(count)
        spin.valueChanged.connect(self._on_conditions_changed)
        table.setCellWidget(row, 3, spin)

    @staticmethod
    def _renumber(table: QTableWidget) -> None:
        """重排配置表序号列（删除行后调用）。"""
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is not None:
                item.setText(str(row + 1))

    def _remove_selected_rows(self, table: QTableWidget) -> None:
        """删除配置表中选中的行（用户需求：配置行可手动删除）。"""
        rows = sorted({index.row() for index in table.selectedIndexes()}, reverse=True)
        for row in rows:
            table.removeRow(row)
        self._renumber(table)
        self._on_conditions_changed()

    def _read_rows(self, table: QTableWidget) -> list[tuple[str, Difficulty, int]]:
        """读取配置表的有效行：``(知识点, 难度, 数量)``。"""
        rows: list[tuple[str, Difficulty, int]] = []
        for row in range(table.rowCount()):
            point_item = table.item(row, 1)
            combo = table.cellWidget(row, 2)
            spin = table.cellWidget(row, 3)
            if point_item is None or combo is None or spin is None:
                continue
            difficulty = combo.currentData()
            if difficulty is None:
                continue
            rows.append(
                (point_item.text(), Difficulty(difficulty), int(spin.value()))
            )
        return rows

    def _on_subject_changed(self) -> None:
        """科目变化：按新科目的知识点重建配置行并刷新统计。"""
        self._sync_rows(force=True)
        self._on_conditions_changed()

    # ------------------------------------------------------------- 条件与统计

    def _on_conditions_changed(self) -> None:
        """配置变化：切换配置表可用性并触发统计防抖刷新。"""
        for question_type, enabled in self._type_enabled.items():
            self._type_bodies[question_type].setEnabled(enabled.isChecked())
        self._hit_timer.start()

    def refresh_hit_counts(self) -> None:
        """实时刷新配比统计表：配置题数 + 该组合的题库命中题数（需求 R6 第 2 条）。"""
        subject = self._subject
        rows: list[tuple[str, str, str, int, int | None]] = []
        for question_type in _TYPE_ORDER:
            if not self._type_enabled[question_type].isChecked():
                continue
            for point, difficulty, count in self._read_rows(
                self._type_tables[question_type]
            ):
                if count <= 0:
                    continue
                hits = ui_utils.safe_call(
                    self._question_service.count_available,
                    subject,
                    difficulty,
                    question_type,
                    [point] if point else [],
                    default=None,
                )
                rows.append(
                    (
                        ui_utils.QUESTION_TYPE_LABELS.get(question_type, ""),
                        ui_utils.DIFFICULTY_LABELS.get(difficulty, ""),
                        point,
                        count,
                        hits,
                    )
                )
        self._render_stats(rows)

    def _render_stats(self, rows: list[tuple[str, str, str, int, int | None]]) -> None:
        """把统计行写入配比统计表（只显示统计，不显示题目正文）。"""
        self._stats_table.setRowCount(0)
        for values in rows:
            row = self._stats_table.rowCount()
            self._stats_table.insertRow(row)
            texts = [
                values[0],
                values[1],
                values[2],
                str(values[3]),
                "—" if values[4] is None else str(values[4]),
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
            for point, difficulty, count in self._read_rows(
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
                        knowledge_points=[point] if point else [],
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
        self._sync_rows(force=True)

        for question_type in _TYPE_ORDER:
            items = self._items_of(criteria, question_type)
            enabled = self._type_enabled[question_type]
            enabled.blockSignals(True)
            enabled.setChecked(bool(items))
            enabled.blockSignals(False)
            self._type_bodies[question_type].setEnabled(bool(items))
            self._fill_rows(self._type_tables[question_type], items)

        self._on_conditions_changed()
        self.refresh_hit_counts()

    def _fill_rows(
        self, table: QTableWidget, items: list[TypeRequirement]
    ) -> None:
        """把历史条件的各条要求在配置表中回填（不存在组合时补行）。"""
        positions = {
            (table.item(row, 1).text(), table.cellWidget(row, 2).currentData()): row
            for row in range(table.rowCount())
            if table.item(row, 1) is not None
            and table.cellWidget(row, 2) is not None
            and table.cellWidget(row, 2).currentData() is not None
        }
        for item in items:
            for point in item.knowledge_points or [""]:
                row = positions.get((point, item.difficulty))
                if row is None:
                    self._append_row(table, point, item.difficulty, item.count)
                    positions[(point, item.difficulty)] = table.rowCount() - 1
                    continue
                spin = table.cellWidget(row, 3)
                if spin is not None:
                    spin.setValue(max(0, int(item.count)))
        self._renumber(table)

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
            ui_utils.warning(self, "请至少为一个「知识点 / 难度」配置大于 0 的题数。")
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
