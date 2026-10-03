"""题库管理视图：题目录入 / 编辑 / 删除 / 批量粘贴 / 检索（需求 R1 / R2 / R5 / R6）。

界面结构（内嵌三个子页签）：

- 录入 / 编辑：结构化表单（科目下拉选择 / 知识点 / 题型 / 选项 / 答案 / 解析 /
  难度 / 质量标记 / 题目图片），题型为解答题时切换为"参考答案"输入
- 批量粘贴：粘贴多题文本 -> 解析预览（"待修正"行标红）-> 确认批量入库
- 检索：按科目（下拉）/ 知识点 / 难度 / 题型过滤，结果展示使用次数与最近使用时间，
  并可对选中题目执行编辑 / 删除 / 质量标记

用户需求补充：

- 科目改为下拉选择（列表在"设置 -> 科目管理"中维护）
- 支持题目图片导入（复制到本地 images/ 目录并预览）
- "AI 辨识"按钮调用 AI 识别科目 / 知识点 / 题型 / 难度 / 质量标记 / 答案 / 解析，
  结果仅供参考，须由出题者人工确认后保存

所有业务操作经 ``app.application.question_service.QuestionService`` 完成；
异常经 ``ui_utils.run_guarded`` 统一提示而不崩溃。

依赖：PySide6.QtCore / QtGui / QtWidgets、app.container.Container、
      app.domain.entities.question、app.domain.enums、app.presentation.ui_utils
调用服务：app.application.question_service.QuestionService
被使用：app.presentation.main_window
"""

import re

from PySide6.QtCore import Qt, QStringListModel, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QCompleter,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.domain.entities.question import Option, Question, QuestionFilter
from app.domain.enums import Difficulty, DifficultySource, QualityFlag, QuestionType
from app.presentation import ui_utils

#: 图片预览的最大尺寸（像素）
PREVIEW_SIZE = (220, 160)


class QuestionBankView(QWidget):
    """题库管理视图：题目增删改查、批量粘贴与检索界面。"""

    #: 题库数据发生变化（新增 / 更新 / 删除 / 批量入库）时发出，
    #: 供主窗口刷新组卷视图的命中量统计。
    questions_changed = Signal()

    def __init__(self, container) -> None:
        """注入容器、构建界面并加载初始数据。"""
        super().__init__()
        self._container = container
        self._question_service = container.question_service

        self._editing_id: str | None = None
        self._paste_drafts: list[Question] = []
        self._search_results: list[Question] = []
        self._image_path: str | None = None

        self._build_ui()
        self.reload_subjects()
        self.reload_knowledge_points()
        self.reload_questions()

    # ------------------------------------------------------------------ 构建

    def _build_ui(self) -> None:
        """构建三个子页签。"""
        root = QVBoxLayout(self)
        self._inner_tabs = QTabWidget(self)
        self._inner_tabs.addTab(self._build_editor_tab(), "录入 / 编辑")
        self._inner_tabs.addTab(self._build_paste_tab(), "批量粘贴")
        self._inner_tabs.addTab(self._build_search_tab(), "检索")
        root.addWidget(self._inner_tabs)

    def _build_editor_tab(self) -> QWidget:
        """构建录入 / 编辑表单页。"""
        page = QWidget()
        form = QFormLayout(page)

        self._subject_combo = QComboBox()
        self._subject_combo.setMinimumWidth(140)
        self._subject_combo.setToolTip("科目只能从列表中选择；新增科目请到「设置 -> 科目管理」")
        self._knowledge_edit = QLineEdit()
        self._knowledge_edit.setPlaceholderText("多个知识点用逗号分隔，如：一元二次方程,因式分解")

        self._type_combo = QComboBox()
        for question_type in (
            QuestionType.SINGLE,
            QuestionType.MULTIPLE,
            QuestionType.FILL,
            QuestionType.SOLUTION,
        ):
            self._type_combo.addItem(
                ui_utils.QUESTION_TYPE_LABELS[question_type], question_type
            )
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)

        self._difficulty_combo = QComboBox()
        for difficulty in (
            Difficulty.PENDING,
            Difficulty.EASY,
            Difficulty.MEDIUM,
            Difficulty.HARD,
        ):
            self._difficulty_combo.addItem(
                ui_utils.DIFFICULTY_LABELS[difficulty], difficulty
            )

        self._quality_combo = QComboBox()
        for flag in (QualityFlag.NORMAL, QualityFlag.QUALITY, QualityFlag.LOW):
            self._quality_combo.addItem(ui_utils.QUALITY_LABELS[flag], flag)

        self._stem_edit = QPlainTextEdit()
        self._stem_edit.setPlaceholderText("必填：题目的完整题干")
        self._stem_edit.setFixedHeight(90)

        self._choice_container = self._build_options_group()
        self._solution_container = self._build_reference_group()
        self._image_container = self._build_image_group()

        self._solution_edit = QPlainTextEdit()
        self._solution_edit.setPlaceholderText("选填：解题思路 / 答案解析")
        self._solution_edit.setFixedHeight(70)

        form.addRow("科目 *", self._subject_combo)
        form.addRow("知识点", self._knowledge_edit)
        form.addRow("题型 *", self._type_combo)
        form.addRow("难度", self._difficulty_combo)
        form.addRow("质量标记", self._quality_combo)
        form.addRow("题干 *", self._stem_edit)
        form.addRow(self._choice_container)
        form.addRow(self._solution_container)
        form.addRow("解析（可选）", self._solution_edit)
        form.addRow(self._image_container)

        self._recognize_button = QPushButton("AI 辨识（科目/知识点/题型/难度/质量/答案/解析）")
        self._recognize_button.setToolTip(
            "调用已配置的 AI 服务识别题目字段并填入表单；结果仅供参考，请人工复核"
        )
        self._recognize_button.clicked.connect(self._on_recognize_clicked)
        self._no_solution_check = QCheckBox("AI 不输出解析")
        self._no_solution_check.setToolTip(
            "勾选后要求 AI 只给出答案，不生成解析（用户需求）"
        )
        self._recognize_note = QLabel(
            "AI 辨识结果仅供参考，必须人工复核后再保存。"
        )
        self._recognize_note.setWordWrap(True)
        self._recognize_row = QHBoxLayout()
        self._recognize_row.addWidget(self._recognize_button)
        self._recognize_row.addWidget(self._no_solution_check)
        self._recognize_row.addWidget(self._recognize_note, 1)
        recognize_holder = QWidget()
        recognize_holder.setLayout(self._recognize_row)
        form.addRow(recognize_holder)

        self._save_button = QPushButton("保存题目")
        self._save_button.clicked.connect(self._on_save_clicked)
        self._cancel_edit_button = QPushButton("取消编辑")
        self._cancel_edit_button.setToolTip("退出编辑状态并清空表单")
        self._cancel_edit_button.clicked.connect(self._on_cancel_edit)
        self._cancel_edit_button.setVisible(False)
        clear_button = QPushButton("清空表单")
        clear_button.clicked.connect(self._reset_form)
        button_row = QHBoxLayout()
        button_row.addWidget(self._save_button)
        button_row.addWidget(self._cancel_edit_button)
        button_row.addWidget(clear_button)
        button_row.addStretch(1)
        button_holder = QWidget()
        button_holder.setLayout(button_row)
        form.addRow(button_holder)

        self._on_type_changed()
        return page

    def _build_options_group(self) -> QGroupBox:
        """构建选择题选项编辑器（标号 + 内容，可增删行）。"""
        group = QGroupBox("选项（选择题，至少 2 项）")
        layout = QVBoxLayout(group)

        self._options_table = QTableWidget(0, 2)
        self._options_table.setHorizontalHeaderLabels(["标号", "内容"])
        self._options_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._options_table.verticalHeader().setVisible(False)
        self._options_table.setFixedHeight(150)
        layout.addWidget(self._options_table)

        add_button = QPushButton("添加选项")
        add_button.clicked.connect(lambda _checked=False: self._add_option_row())
        remove_button = QPushButton("删除选中选项")
        remove_button.clicked.connect(
            lambda _checked=False: self._remove_selected_option_rows()
        )
        row = QHBoxLayout()
        row.addWidget(add_button)
        row.addWidget(remove_button)
        row.addStretch(1)
        layout.addLayout(row)

        self._answer_edit = QLineEdit()
        self._answer_edit.setPlaceholderText(
            "单选填 1 个标号（如 A）；多选填多个（如 A,C）"
        )
        answer_row = QHBoxLayout()
        answer_row.addWidget(QLabel("答案 *"))
        answer_row.addWidget(self._answer_edit)
        layout.addLayout(answer_row)
        return group

    def _build_reference_group(self) -> QGroupBox:
        """构建填空题 / 解答题参考答案编辑器。"""
        group = QGroupBox("参考答案（填空题 / 解答题）")
        layout = QVBoxLayout(group)
        self._reference_edit = QPlainTextEdit()
        self._reference_edit.setPlaceholderText(
            "必填：填空题多个空用分号分隔（如：3；-1）；解答题填参考答案"
        )
        self._reference_edit.setFixedHeight(90)
        layout.addWidget(self._reference_edit)
        return group

    def _build_image_group(self) -> QGroupBox:
        """构建题目图片导入区（用户需求：题目图像的导入方式）。

        图片被复制到数据库同级 ``images/`` 目录，数据库保存相对路径；
        此处仅做导入、预览与移除，不参与 AI 辨识。
        """
        group = QGroupBox("题目图片（可选）")
        layout = QHBoxLayout(group)

        self._image_preview = QLabel("未选择图片")
        self._image_preview.setFixedSize(*PREVIEW_SIZE)
        self._image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_preview.setStyleSheet("border: 1px dashed #999; color: #666;")
        layout.addWidget(self._image_preview)

        column = QVBoxLayout()
        self._image_path_label = QLabel("—")
        self._image_path_label.setWordWrap(True)
        choose_button = QPushButton("选择图片…")
        choose_button.clicked.connect(self._on_choose_image)
        clear_button = QPushButton("移除图片")
        clear_button.clicked.connect(self._on_clear_image)
        column.addWidget(self._image_path_label)
        column.addWidget(choose_button)
        column.addWidget(clear_button)
        column.addStretch(1)
        layout.addLayout(column, 1)
        return group

    def _build_paste_tab(self) -> QWidget:
        """构建批量粘贴页。"""
        page = QWidget()
        layout = QVBoxLayout(page)

        hint = QLabel(
            "粘贴多道题目，以空行或“---”分隔；每条可用“科目：/知识点：/题型：/"
            "题干：/选项：/答案：/解析：”标注字段。点击“解析预览”后确认提交。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._paste_edit = QPlainTextEdit()
        self._paste_edit.setPlaceholderText("在此粘贴题目文本…")
        layout.addWidget(self._paste_edit)

        parse_button = QPushButton("解析预览")
        parse_button.clicked.connect(self._on_parse_paste)
        commit_button = QPushButton("确认提交")
        commit_button.clicked.connect(self._on_commit_paste)
        button_row = QHBoxLayout()
        button_row.addWidget(parse_button)
        button_row.addWidget(commit_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self._preview_table = QTableWidget(0, 6)
        self._preview_table.setHorizontalHeaderLabels(
            ["状态", "科目", "题型", "题干", "答案", "待修正"]
        )
        self._preview_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._preview_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self._preview_table)

        self._paste_status = QLabel("尚未解析")
        layout.addWidget(self._paste_status)
        return page

    def _build_search_tab(self) -> QWidget:
        """构建检索页：过滤条件 + 结果表 + 操作按钮。"""
        page = QWidget()
        layout = QVBoxLayout(page)

        filter_row = QHBoxLayout()
        self._search_subject = QComboBox()
        self._search_subject.setMinimumWidth(120)
        self._search_knowledge = QLineEdit()
        self._search_knowledge.setPlaceholderText("知识点（可空）")
        self._search_difficulty = QComboBox()
        self._search_difficulty.addItem("难度不限", None)
        for difficulty in (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD):
            self._search_difficulty.addItem(
                ui_utils.DIFFICULTY_LABELS[difficulty], difficulty
            )
        self._search_type = QComboBox()
        self._search_type.addItem("题型不限", None)
        for question_type in (
            QuestionType.SINGLE,
            QuestionType.MULTIPLE,
            QuestionType.FILL,
            QuestionType.SOLUTION,
        ):
            self._search_type.addItem(
                ui_utils.QUESTION_TYPE_LABELS[question_type], question_type
            )

        search_button = QPushButton("检索")
        search_button.clicked.connect(self._on_search)
        filter_row.addWidget(QLabel("科目"))
        filter_row.addWidget(self._search_subject)
        filter_row.addWidget(QLabel("知识点"))
        filter_row.addWidget(self._search_knowledge)
        filter_row.addWidget(self._search_difficulty)
        filter_row.addWidget(self._search_type)
        filter_row.addWidget(search_button)
        layout.addLayout(filter_row)

        self._result_table = QTableWidget(0, 9)
        self._result_table.setHorizontalHeaderLabels(
            [
                "题目 ID",
                "科目",
                "题型",
                "难度",
                "质量",
                "图片",
                "使用次数",
                "最近使用",
                "题干",
            ]
        )
        self._result_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._result_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._result_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._result_table.horizontalHeader().setSectionResizeMode(
            8, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self._result_table)

        action_row = QHBoxLayout()
        edit_button = QPushButton("编辑选中")
        edit_button.clicked.connect(self._on_edit_selected)
        delete_button = QPushButton("删除选中")
        delete_button.clicked.connect(self._on_delete_selected)
        quality_button = QPushButton("设为优质")
        quality_button.clicked.connect(
            lambda _checked=False: self._on_quality_selected(QualityFlag.QUALITY)
        )
        low_button = QPushButton("设为低质")
        low_button.clicked.connect(
            lambda _checked=False: self._on_quality_selected(QualityFlag.LOW)
        )
        normal_button = QPushButton("清除质量标记")
        normal_button.clicked.connect(
            lambda _checked=False: self._on_quality_selected(QualityFlag.NORMAL)
        )
        reanalyze_button = QPushButton("批量重析难度（AI）")
        reanalyze_button.setToolTip(
            "对选中题目（未选中则全库）重新调用 AI 分析难度；人工设置的难度不会被覆盖"
        )
        reanalyze_button.clicked.connect(self._on_reanalyze_selected)
        for button in (
            edit_button,
            delete_button,
            quality_button,
            low_button,
            normal_button,
            reanalyze_button,
        ):
            action_row.addWidget(button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self._search_status = QLabel("尚未加载")
        layout.addWidget(self._search_status)
        self._stats_label = QLabel("题库概览：—")
        layout.addWidget(self._stats_label)
        return page

    # ------------------------------------------------------------- 表单辅助

    def _add_option_row(self, key: str = "", text: str = "") -> None:
        """向选项表追加一行；未给标号时按 A/B/C… 自动分配。"""
        row = self._options_table.rowCount()
        self._options_table.insertRow(row)
        if not key:
            key = chr(ord("A") + row)
        self._options_table.setItem(row, 0, QTableWidgetItem(key))
        self._options_table.setItem(row, 1, QTableWidgetItem(text))

    def _remove_selected_option_rows(self) -> None:
        """删除选项表中选中的行。"""
        rows = sorted(
            {index.row() for index in self._options_table.selectedIndexes()},
            reverse=True,
        )
        for row in rows:
            self._options_table.removeRow(row)

    def _reset_options(self) -> None:
        """重置为 A-D 四个空选项。"""
        self._options_table.setRowCount(0)
        for key in ("A", "B", "C", "D"):
            self._add_option_row(key, "")

    def _collect_options(self) -> list[Option]:
        """从选项表读取选项，跳过完全空白的行。"""
        options: list[Option] = []
        for row in range(self._options_table.rowCount()):
            key_item = self._options_table.item(row, 0)
            text_item = self._options_table.item(row, 1)
            key = key_item.text().strip() if key_item else ""
            text = text_item.text().strip() if text_item else ""
            if key or text:
                options.append(Option(key=key, text=text))
        return options

    def _parse_knowledge(self) -> list[str]:
        """解析知识点输入（支持中英文逗号分隔）。"""
        raw = self._knowledge_edit.text().strip()
        return [
            part.strip()
            for part in raw.replace("，", ",").split(",")
            if part.strip()
        ]

    def _collect_answer(self, question_type: QuestionType) -> list[str]:
        """收集答案：选择题取标号列表，填空题 / 解答题取参考答案文本。"""
        if question_type in (QuestionType.SOLUTION, QuestionType.FILL):
            reference = self._reference_edit.toPlainText().strip()
            if question_type == QuestionType.FILL and reference:
                # 填空题多个空以分号 / 换行分隔，保留顺序
                parts = [
                    part.strip()
                    for part in re.split(r"[;；\n]+", reference)
                    if part.strip()
                ]
                return parts or [reference]
            return [reference] if reference else []
        raw = self._answer_edit.text().strip().replace("，", ",").replace(" ", ",")
        return [
            part.strip().upper()
            for part in raw.split(",")
            if part.strip()
        ]

    def _build_draft(self) -> Question:
        """根据当前表单构建题目草稿（未落库）。"""
        question_type = self._type_combo.currentData()
        difficulty = self._difficulty_combo.currentData()
        return Question(
            id=self._editing_id or "",
            subject=self._subject_combo.currentText().strip(),
            knowledge_points=self._parse_knowledge(),
            type=question_type,
            stem=self._stem_edit.toPlainText().strip(),
            options=(
                self._collect_options()
                if question_type in (QuestionType.SINGLE, QuestionType.MULTIPLE)
                else []
            ),
            answer=self._collect_answer(question_type),
            solution=self._solution_edit.toPlainText().strip() or None,
            difficulty=difficulty,
            difficulty_source=(
                DifficultySource.MANUAL
                if difficulty != Difficulty.PENDING
                else DifficultySource.AI
            ),
            quality_flag=self._quality_combo.currentData(),
            image_path=self._image_path,
        )

    def _build_patch(self, draft: Question) -> dict:
        """把草稿转换为 QuestionService.update_question 所需的补丁字典。"""
        return {
            "subject": draft.subject,
            "knowledge_points": draft.knowledge_points,
            "type": draft.type,
            "stem": draft.stem,
            "options": draft.options,
            "answer": draft.answer,
            "solution": draft.solution,
            "difficulty": draft.difficulty,
            "difficulty_source": draft.difficulty_source,
            "quality_flag": draft.quality_flag,
            "image_path": draft.image_path,
        }

    def _reset_form(self) -> None:
        """清空表单并回到"新增"模式。"""
        self._editing_id = None
        self._knowledge_edit.clear()
        self._stem_edit.clear()
        self._answer_edit.clear()
        self._reference_edit.clear()
        self._solution_edit.clear()
        if self._subject_combo.count():
            self._subject_combo.setCurrentIndex(0)
        ui_utils.select_combo_data(self._type_combo, QuestionType.SINGLE)
        ui_utils.select_combo_data(self._difficulty_combo, Difficulty.PENDING)
        ui_utils.select_combo_data(self._quality_combo, QualityFlag.NORMAL)
        self._reset_options()
        self._set_image(None)
        self._recognize_note.setText("AI 辨识结果仅供参考，必须人工复核后再保存。")
        self._save_button.setText("保存题目")
        self._cancel_edit_button.setVisible(False)
        self._on_type_changed()

    def _on_cancel_edit(self) -> None:
        """取消编辑：退出编辑状态并清空表单（用户需求）。"""
        if self._editing_id:
            self.show_status("已取消编辑，表单已清空")
        self._reset_form()

    def _on_type_changed(self) -> None:
        """题型切换时在"选项 + 答案"与"参考答案"之间切换。"""
        needs_options = self._type_combo.currentData() in (
            QuestionType.SINGLE,
            QuestionType.MULTIPLE,
        )
        self._choice_container.setVisible(needs_options)
        self._solution_container.setVisible(not needs_options)
        if needs_options and self._options_table.rowCount() == 0:
            self._reset_options()

    def _load_question_into_form(self, question: Question) -> None:
        """把已有题目载入表单进入编辑模式。"""
        self._editing_id = question.id
        index = self._subject_combo.findText(question.subject)
        if index < 0 and question.subject:
            self._subject_combo.addItem(question.subject, question.subject)
            index = self._subject_combo.findText(question.subject)
        if index >= 0:
            self._subject_combo.setCurrentIndex(index)
        self._knowledge_edit.setText("，".join(question.knowledge_points))
        self._stem_edit.setPlainText(question.stem)
        ui_utils.select_combo_data(self._type_combo, question.type)
        if question.type in (QuestionType.SOLUTION, QuestionType.FILL):
            separator = "；" if question.type == QuestionType.FILL else ""
            reference = separator.join(question.answer) if question.answer else ""
            self._reference_edit.setPlainText(reference)
            self._answer_edit.clear()
        else:
            self._answer_edit.setText(",".join(question.answer))
            self._reference_edit.clear()
            self._options_table.setRowCount(0)
            for option in question.options:
                self._add_option_row(option.key, option.text)
            if self._options_table.rowCount() == 0:
                self._reset_options()
        self._solution_edit.setPlainText(question.solution or "")
        ui_utils.select_combo_data(self._difficulty_combo, question.difficulty)
        ui_utils.select_combo_data(self._quality_combo, question.quality_flag)
        self._set_image(question.image_path)
        self._save_button.setText("更新题目")
        self._cancel_edit_button.setVisible(True)
        self._on_type_changed()
        self._inner_tabs.setCurrentIndex(0)

    # --------------------------------------------------------- 图片与 AI 辨识

    def _set_image(self, relative_path: str | None) -> None:
        """设置当前题目的图片相对路径并刷新预览。"""
        self._image_path = relative_path or None
        resolved = ui_utils.safe_call(
            self._container.image_store.resolve, self._image_path, default=None
        )
        if resolved is None:
            self._image_preview.setPixmap(QPixmap())
            self._image_preview.setText(
                "未选择图片" if not self._image_path else "图片文件缺失"
            )
        else:
            pixmap = QPixmap(str(resolved))
            if pixmap.isNull():
                self._image_preview.setPixmap(QPixmap())
                self._image_preview.setText("无法预览该图片")
            else:
                self._image_preview.setText("")
                self._image_preview.setPixmap(
                    pixmap.scaled(
                        PREVIEW_SIZE[0],
                        PREVIEW_SIZE[1],
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        self._image_path_label.setText(self._image_path or "—")

    def _on_choose_image(self) -> None:
        """选择本地图片并复制进 images/ 目录（用户需求：题目图片导入）。"""
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "选择题目图片",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.webp)",
        )
        if not path:
            return
        ok, relative = ui_utils.run_guarded(
            self, self._container.image_store.save, path
        )
        if ok and relative:
            self._set_image(relative)

    def _on_clear_image(self) -> None:
        """移除当前题目的图片引用（保留磁盘文件，避免误删历史图片）。"""
        self._set_image(None)

    def _on_recognize_clicked(self) -> None:
        """调用 AI 辨识题目字段并回填表单（用户需求；结果仅供参考）。"""
        stem = self._stem_edit.toPlainText().strip()
        if not stem:
            ui_utils.info(self, "请先填写题干，再使用 AI 辨识。")
            return
        if not self._question_service.ai_configured():
            ui_utils.warning(
                self,
                "AI 服务未配置，请先到「设置 -> AI 设置」填写接口地址、API Key 与模型名称。",
            )
            return
        ok, result = ui_utils.run_guarded(
            self,
            self._question_service.recognize_draft,
            stem,
            self._collect_options(),
            not self._no_solution_check.isChecked(),
        )
        if not ok or not result:
            return
        self._apply_recognition(result, include_solution=not self._no_solution_check.isChecked())

    def _apply_recognition(self, result: dict, include_solution: bool = True) -> None:
        """把 AI 辨识结果写入表单，并给出"仅供参考"的提示文字。"""
        notes = ["AI 辨识结果仅供参考，请人工复核后再保存。"]
        if not include_solution:
            notes.append("已按要求不生成解析。")

        subject = result.get("subject", "")
        index = self._subject_combo.findText(subject)
        if index >= 0 and subject:
            self._subject_combo.setCurrentIndex(index)
            notes.append(f"科目：{subject}")
        elif subject:
            notes.append(
                f"AI 建议科目「{subject}」不在科目列表中，请先在「设置 -> 科目管理」维护"
            )

        points = result.get("knowledge_points") or []
        if points:
            self._knowledge_edit.setText("，".join(points))

        question_type = result.get("question_type")
        if question_type is not None:
            ui_utils.select_combo_data(self._type_combo, question_type)
            self._on_type_changed()

        difficulty = result.get("difficulty")
        if difficulty is not None:
            ui_utils.select_combo_data(self._difficulty_combo, difficulty)

        quality = result.get("quality_flag")
        if quality is not None:
            ui_utils.select_combo_data(self._quality_combo, quality)

        answer = [str(item) for item in (result.get("answer") or [])]
        if question_type in (QuestionType.SOLUTION, QuestionType.FILL):
            if answer:
                self._reference_edit.setPlainText(
                    "；".join(answer) if question_type == QuestionType.FILL else answer[0]
                )
        elif answer:
            self._answer_edit.setText(",".join(answer))
            notes.append("答案若为选项标号，请确认选项内容已填写完整")

        solution = result.get("solution")
        if include_solution and solution:
            self._solution_edit.setPlainText(str(solution))

        notes.append("核对无误后点击保存即可入库。")
        self._recognize_note.setText(" ".join(notes))

    # --------------------------------------------------------------- 保存

    # --------------------------------------------------- 保存前校验与 AI 补全

    @staticmethod
    def _stem_or_options_problem(question: Question) -> str | None:
        """题干或选择题选项不全时返回提示文本（这两类必须由出题者填写）。"""
        if not question.stem:
            return "题干不能为空，请填写题干后再保存。"
        if question.type in (QuestionType.SINGLE, QuestionType.MULTIPLE):
            valid = [
                option
                for option in question.options
                if option.key.strip() and option.text.strip()
            ]
            if len(valid) < 2:
                return "选择题至少需要 2 个含标号与内容的选项，请补齐后再保存。"
        return None

    @staticmethod
    def _missing_labels(question: Question) -> list[str]:
        """列出除题干 / 选项之外缺失的必填信息（可由 AI 分析补全）。"""
        missing: list[str] = []
        if not question.subject:
            missing.append("科目")
        if not question.knowledge_points:
            missing.append("知识点")
        if not question.answer:
            missing.append(
                "参考答案"
                if question.type in (QuestionType.FILL, QuestionType.SOLUTION)
                else "答案"
            )
        if question.difficulty is Difficulty.PENDING:
            missing.append("难度")
        return missing

    def _ensure_required_fields(self, draft: Question) -> bool:
        """保存前检查必填信息；除题干 / 选项外信息不全时提供 AI 分析选项（用户需求）。

        :return: True 表示信息齐全（或已由 AI 补全）可继续保存
        """
        problem = self._stem_or_options_problem(draft)
        if problem:
            ui_utils.warning(self, problem)
            return False

        missing = self._missing_labels(draft)
        if not missing:
            return True

        if not self._question_service.ai_configured():
            ui_utils.warning(
                self,
                "以下信息不完整：" + "、".join(missing)
                + "。\n\nAI 服务未配置，请手工补齐后保存，或先在「设置 -> AI 设置」中配置。",
            )
            return False

        if not ui_utils.confirm_action(
            self,
            "以下信息不完整：" + "、".join(missing)
            + "。\n\n是否使用 AI 分析补全这些字段？（结果仅供参考，保存前请人工复核）",
            title="信息不完整",
            accept_text="AI 分析",
            reject_text="取消",
        ):
            return False

        include_solution = not self._no_solution_check.isChecked()
        ok, result = ui_utils.run_guarded(
            self,
            self._question_service.recognize_draft,
            draft.stem,
            draft.options,
            include_solution,
        )
        if not ok or not result:
            return False
        self._apply_recognition(result, include_solution=include_solution)

        remaining = self._missing_labels(self._build_draft())
        if remaining:
            ui_utils.warning(
                self,
                "AI 补全后仍缺少：" + "、".join(remaining) + "，请手工补齐后保存。",
            )
            return False
        return True

    def _on_save_clicked(self) -> None:
        """保存或更新题目（需求 R1）。

        保存前检查必填信息（用户需求）：
        - 题干（选择题含选项）不全时直接提示，必须由出题者补齐；
        - 其余信息（科目 / 知识点 / 答案 / 难度）不全时，弹出窗口提供
          "AI 分析"选项，由 AI 辨识补全后再保存（结果仅供参考）。
        """
        draft = self._build_draft()
        if not self._ensure_required_fields(draft):
            return
        draft = self._build_draft()
        if self._editing_id:
            ok, _ = ui_utils.run_guarded(
                self,
                self._question_service.update_question,
                self._editing_id,
                self._build_patch(draft),
                success_message="题目已更新",
            )
        else:
            ok, _ = ui_utils.run_guarded(
                self,
                self._question_service.create_question,
                draft,
                success_message="题目已保存，已触发 AI 难度分析（未配置则置为待确认）",
            )
        if ok:
            self._reset_form()
            self.reload_questions()
            self.reload_knowledge_points()
            self.questions_changed.emit()

    # ------------------------------------------------------------- 批量粘贴

    def _on_parse_paste(self) -> None:
        """解析粘贴文本为候选题并展示预览（需求 R2 第 1 / 2 / 4 条）。"""
        raw = self._paste_edit.toPlainText().strip()
        if not raw:
            ui_utils.info(self, "请先粘贴题目文本。")
            return
        ok, drafts = ui_utils.run_guarded(self, self._question_service.batch_parse, raw)
        if not ok:
            return
        self._paste_drafts = drafts or []
        self._render_paste_preview(self._paste_drafts)
        self._paste_status.setText(f"解析出 {len(self._paste_drafts)} 道候选题目")

    def _on_commit_paste(self) -> None:
        """批量写入确认后的候选题（需求 R2 第 3 条）。"""
        if not self._paste_drafts:
            ui_utils.info(self, "请先点击“解析预览”确认候选题。")
            return
        ok, saved = ui_utils.run_guarded(
            self,
            self._question_service.batch_commit,
            self._paste_drafts,
            success_message="候选题目已批量入库",
        )
        if not ok:
            return
        self._paste_drafts = []
        self._preview_table.setRowCount(0)
        self._paste_edit.clear()
        self._paste_status.setText(f"已入库 {len(saved or [])} 道题目")
        self.reload_questions()
        self.reload_knowledge_points()
        self.questions_changed.emit()

    def _render_paste_preview(self, drafts: list[Question]) -> None:
        """渲染候选题预览，待修正行标红（需求 R2 第 4 条）。"""
        self._preview_table.setRowCount(0)
        for draft in drafts:
            incomplete = self._is_incomplete(draft)
            row = self._preview_table.rowCount()
            self._preview_table.insertRow(row)
            values = [
                "待修正" if incomplete else "就绪",
                draft.subject,
                ui_utils.QUESTION_TYPE_LABELS.get(draft.type, ""),
                draft.stem,
                self._answer_text(draft),
                "是" if incomplete else "否",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if incomplete:
                    item.setForeground(QColor("red"))
                self._preview_table.setItem(row, column, item)

    @staticmethod
    def _answer_text(question: Question) -> str:
        """把答案列表渲染为可读文本。"""
        return "，".join(question.answer)

    @staticmethod
    def _is_incomplete(question: Question) -> bool:
        """判断候选题是否缺少必填字段（预览"待修正"依据，需求 R2 第 4 条）。"""
        if not question.subject or not question.stem:
            return True
        if question.type in (QuestionType.SOLUTION, QuestionType.FILL):
            return not (question.answer and question.answer[0].strip())
        return len(question.options) < 2 or not question.answer

    # --------------------------------------------------------------- 检索

    def _build_filter(self) -> QuestionFilter:
        """根据检索控件构建过滤器（空条件表示不过滤）。"""
        return QuestionFilter(
            subject=self._search_subject.currentData() or None,
            knowledge_point=self._search_knowledge.text().strip() or None,
            difficulty=self._search_difficulty.currentData(),
            question_type=self._search_type.currentData(),
        )

    def reload_subjects(self) -> None:
        """按设置中的科目列表重建录入与检索的科目下拉框（用户需求）。"""
        subjects = ui_utils.safe_call(self._question_service.list_subjects, default=None)
        if not subjects:
            return

        for combo, with_all in (
            (self._subject_combo, False),
            (self._search_subject, True),
        ):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            if with_all:
                combo.addItem("全部科目", None)
            for subject in subjects:
                combo.addItem(subject, subject)
            index = combo.findData(current)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

    def reload_knowledge_points(self) -> None:
        """按已有知识点刷新录入与检索的自动补全（用户需求：完成题库相关内容）。"""
        points = ui_utils.safe_call(
            self._question_service.list_knowledge_points, default=None
        ) or []
        for edit in (self._knowledge_edit, self._search_knowledge):
            completer = QCompleter(QStringListModel(list(points), edit), edit)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            edit.setCompleter(completer)

    def reload_questions(self) -> None:
        """静默重新检索（初始化与跨视图刷新使用，不弹窗）。"""
        questions = ui_utils.safe_call(
            self._question_service.search, self._build_filter(), default=None
        )
        if questions is None:
            self._search_results = []
            self._render_results([])
            self._search_status.setText("检索功能尚未实现（框架占位）")
            self._update_statistics()
            return
        self._search_results = questions
        self._render_results(questions)
        self._search_status.setText(f"共 {len(questions)} 道题")
        self._update_statistics()

    def _update_statistics(self) -> None:
        """刷新题库概览（总题数、各题型题量与待确认难度数）。"""
        stats = ui_utils.safe_call(self._question_service.statistics, default=None)
        if not stats:
            self._stats_label.setText("题库概览：—")
            return
        self._stats_label.setText(
            f"题库概览：共 {stats['total']} 道（单选 {stats['single']} / "
            f"多选 {stats['multiple']} / 填空 {stats['fill']} / "
            f"解答 {stats['solution']}），难度待确认 {stats['pending']} 道"
        )

    def _on_search(self) -> None:
        """检索按钮：按条件查询题库（需求 R6 第 1 条）。"""
        ok, questions = ui_utils.run_guarded(
            self, self._question_service.search, self._build_filter()
        )
        if not ok:
            return
        self._search_results = questions or []
        self._render_results(self._search_results)
        self._search_status.setText(f"共 {len(self._search_results)} 道题")

    def _render_results(self, questions: list[Question]) -> None:
        """渲染结果表，并补充使用次数与最近使用时间（需求 R6 第 4 条）。"""
        self._result_table.setRowCount(0)
        ids = [question.id for question in questions]
        usage = ui_utils.safe_call(
            self._container.usage_repository.get_many, ids, default={}
        ) or {}
        for question in questions:
            record = usage.get(question.id)
            last_used = (
                record.last_used_at.strftime("%Y-%m-%d %H:%M")
                if record is not None and record.last_used_at is not None
                else "从未"
            )
            row = self._result_table.rowCount()
            self._result_table.insertRow(row)
            values = [
                question.id,
                question.subject,
                ui_utils.QUESTION_TYPE_LABELS.get(question.type, ""),
                ui_utils.DIFFICULTY_LABELS.get(question.difficulty, ""),
                ui_utils.QUALITY_LABELS.get(question.quality_flag, ""),
                "有" if question.image_path else "—",
                str(record.use_count) if record is not None else "0",
                last_used,
                question.stem,
            ]
            for column, value in enumerate(values):
                self._result_table.setItem(row, column, QTableWidgetItem(str(value)))

    def _selected_question(self) -> Question | None:
        """返回结果表当前选中行对应的题目。"""
        row = self._result_table.currentRow()
        if row < 0 or row >= len(self._search_results):
            return None
        return self._search_results[row]

    def _selected_questions(self) -> list[Question]:
        """返回结果表中全部选中行对应的题目（支持批量操作）。"""
        rows = sorted({index.row() for index in self._result_table.selectedIndexes()})
        return [
            self._search_results[row]
            for row in rows
            if 0 <= row < len(self._search_results)
        ]

    # ------------------------------------------------------- 结果行操作

    def _on_edit_selected(self) -> None:
        """把选中题目载入编辑表单。"""
        question = self._selected_question()
        if question is None:
            ui_utils.info(self, "请先在检索结果中选择一道题目。")
            return
        self._load_question_into_form(question)

    def _on_delete_selected(self) -> None:
        """删除选中题目（支持多选批量，需求 R1 第 4 条）。"""
        questions = self._selected_questions()
        if not questions:
            ui_utils.info(self, "请先在检索结果中选择要删除的题目。")
            return
        if not ui_utils.confirm(
            self,
            f"确定删除选中的 {len(questions)} 道题目？删除后不再参与组卷，"
            "其题目图片也将一并清理。",
        ):
            return
        if len(questions) == 1:
            ok, _ = ui_utils.run_guarded(
                self,
                self._question_service.delete_question,
                questions[0].id,
                success_message="题目已删除",
            )
        else:
            ok, deleted = ui_utils.run_guarded(
                self,
                self._question_service.delete_questions,
                [question.id for question in questions],
            )
            if ok:
                self.show_status(f"已删除 {deleted} 道题目")
        if ok:
            self.reload_questions()
            self.reload_knowledge_points()
            self.questions_changed.emit()

    def _on_quality_selected(self, flag: QualityFlag) -> None:
        """设置选中题目的人工质量标记（支持多选，需求 R5 第 3 条 / R8 第 8 条）。"""
        questions = self._selected_questions()
        if not questions:
            ui_utils.info(self, "请先在检索结果中选择题目。")
            return
        ok, changed = ui_utils.run_guarded(
            self,
            self._question_service.set_quality_flag_many,
            [question.id for question in questions],
            flag,
        )
        if ok:
            self.show_status(
                f"已将 {changed} 道题的质量标记设为「{ui_utils.QUALITY_LABELS[flag]}」"
            )
            self.reload_questions()

    def _on_reanalyze_selected(self) -> None:
        """批量重析难度：选中题目优先，未选中则确认后处理全库（需求 R4 / R5）。"""
        questions = self._selected_questions()
        if questions:
            ids = [question.id for question in questions]
        else:
            ids = ui_utils.safe_call(
                self._question_service.all_question_ids, default=None
            ) or []
            if not ids:
                ui_utils.info(self, "题库为空，无可重析的题目。")
                return
            if not ui_utils.confirm(
                self, f"未选择题目，是否对全库 {len(ids)} 道题重新分析难度？"
            ):
                return
        ok, summary = ui_utils.run_guarded(
            self, self._question_service.reanalyze_difficulties, ids
        )
        if not ok or not summary:
            return
        self.show_status(
            f"难度重析完成：更新 {summary['updated']} 道，"
            f"跳过人工难度 {summary['skipped']} 道，失败 {summary['failed']} 道",
            8000,
        )
        self.reload_questions()

    def show_status(self, message: str, timeout_ms: int = 5000) -> None:
        """在检索页状态区显示临时消息（主窗口状态栏不可达时的本地反馈）。"""
        self._search_status.setText(message)
