"""题库管理视图：题目录入 / 编辑 / 删除 / 批量粘贴 / 检索（需求 R1 / R2 / R5 / R6）。

界面结构（内嵌三个子页签）：

- 录入 / 编辑：结构化表单（科目下拉选择 / 知识点板块 / 知识点 / 题型 / 选项 / 答案 / 解析 /
  难度 / 质量标记 / 题目图片），题型为解答题时切换为"参考答案"输入；
  选中科目后联动其知识点板块，选中板块后只补全该板块的细分知识点
- 批量粘贴：粘贴多题文本 -> 解析预览（"待修正"行标红）-> 确认批量入库
- 检索：按科目（下拉）/ 知识点 / 难度 / 题型过滤，结果展示使用次数与最近使用时间，
  并可对选中题目执行编辑 / 删除 / 质量标记 / 全库去重

用户需求补充：

- 科目改为下拉选择（列表在"设置 -> 科目管理"中维护）
- 支持题目图片导入（复制到本地 images/ 目录并预览）
- "AI 辨识"按模块勾选（科目 / 知识点 / 题型 / 难度 / 质量标记 / 答案 / 解析），
  只把勾选的模块拼进一次 AI 调用并返回，未勾选的字段不会被覆盖；
  结果仅供参考，须由出题者人工确认后保存
- 题库自动去重：题干归一化后相同即视为重复题。录入 / 编辑保存前提示并可"仍然保存"，
  批量粘贴入库前列出将要跳过的重复题，检索页另有"全库去重"扫描重复分组，
  确认后每组保留最早录入的一道并删除其余重复题

所有业务操作经 ``app.application.question_service.QuestionService`` 完成；
异常经 ``ui_utils.run_guarded`` 统一提示而不崩溃。

依赖：PySide6.QtCore / QtGui / QtWidgets、app.container.Container、
      app.domain.entities.question、app.domain.enums、app.presentation.ui_utils
调用服务：app.application.question_service.QuestionService
被使用：app.presentation.main_window
"""

import re

from PySide6.QtCore import Qt, QStringListModel, QModelIndex, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QCompleter,
    QDialog,
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
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.application.question_service import RECOGNIZE_MODULES, QuestionService
from app.config.settings import DEFAULT_SUBJECTS
from app.domain.entities.duplicate import DuplicateGroup
from app.domain.entities.question import (
    Option,
    Question,
    QuestionFilter,
    split_sections,
)
from app.domain.enums import (
    Difficulty,
    DifficultySource,
    QualityFlag,
    QuestionType,
    RecognizeModule,
)
from app.presentation import ui_utils

#: 图片预览的最大尺寸（像素）
PREVIEW_SIZE = (220, 160)

#: 检索结果表的数据列：题目 ID / 科目 / 知识点板块 / 知识点 / 题型 / 难度 / 质量 /
#: 图片 / 使用次数 / 最近使用 / 题干（用户需求：检索结果含知识点板块与知识点列）
RESULT_COLUMNS: tuple[str, ...] = (
    "题目 ID",
    "科目",
    "知识点板块",
    "知识点",
    "题型",
    "难度",
    "质量",
    "图片",
    "使用次数",
    "最近使用",
    "题干",
)


class _PasteDraftEditor(QDialog):
    """批量粘贴预览中双击一行后弹出的候选题编辑器。

    修改 / 删除仅作用于内存中的候选题草稿，不触及已入库题目；
    取消（关闭窗口）则丢弃本次改动。
    """

    def __init__(
        self,
        parent: QWidget,
        draft: Question,
        index: int,
        service: QuestionService,
        subjects: list[str],
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._draft = draft
        self._index = index
        self._deleted = False

        self.setWindowTitle(f"编辑第 {index} 道候选题")
        self.setMinimumWidth(560)
        self._build_ui()
        self._fill(draft)

    # ------------------------------------------------------------------ 构建

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()

        self._subject_combo = QComboBox()
        self._subject_combo.setMinimumWidth(120)
        self._subject_combo.currentIndexChanged.connect(self._reload_sections)
        # 一道题可属于多个知识点板块（用户需求）：可手写多个，逗号 / 顿号分隔
        self._section_combo = ui_utils.new_multi_combo("不限（可多个，用逗号分隔）", 120)
        self._section_combo.currentTextChanged.connect(self._reload_knowledge_completer)
        self._knowledge_edit = QLineEdit()
        self._knowledge_edit.setPlaceholderText("多个知识点用逗号分隔")
        self._knowledge_completer = QCompleter(
            QStringListModel([], self._knowledge_edit), self._knowledge_edit
        )
        self._knowledge_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._knowledge_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._knowledge_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._knowledge_edit.setCompleter(self._knowledge_completer)

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

        self._stem_edit = QPlainTextEdit()
        self._stem_edit.setFixedHeight(80)

        self._options_container = self._build_options_group()
        self._answer_edit = QLineEdit()
        self._answer_edit.setPlaceholderText("选择题填 A,B；填空 / 解答填参考答案")
        self._solution_edit = QPlainTextEdit()
        self._solution_edit.setPlaceholderText("选填：解析")
        self._solution_edit.setFixedHeight(60)

        form.addRow("科目 *", self._subject_combo)
        form.addRow("知识点板块", self._section_combo)
        form.addRow("知识点", self._knowledge_edit)
        form.addRow("题型 *", self._type_combo)
        form.addRow("题干 *", self._stem_edit)
        form.addRow(self._options_container)
        form.addRow("答案 *", self._answer_edit)
        form.addRow("解析", self._solution_edit)
        root.addLayout(form)

        button_row = QHBoxLayout()
        save_button = QPushButton("保存修改")
        save_button.clicked.connect(self.accept)
        delete_button = QPushButton("删除本题")
        delete_button.clicked.connect(self._on_delete)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(save_button)
        button_row.addWidget(delete_button)
        button_row.addStretch(1)
        button_row.addWidget(cancel_button)
        root.addLayout(button_row)

    def _build_options_group(self) -> QGroupBox:
        """构建选择题选项编辑器（标号 + 内容，可增删行）。"""
        group = QGroupBox("选项（选择题，至少 2 项）")
        layout = QVBoxLayout(group)

        self._options_table = QTableWidget(0, 2)
        self._options_table.setHorizontalHeaderLabels(["标号", "内容"])
        self._options_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        ui_utils.make_rows_compact(self._options_table)
        layout.addWidget(self._options_table)

        option_row = QHBoxLayout()
        self._add_option_button = QPushButton("添加选项")
        self._add_option_button.clicked.connect(self._add_option_row)
        self._remove_option_button = QPushButton("删除选中")
        self._remove_option_button.clicked.connect(self._remove_option_row)
        option_row.addWidget(self._add_option_button)
        option_row.addWidget(self._remove_option_button)
        option_row.addStretch(1)
        layout.addLayout(option_row)
        return group

    def _add_option_row(self, key: str = "", text: str = "") -> None:
        row = self._options_table.rowCount()
        self._options_table.insertRow(row)
        self._options_table.setItem(row, 0, QTableWidgetItem(key or self._next_option_key()))
        self._options_table.setItem(row, 1, QTableWidgetItem(text))
        self._options_table.setCurrentCell(row, 1)

    def _remove_option_row(self) -> None:
        row = self._options_table.currentRow()
        if row < 0:
            ui_utils.info(self, "请先在选项表中选择要删除的行。")
            return
        if self._options_table.rowCount() <= 2:
            ui_utils.info(self, "选择题至少保留 2 个选项。")
            return
        self._options_table.removeRow(row)

    def _next_option_key(self) -> str:
        """按 A/B/C… 自动分配下一个选项标号。"""
        return chr(ord("A") + self._options_table.rowCount())

    def _reload_sections(self) -> None:
        """按当前科目重建板块候选（保留已输入的多个板块文本）。"""
        subject = self._subject_combo.currentText().strip()
        sections = self._service.list_sections(subject)
        ui_utils.reload_combo_candidates(self._section_combo, list(sections))
        self._reload_knowledge_completer()

    def _reload_knowledge_completer(self) -> None:
        """按所选板块刷新知识点补全；未选板块则补全科目的全部知识点。

        一道题可属于多个板块（用户需求）：取全部所选板块的知识点并集。
        """
        selected = split_sections(self._section_combo.currentText())
        points = self._service.list_sections(self._subject_combo.currentText().strip())
        if selected:
            candidates = [
                point
                for section in selected
                for point in points.get(section, [])
            ]
        else:
            candidates = [p for group in points.values() for p in group]
        self._knowledge_completer.setModel(
            QStringListModel(list(dict.fromkeys(candidates)), self._knowledge_edit)
        )

    def _on_type_changed(self) -> None:
        """题型切换时在"选项 + 答案"与"参考答案"之间切换。"""
        needs_options = self._type_combo.currentData() in (
            QuestionType.SINGLE,
            QuestionType.MULTIPLE,
        )
        self._options_container.setVisible(needs_options)

    def _fill(self, question: Question) -> None:
        """把候选题写入表单控件。"""
        index = self._subject_combo.findText(question.subject)
        if index < 0 and question.subject:
            self._subject_combo.addItem(question.subject, question.subject)
            index = self._subject_combo.findText(question.subject)
        if index >= 0:
            self._subject_combo.setCurrentIndex(index)
            self._reload_sections()
        self._section_combo.setEditText(question.section)
        self._knowledge_edit.setText("，".join(question.knowledge_points))
        ui_utils.select_combo_data(self._type_combo, question.type)
        self._stem_edit.setPlainText(question.stem)
        self._options_table.setRowCount(0)
        for option in question.options:
            self._add_option_row(option.key, option.text)
        self._answer_edit.setText(
            ",".join(question.answer) if question.is_choice else "；".join(question.answer)
        )
        self._solution_edit.setPlainText(question.solution or "")

    def read(self) -> None:
        """把表单上的修改写回候选题草稿（不落库，用户需求）。"""
        self._draft.subject = self._subject_combo.currentText().strip()
        self._draft.section = "、".join(
            split_sections(self._section_combo.currentText())
        )
        self._draft.knowledge_points = self._parse_knowledge()
        self._draft.type = self._type_combo.currentData()
        self._draft.stem = self._stem_edit.toPlainText().strip()
        self._draft.options = [
            Option(
                key=self._options_table.item(row, 0).text().strip(),
                text=self._options_table.item(row, 1).text().strip(),
            )
            for row in range(self._options_table.rowCount())
            if self._options_table.item(row, 0) is not None
            and self._options_table.item(row, 1) is not None
        ]
        self._draft.answer = self._collect_answer()
        self._draft.solution = self._solution_edit.toPlainText().strip() or None

    def _parse_knowledge(self) -> list[str]:
        """解析知识点输入（支持中英文逗号、顿号与分号）。"""
        return [
            part.strip()
            for part in re.split(r"[,，、;；\s]+", self._knowledge_edit.text() or "")
            if part.strip()
        ]

    def _collect_answer(self) -> list[str]:
        """按题型收集答案：选择题取标号列表，其余取参考答案文本。"""
        raw = self._answer_edit.text().strip()
        if self._type_combo.currentData() in (
            QuestionType.SOLUTION,
            QuestionType.FILL,
        ):
            parts = [part.strip() for part in re.split(r"[;；\n]+", raw) if part.strip()]
            return parts or ([raw] if raw else [])
        return [
            part.strip().upper()
            for part in raw.replace("，", ",").replace(" ", ",").split(",")
            if part.strip()
        ]

    def was_deleted(self) -> bool:
        """用户是否点了"删除本题"。"""
        return self._deleted

    def _on_delete(self) -> None:
        if ui_utils.confirm(self, f"确定要删除第 {self._index} 道候选题吗？"):
            self._deleted = True
            self.reject()


class _DuplicateReviewDialog(QDialog):
    """全库去重预览：列出题干重复的题目分组，确认后删除多余项（用户需求）。

    每组保留最早录入的一道（标为"保留"），其余标为"删除"；取消则不做任何改动。
    """

    #: 预览表列：分组 / 处理 / 题目 ID / 科目 / 题型 / 难度 / 录入时间 / 题干
    COLUMNS: tuple[str, ...] = (
        "分组",
        "处理",
        "题目 ID",
        "科目",
        "题型",
        "难度",
        "录入时间",
        "题干",
    )

    def __init__(self, parent: QWidget, groups: list[DuplicateGroup]) -> None:
        super().__init__(parent)
        self._groups = list(groups)
        self.setWindowTitle(
            f"全库去重：{len(self._groups)} 组重复，"
            f"待删除 {self.duplicate_count()} 道"
        )
        self.setMinimumSize(960, 420)
        self._build_ui()

    def duplicate_count(self) -> int:
        """待删除的重复题总数（每组除保留项外的全部题目）。"""
        return sum(len(group.duplicates) for group in self._groups)

    def _build_ui(self) -> None:
        """构建说明文字 + 重复题清单 + 确认 / 取消按钮。"""
        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                "重复判定口径：题干归一化后完全相同（忽略空白、标点、全角半角"
                "与大小写差异）。\n"
                f"共 {len(self._groups)} 组、{self.duplicate_count()} 道重复题；"
                "每组保留最早录入的一道，其余在确认后删除。"
            )
        )
        table = QTableWidget(0, len(self.COLUMNS))
        table.setHorizontalHeaderLabels(list(self.COLUMNS))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(
            len(self.COLUMNS) - 1, QHeaderView.ResizeMode.Stretch
        )
        ui_utils.make_rows_compact(table)
        self._fill_table(table)
        root.addWidget(table)

        button_row = QHBoxLayout()
        delete_button = QPushButton(
            f"删除 {self.duplicate_count()} 道重复题（保留最早录入）"
        )
        delete_button.clicked.connect(self.accept)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(delete_button)
        button_row.addStretch(1)
        button_row.addWidget(cancel_button)
        root.addLayout(button_row)

    def _fill_table(self, table: QTableWidget) -> None:
        """按组渲染：保留项正常显示，待删除项标红。"""
        for number, group in enumerate(self._groups, start=1):
            for question in [group.keeper, *group.duplicates]:
                keep = question is group.keeper
                row = table.rowCount()
                table.insertRow(row)
                values = [
                    f"第 {number} 组",
                    "保留" if keep else "删除",
                    question.id,
                    question.subject,
                    ui_utils.QUESTION_TYPE_LABELS.get(question.type, ""),
                    ui_utils.DIFFICULTY_LABELS.get(question.difficulty, ""),
                    question.created_at.strftime("%Y-%m-%d %H:%M:%S")
                    if question.created_at
                    else "—",
                    question.stem,
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if not keep:
                        item.setForeground(QColor("#b00020"))
                    table.setItem(row, column, item)


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
        self._import_checked = False

        self._build_ui()
        self.reload_subjects()
        self.reload_knowledge_points()
        self.reload_questions()

    # ------------------------------------------------------------------ 构建

    def _build_ui(self) -> None:
        """构建三个子页签。"""
        root = QVBoxLayout(self)
        self._inner_tabs = QTabWidget(self)
        # 录入 / 批量粘贴：内容可能超过屏幕，各自包滚动
        self._inner_tabs.addTab(
            self._wrap_scroll(self._build_editor_tab()), "录入 / 编辑"
        )
        self._inner_tabs.addTab(
            self._wrap_scroll(self._build_paste_tab()), "批量粘贴"
        )
        # 检索：外层不滚动，表格内部自己滚动（用户需求）
        self._inner_tabs.addTab(self._build_search_tab(), "检索")
        root.addWidget(self._inner_tabs)

    @staticmethod
    def _wrap_scroll(widget: QWidget) -> QScrollArea:
        """给子页签包一层滚动区域（录入 / 批量粘贴内容可能超过屏幕）。"""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(widget)
        return area

    @staticmethod
    def _wrap_scroll(widget: QWidget) -> QScrollArea:
        """给子页签包一层滚动区域（录入 / 批量粘贴内容可能超过屏幕）。"""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(widget)
        return area

    def _build_editor_tab(self) -> QWidget:
        """构建录入 / 编辑表单页。"""
        page = QWidget()
        form = QFormLayout(page)

        self._subject_combo = QComboBox()
        self._subject_combo.setMinimumWidth(140)
        self._subject_combo.setToolTip("科目只能从列表中选择；新增科目请到「设置 -> 科目管理」")
        self._subject_combo.currentIndexChanged.connect(self._on_subject_changed)

        # 一道题可属于多个知识点板块（用户需求）：可手写多个，逗号 / 顿号分隔
        self._section_combo = ui_utils.new_multi_combo(
            "不限（可多个，用逗号分隔）", 140
        )
        self._section_combo.setToolTip(
            "一道题可属于多个知识点板块（用逗号分隔）；"
            "新增板块请到「设置 -> 知识点板块」"
        )
        self._section_combo.currentTextChanged.connect(self._on_section_changed)

        self._knowledge_edit = QLineEdit()
        self._knowledge_edit.setPlaceholderText("多个知识点用逗号分隔，如：一元二次方程,因式分解")
        self._knowledge_completer = QCompleter(
            QStringListModel([], self._knowledge_edit), self._knowledge_edit
        )
        self._knowledge_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._knowledge_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._knowledge_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._knowledge_edit.setCompleter(self._knowledge_completer)

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
        form.addRow("知识点板块", self._section_combo)
        form.addRow("知识点", self._knowledge_edit)
        form.addRow("题型 *", self._type_combo)
        form.addRow("难度", self._difficulty_combo)
        form.addRow("质量标记", self._quality_combo)
        form.addRow("题干 *", self._stem_edit)
        form.addRow(self._choice_container)
        form.addRow(self._solution_container)
        form.addRow("解析（可选）", self._solution_edit)
        form.addRow(self._image_container)

        # AI 辨识模块：出题者按需勾选，只请求所需字段，一次调用返回（用户需求）
        self._module_group = QGroupBox(
            "AI 辨识模块（按需勾选，一次调用返回全部勾选字段）"
        )
        module_layout = QVBoxLayout(self._module_group)
        module_row = QHBoxLayout()
        self._module_checks: dict[RecognizeModule, QCheckBox] = {}
        for module in RECOGNIZE_MODULES:
            check = QCheckBox(ui_utils.RECOGNIZE_MODULE_LABELS[module])
            check.setChecked(True)
            check.setToolTip(
                f"勾选后本次 AI 辨识会请求「{ui_utils.RECOGNIZE_MODULE_LABELS[module]}」，"
                "所有勾选项由同一次调用返回"
            )
            self._module_checks[module] = check
            module_row.addWidget(check)
        module_row.addStretch(1)
        module_layout.addLayout(module_row)

        self._recognize_button = QPushButton("AI 辨识选中模块")
        self._recognize_button.setToolTip(
            "调用已配置的 AI 服务识别勾选的模块并填入表单；结果仅供参考，请人工复核"
        )
        self._recognize_button.clicked.connect(self._on_recognize_clicked)
        self._recognize_note = QLabel(
            "AI 辨识结果仅供参考，必须人工复核后再保存。"
        )
        self._recognize_note.setWordWrap(True)
        recognize_row = QHBoxLayout()
        recognize_row.addWidget(self._recognize_button)
        recognize_row.addWidget(self._recognize_note, 1)
        module_layout.addLayout(recognize_row)
        form.addRow(self._module_group)

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
        ui_utils.make_rows_compact(self._options_table)
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
            "题干：/选项：/答案：/解析：”标注字段。点击“解析预览”后会自动逐项检查，"
            "非题干信息不完整时会弹窗询问是否让 AI 填充，确认无误再点“确认提交”。"
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
        self._preview_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._preview_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self._preview_table.doubleClicked.connect(self._on_preview_double_clicked)
        ui_utils.make_rows_compact(self._preview_table)
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
        self._search_subject.currentIndexChanged.connect(self._on_search_subject_changed)
        self._search_section = ui_utils.new_multi_combo(
            "不限（可多个，用逗号分隔）", 120
        )
        self._search_section.setToolTip(
            "按知识点板块过滤检索结果（可多个，命中任一板块即匹配）"
        )
        self._search_section.currentTextChanged.connect(
            self._reload_search_completer
        )
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
        filter_row.addWidget(QLabel("知识点板块"))
        filter_row.addWidget(self._search_section)
        filter_row.addWidget(QLabel("知识点"))
        filter_row.addWidget(self._search_knowledge)
        filter_row.addWidget(self._search_difficulty)
        filter_row.addWidget(self._search_type)
        filter_row.addWidget(search_button)
        layout.addLayout(filter_row)

        self._result_table = QTableWidget(0, len(RESULT_COLUMNS))
        self._result_table.setHorizontalHeaderLabels(list(RESULT_COLUMNS))
        self._result_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._result_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._result_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        # 题干列占满剩余宽度；行距收紧（用户需求）
        self._result_table.horizontalHeader().setSectionResizeMode(
            len(RESULT_COLUMNS) - 1, QHeaderView.ResizeMode.Stretch
        )
        ui_utils.make_rows_compact(self._result_table)
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
        local_reanalyze_button = QPushButton("批量重析难度（本地）")
        local_reanalyze_button.setToolTip(
            "对选中题目（未选中则全库）使用本地模型重新分析难度；离线可用，速度快"
        )
        local_reanalyze_button.clicked.connect(self._on_reanalyze_selected_local)
        dedup_button = QPushButton("全库去重")
        dedup_button.setToolTip(
            "扫描题干重复的题目（忽略空白、标点与全角半角差异），"
            "每组保留最早录入的一道，确认后删除其余重复题"
        )
        dedup_button.clicked.connect(self._on_deduplicate)
        for button in (
            edit_button,
            delete_button,
            quality_button,
            low_button,
            normal_button,
            reanalyze_button,
            local_reanalyze_button,
            dedup_button,
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
            section="、".join(split_sections(self._section_combo.currentText())),
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
            "section": draft.section,
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
        self._section_combo.setEditText("")
        self._reload_sections()
        self._reload_knowledge_completer()
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

    def _on_subject_changed(self) -> None:
        """切换科目时刷新板块下拉与知识点补全（用户需求：选科后联动板块与知识点）。"""
        self._reload_sections()
        self._reload_knowledge_completer()

    def _on_section_changed(self) -> None:
        """切换板块时刷新该板块的知识点补全候选。"""
        self._reload_knowledge_completer()

    def _reload_sections(self) -> None:
        """按当前科目重建板块候选（保留已输入的多个板块文本）。"""
        subject = self._subject_combo.currentText().strip()
        sections = ui_utils.safe_call(
            self._question_service.list_sections, subject, default=None
        ) or {}
        ui_utils.reload_combo_candidates(self._section_combo, list(sections))

    def _reload_knowledge_completer(self) -> None:
        """按所选板块刷新知识点的自动补全候选；未选板块则补全科目的全部知识点。

        一道题可属于多个板块（用户需求）：取全部所选板块的知识点并集。
        """
        selected = split_sections(self._section_combo.currentText())
        points = ui_utils.safe_call(
            self._question_service.list_sections,
            self._subject_combo.currentText().strip(),
            default=None,
        ) or {}
        if selected:
            candidates = [
                point for section in selected for point in points.get(section, [])
            ]
        else:
            candidates = [p for group in points.values() for p in group]
        model = QStringListModel(
            list(dict.fromkeys(candidates)), self._knowledge_edit
        )
        self._knowledge_completer.setModel(model)

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
            self._reload_sections()
        self._section_combo.setEditText(question.section)
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

    def _requested_modules(self) -> list[RecognizeModule]:
        """返回被勾选的 AI 辨识模块（用户需求：按需给出、一次返回）。"""
        return [
            module
            for module in RECOGNIZE_MODULES
            if self._module_checks[module].isChecked()
        ]

    def _wants_solution(self) -> bool:
        """是否要求 AI 给出解析（勾选了「解析」模块）。"""
        return self._module_checks[RecognizeModule.SOLUTION].isChecked()

    def _call_recognition(
        self,
        stem: str,
        options: list,
        include_solution: bool,
        modules: list,
    ):
        """调用一次 AI 辨识并返回报告（失败时已弹窗，返回 None）。

        使用 :meth:`QuestionService.recognize_draft_report`，以便拿到
        "AI 返回内容的问题清单"（用户需求：返回信息有问题时弹窗提示）。
        """
        ok, report = ui_utils.run_guarded(
            self,
            self._question_service.recognize_draft_report,
            stem,
            options,
            include_solution,
            True,
            modules,
        )
        return report if ok else None

    def _show_ai_issues(self, issues: list[str], title: str = "AI 返回内容有问题") -> None:
        """AI 返回信息出现问题时弹窗提示（用户需求）。

        :param issues: 问题清单（可为空，空则不弹窗）
        """
        if not issues:
            return
        ui_utils.warning(
            self,
            "AI 返回的内容存在以下问题：\n\n- "
            + "\n- ".join(issues)
            + "\n\n已按可识别的部分回填，无法识别的字段保持原值，请人工核对或手工补充。",
            title=title,
        )

    def _on_recognize_clicked(self) -> None:
        """按勾选的模块调用 AI 辨识并回填表单（用户需求；结果仅供参考）。"""
        stem = self._stem_edit.toPlainText().strip()
        if not stem:
            ui_utils.info(self, "请先填写题干，再使用 AI 辨识。")
            return
        modules = self._requested_modules()
        if not modules:
            ui_utils.info(self, "请至少勾选一个需要 AI 辨识的模块。")
            return
        if not self._question_service.ai_configured():
            ui_utils.warning(
                self,
                "AI 服务未配置，请先到「设置 -> AI 设置」填写接口地址、API Key 与模型名称。",
            )
            return
        include_solution = self._wants_solution()
        report = self._call_recognition(
            stem, self._collect_options(), include_solution, modules
        )
        if report is None:
            return
        if report.fields:
            self._apply_recognition(
                report.fields, include_solution=include_solution
            )
        self._show_ai_issues(report.issues, title="AI 辨识返回内容有问题")

    def _apply_recognition(self, result: dict, include_solution: bool = True) -> None:
        """把 AI 辨识结果写入表单，并给出"仅供参考"的提示文字。

        只回填结果中出现的字段（未勾选的模块不会被覆盖）。
        """
        notes = ["AI 辨识结果仅供参考，请人工复核后再保存。"]
        if not include_solution:
            notes.append("已按要求不生成解析。")

        subject = result.get("subject", "")
        index = self._subject_combo.findText(subject)
        if index >= 0 and subject:
            self._subject_combo.setCurrentIndex(index)
            self._reload_sections()
            notes.append(f"科目：{subject}")

        section = result.get("section")
        if section:
            # AI 可给出多个知识点板块（用户需求）：整段回填，用"、"分隔
            self._section_combo.setEditText("、".join(split_sections(section)))
            self._reload_knowledge_completer()
            notes.append(f"知识点板块：{section}")

        points = result.get("knowledge_points") or []
        if points:
            self._knowledge_edit.setText("，".join(points))

        question_type = (
            result["question_type"]
            if result.get("question_type") is not None
            else self._type_combo.currentData()
        )
        if result.get("question_type") is not None:
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
    def _module_label(question: Question, module: RecognizeModule) -> str:
        """模块在提示文案中的名称（填空题 / 解答题的 answer 称为"参考答案"）。"""
        if module is RecognizeModule.ANSWER and question.type in (
            QuestionType.FILL,
            QuestionType.SOLUTION,
        ):
            return "参考答案"
        return ui_utils.RECOGNIZE_MODULE_LABELS[module]

    @classmethod
    def _missing_labels(cls, question: Question) -> list[str]:
        """列出逐项检查中尚未填写的模块名称（可由 AI 填充，含题干与选项）。"""
        return [
            cls._module_label(question, module)
            for module in QuestionService.missing_modules(question)
        ]

    @classmethod
    def _required_missing_labels(cls, question: Question) -> list[str]:
        """列出尚未填写的必填模块名称（科目 / 知识点 / 答案，缺失时不许保存）。"""
        return [
            cls._module_label(question, module)
            for module in QuestionService.required_missing_modules(question)
        ]

    @classmethod
    def _check_lines(cls, question: Question) -> list[str]:
        """逐项检查文本（弹窗展示：每项当前取值与是否缺失）。

        用户需求：导入或修改时逐项检查弹窗提示。题干与选项也在检查之列，
        原文残缺时可由 AI 补全。
        """
        lines: list[str] = []
        stem_ok = bool((question.stem or "").strip())
        lines.append(f"题干：{'已填写' if stem_ok else '缺失'}（可由 AI 补全）")
        if question.type in (QuestionType.SINGLE, QuestionType.MULTIPLE):
            valid_options = [
                option
                for option in question.options
                if option.key.strip() and option.text.strip()
            ]
            lines.append(f"选项：{len(valid_options)} 项（至少 2 项，可由 AI 补全）")
        for module, filled in QuestionService.module_states(question):
            label = cls._module_label(question, module)
            if filled:
                lines.append(f"{label}：{cls._module_value(question, module)} ✓")
            elif module in QuestionService.REQUIRED_MODULES:
                lines.append(f"{label}：缺失 ✗（必填）")
            else:
                lines.append(f"{label}：缺失 ✗（选填）")
        return lines

    @staticmethod
    def _module_value(question: Question, module: RecognizeModule) -> str:
        """返回模块当前取值的可读文本（逐项检查展示用）。"""
        if module is RecognizeModule.SUBJECT:
            return question.subject
        if module is RecognizeModule.KNOWLEDGE_POINTS:
            return "，".join(question.knowledge_points)
        if module is RecognizeModule.QUESTION_TYPE:
            return ui_utils.QUESTION_TYPE_LABELS.get(question.type, str(question.type))
        if module is RecognizeModule.DIFFICULTY:
            return ui_utils.DIFFICULTY_LABELS.get(question.difficulty, "")
        if module is RecognizeModule.QUALITY_FLAG:
            return ui_utils.QUALITY_LABELS.get(question.quality_flag, "")
        if module is RecognizeModule.ANSWER:
            return "，".join(str(item) for item in question.answer)
        solution = (question.solution or "").strip()
        if len(solution) > 20:
            solution = solution[:20] + "…"
        return solution

    def _check_text(self, question: Question, title: str) -> str:
        """拼装逐项检查 + 询问文案。"""
        lines = self._check_lines(question)
        return (
            f"{title}\n\n"
            + "\n".join(lines)
            + "\n\n是否让 AI 填充上述缺失项（题干与选项除外）？"
            "AI 结果仅供参考，保存前请人工复核。"
        )

    def _ensure_required_fields(self, draft: Question) -> bool:
        """保存前逐项检查各模块，并询问是否让 AI 填充缺失项（用户需求）。

        题干与选项必须由出题者填写（AI 不生成）；科目 / 知识点 / 答案缺失时
        必须补齐后才能保存，难度 / 解析 / 质量标记缺失时允许直接保存。

        :return: True 表示可以继续保存
        """
        problem = self._stem_or_options_problem(draft)
        if problem:
            ui_utils.warning(self, problem)
            return False

        missing = self._question_service.missing_modules(draft)
        if not missing:
            return True

        required_labels = self._required_missing_labels(draft)
        text = self._check_text(draft, "保存前逐项检查：")
        if not self._question_service.ai_configured():
            if not required_labels:
                return True
            ui_utils.warning(
                self,
                f"{text}\n\nAI 服务未配置，请手工补齐后保存，"
                "或先在「设置 -> AI 设置」中配置。",
            )
            return False

        choice = ui_utils.choose_action(
            self,
            text,
            title="逐项检查：信息不完整",
            actions=[
                ("fill", "AI 填充缺失项"),
                ("manual", "手动补齐"),
                ("cancel", "取消"),
            ],
        )
        if choice == "fill":
            return self._ai_fill_missing(draft)
        if choice == "manual":
            if required_labels:
                ui_utils.warning(
                    self,
                    "以下必填项仍然缺失：" + "、".join(required_labels)
                    + "，请手工补齐后再保存。",
                )
                return False
            return True
        return False

    def _ai_fill_missing(self, draft: Question) -> bool:
        """用户确认后，按缺失模块调用一次 AI 并回填表单（结果仅供参考）。

        AI 返回内容有问题时同样弹窗提示（用户需求）。
        """
        include_solution = self._wants_solution()
        modules = self._question_service.missing_modules(draft)
        if not include_solution:
            modules = [
                module for module in modules if module is not RecognizeModule.SOLUTION
            ]
        if not modules:
            return True
        report = self._call_recognition(
            draft.stem, draft.options, include_solution, modules
        )
        if report is None:
            return False
        if report.fields:
            self._apply_recognition(report.fields, include_solution=include_solution)
        self._show_ai_issues(report.issues, title="AI 填充返回内容有问题")

        remaining = self._required_missing_labels(self._build_draft())
        if remaining:
            ui_utils.warning(
                self,
                "AI 填充后仍缺少必填项：" + "、".join(remaining)
                + "，请手工补齐后保存。",
            )
            return False
        return True

    def _confirm_difficulty_ai(self, draft: Question):
        """保存前让用户选择难度分析方式：AI / 本地 / 跳过。

        :return: "ai" / "local" / None（跳过）
        """
        if draft.difficulty is not Difficulty.PENDING:
            return None

        ai_ok = self._question_service.ai_configured()
        local_ok = self._question_service.local_difficulty_available()

        if not ai_ok and not local_ok:
            return None

        actions = []
        if ai_ok:
            actions.append(("ai", "AI 分析"))
        if local_ok:
            actions.append(("local", "本地模型分析"))
        actions.append(("skip", "跳过"))

        choice = ui_utils.choose_action(
            self,
            "该题难度仍为「待确认」。\n\n请选择分析方式：",
            title="难度分析",
            actions=actions,
        )
        if choice == "ai":
            return "ai"
        elif choice == "local":
            return "local"
        return None

    def _on_save_clicked(self) -> None:
        """保存或更新题目（需求 R1）。

        保存前逐项检查（用户需求）：
        - 题干（选择题含选项）不全时直接提示，必须由出题者补齐；
        - 其余模块（科目 / 知识点 / 题型 / 难度 / 质量标记 / 答案 / 解析）逐项
          列出填写状态，弹出窗口询问是否让 AI 填充缺失项（AI 填充 / 手动补齐 / 取消）；
        - 难度仍为「待确认」时再询问一次是否调用 AI 分析难度。
        所有 AI 调用都需用户在弹窗中确认。

        自动去重（用户需求）：题干与题库已有题目重复时提示并默认拦截，
        用户确认"仍然保存"后才以 ``allow_duplicate=True`` 入库。
        """
        draft = self._build_draft()
        if not self._ensure_required_fields(draft):
            return
        draft = self._build_draft()
        allow_duplicate = self._confirm_duplicate(draft)
        if allow_duplicate is None:
            return
        prefer = self._confirm_difficulty_ai(draft)
        analyze_difficulty = prefer is not None
        prefer = prefer or "auto"
        if self._editing_id:
            ok, _ = ui_utils.run_guarded(
                self,
                self._question_service.update_question,
                self._editing_id,
                self._build_patch(draft),
                analyze_difficulty,
                allow_duplicate,
                prefer,
                success_message="题目已更新",
            )
        else:
            ok, _ = ui_utils.run_guarded(
                self,
                self._question_service.create_question,
                draft,
                analyze_difficulty,
                allow_duplicate,
                prefer,
                success_message=(
                    "题目已保存"
                    if not analyze_difficulty
                    else "题目已保存，难度分析结果仅供参考"
                ),
            )
        if ok:
            self._reset_form()
            self.reload_questions()
            self.reload_knowledge_points()
            self.questions_changed.emit()

    def _confirm_duplicate(self, draft: Question) -> bool | None:
        """保存前的自动去重检查（用户需求）。

        :return: ``True`` 用户确认"仍然保存"（跳过查重）、``False`` 无重复题、
            ``None`` 命中重复题且用户取消保存
        """
        existing = ui_utils.safe_call(
            self._question_service.find_duplicate,
            draft,
            self._editing_id,
            default=None,
        )
        if existing is None:
            return False
        excerpt = " ".join((existing.stem or "").split())[:60]
        if ui_utils.confirm_action(
            self,
            "题库中已存在题干相同的题目：\n\n"
            f"题目 ID：{existing.id}\n科目：{existing.subject}\n题干：{excerpt}\n\n"
            "自动去重会忽略空白、标点、全角半角与大小写差异。\n是否仍然保存？",
            title="重复题目",
            accept_text="仍然保存",
            reject_text="取消",
        ):
            return True
        return None

    # ------------------------------------------------------------- 批量粘贴

    def _on_parse_paste(self) -> None:
        """解析粘贴文本为候选题并展示预览（需求 R2 第 1 / 2 / 4 条）。

        解析出候选题目后立即逐项检查（用户需求：导入时非题干信息不完整要有弹窗
        提示并询问是否 AI 填充），用户可当场让 AI 补全，预览随即刷新。
        """
        raw = self._paste_edit.toPlainText().strip()
        if not raw:
            ui_utils.info(self, "请先粘贴题目文本。")
            return
        ok, drafts = ui_utils.run_guarded(self, self._question_service.batch_parse, raw)
        if not ok:
            return
        self._paste_drafts = drafts or []
        self._import_checked = False
        self._render_paste_preview(self._paste_drafts)
        self._paste_status.setText(f"解析出 {len(self._paste_drafts)} 道候选题目")
        self._check_import_drafts()
        self._render_paste_preview(self._paste_drafts)

    def _on_commit_paste(self) -> None:
        """批量写入确认后的候选题（需求 R2 第 3 条）。

        入库前再检查一次（兜底）；若解析预览时已问过且必填项齐全，则不重复弹窗。

        自动去重（用户需求）：先给出去重预检结果并确认，重复题（与题库重复或
        本次粘贴内重复）在入库时被自动跳过。
        """
        if not self._paste_drafts:
            ui_utils.info(self, "请先点击“解析预览”确认候选题。")
            return
        if not self._import_checked:
            if not self._ensure_drafts_before_import():
                return
        elif any(
            self._question_service.required_missing_modules(draft)
            for draft in self._paste_drafts
        ):
            ui_utils.warning(
                self,
                "仍有候选题缺少必填项（科目 / 知识点 / 答案），"
                "请在「录入 / 编辑」中手工修正后重新解析预览再提交。",
            )
            return
        duplicates = ui_utils.safe_call(
            self._question_service.duplicate_drafts, self._paste_drafts, default=None
        ) or []
        if duplicates and not self._confirm_skip_duplicates(duplicates):
            return
        message = "候选题目已批量入库"
        if duplicates:
            message += f"（自动去重跳过 {len(duplicates)} 道重复题）"
        ok, saved = ui_utils.run_guarded(
            self,
            self._question_service.batch_commit,
            self._paste_drafts,
            success_message=message,
        )
        if not ok:
            return
        self._paste_drafts = []
        self._preview_table.setRowCount(0)
        self._paste_edit.clear()
        skipped = f"，跳过重复题 {len(duplicates)} 道" if duplicates else ""
        self._paste_status.setText(f"已入库 {len(saved or [])} 道题目{skipped}")
        self.reload_questions()
        self.reload_knowledge_points()
        self.questions_changed.emit()

    def _confirm_skip_duplicates(
        self, duplicates: list[tuple[int, Question, Question | None]]
    ) -> bool:
        """批量导入前的去重确认（用户需求）：列出将要跳过的重复题。

        :param duplicates: ``duplicate_drafts`` 的结果
        :return: 用户是否确认跳过这些重复题并继续入库
        """
        lines: list[str] = []
        for position, _draft, existing in duplicates[:10]:
            if existing is None:
                reason = "与本次粘贴中更靠前的同题干候选题重复"
            else:
                reason = f"与题库中已有题目重复（题目 ID：{existing.id}）"
            lines.append(f"第 {position} 题：{reason}")
        if len(duplicates) > len(lines):
            lines.append(f"…另有 {len(duplicates) - len(lines)} 道重复题")
        return ui_utils.confirm_action(
            self,
            f"自动去重：共 {len(self._paste_drafts)} 道候选题，"
            f"其中 {len(duplicates)} 道与已有题目题干相同（忽略空白、标点、"
            "全角半角与大小写差异）。\n\n"
            + "\n".join(lines)
            + "\n\n是否跳过这些重复题并入库其余候选题？",
            title="批量导入去重",
            accept_text="跳过重复题并入库",
            reject_text="取消",
        )

    def _incomplete_drafts(self) -> list[tuple[int, Question]]:
        """返回逐项检查中仍有缺失项的候选题 ``[(序号, 题目)]``。"""
        return [
            (index, draft)
            for index, draft in enumerate(self._paste_drafts, start=1)
            if self._question_service.missing_modules(draft)
        ]

    def _import_check_text(self, problems: list[tuple[int, Question]]) -> str:
        """拼装导入前逐项检查的提示文本（纯函数，便于测试）。"""
        lines: list[str] = []
        for index, draft in problems:
            labels = self._missing_labels(draft)
            required = self._required_missing_labels(draft)
            tag = "（必填）" if required else "（选填）"
            lines.append(f"第 {index} 题：缺 " + "、".join(labels) + tag)
        return (
            f"导入前逐项检查：共 {len(self._paste_drafts)} 道候选题，"
            f"其中 {len(problems)} 道信息不完整。\n\n"
            + "\n".join(lines)
            + "\n\n是否让 AI 填充上述缺失项（题干与选项也由 AI 补全）？"
            f"（共需调用 AI {len(problems)} 次，逐题一次返回；结果仅供参考）"
        )

    def _check_import_drafts(self) -> bool:
        """解析预览 / 确认提交时的逐项检查入口。

        只有检查通过（信息齐全、已由 AI 填充，或用户选择跳过 AI 且仅缺选填项）
        才记为"已询问"，避免在确认提交时重复弹同一个窗口。
        """
        result = self._ensure_drafts_before_import()
        self._import_checked = bool(result)
        return result

    def _ensure_drafts_before_import(self) -> bool:
        """导入前逐项检查候选题，并询问是否让 AI 填充缺失项（用户需求）。

        :return: True 表示可以继续入库
        """
        problems = self._incomplete_drafts()
        if not problems:
            return True

        required_any = any(
            self._question_service.required_missing_modules(draft)
            for _, draft in problems
        )
        text = self._import_check_text(problems)

        if not self._question_service.ai_configured():
            if not required_any:
                return True
            ui_utils.warning(
                self,
                f"{text}\n\nAI 服务未配置，请先在「录入 / 编辑」中手工修正后重新导入，"
                "或到「设置 -> AI 设置」配置 AI。",
            )
            return False

        choice = ui_utils.choose_action(
            self,
            text,
            title="逐项检查：候选题非题干信息不完整",
            actions=[
                ("fill", "AI 填充缺失项"),
                ("manual", "跳过 AI"),
                ("cancel", "取消"),
            ],
        )
        if choice == "fill":
            return self._ai_fill_drafts(problems)
        if choice == "manual":
            if required_any:
                ui_utils.warning(
                    self,
                    "仍有候选题缺少必填项（科目 / 知识点 / 答案），"
                    "请在「录入 / 编辑」中手工修正后重新解析预览再提交。",
                )
                return False
            return True
        return False

    def _ai_fill_drafts(self, problems: list[tuple[int, Question]]) -> bool:
        """用户确认后，逐题按缺失模块调用一次 AI 并回填候选题。

        AI 返回内容的问题汇总为一次弹窗（用户需求）。
        """
        include_solution = self._wants_solution()
        failures: list[str] = []
        issue_lines: list[str] = []
        for index, draft in problems:
            modules = self._question_service.missing_modules(draft)
            if not include_solution:
                modules = [
                    module
                    for module in modules
                    if module is not RecognizeModule.SOLUTION
                ]
            if not modules:
                continue
            report = self._call_recognition(
                draft.stem, draft.options, include_solution, modules
            )
            if report is None:
                failures.append(f"第 {index} 题")
                continue
            if report.issues:
                issue_lines.append(
                    f"第 {index} 题：" + "；".join(report.issues)
                )
            if report.fields:
                self._question_service.apply_recognition(
                    draft, report.fields, include_solution
                )

        if issue_lines:
            ui_utils.warning(
                self,
                "AI 返回的内容存在以下问题（已按可识别部分回填，请人工核对或手工补充）："
                "\n\n- " + "\n- ".join(issue_lines),
                title="AI 填充返回内容有问题",
            )

        remaining = [
            f"第 {index} 题（缺 " + "、".join(self._required_missing_labels(draft)) + "）"
            for index, draft in problems
            if self._question_service.required_missing_modules(draft)
        ]
        if failures or remaining:
            detail = ""
            if failures:
                detail += "\nAI 填充失败：" + "、".join(failures)
            if remaining:
                detail += "\n仍缺必填项：" + "；".join(remaining)
            ui_utils.warning(
                self,
                "以下候选题需在「录入 / 编辑」中手工修正后重新解析预览再提交："
                + detail,
            )
            return False
        self._render_paste_preview(self._paste_drafts)
        return True

    def _on_preview_double_clicked(self, index: QModelIndex) -> None:
        """双击预览行时打开该候选题的编辑对话框。"""
        row = index.row()
        if 0 <= row < len(self._paste_drafts):
            self._edit_paste_draft(row)

    def _edit_paste_draft(self, index: int) -> None:
        """在弹窗中编辑指定序号的候选题（修改/删除仅作用于内存草稿）。"""
        subjects = ui_utils.safe_call(self._question_service.list_subjects, default=None) or list(
            DEFAULT_SUBJECTS
        )
        dialog = _PasteDraftEditor(
            self, self._paste_drafts[index], index + 1, self._question_service, subjects
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            if dialog.was_deleted():
                del self._paste_drafts[index]
                self._paste_status.setText(f"已删除第 {index + 1} 道候选题")
            return
        dialog.read()
        self._render_paste_preview(self._paste_drafts)
        self._paste_status.setText(f"第 {index + 1} 道候选题已修改")

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

    @classmethod
    def _is_incomplete(cls, question: Question) -> bool:
        """判断候选题是否缺少必填字段（预览"待修正"依据，需求 R2 第 4 条）。"""
        if not question.stem:
            return True
        if question.type in (QuestionType.SINGLE, QuestionType.MULTIPLE):
            valid = [
                option
                for option in question.options
                if option.key.strip() and option.text.strip()
            ]
            if len(valid) < 2:
                return True
        return bool(QuestionService.required_missing_modules(question))

    # --------------------------------------------------------------- 检索

    def _build_filter(self) -> QuestionFilter:
        """根据检索控件构建过滤器（空条件表示不过滤）。"""
        return QuestionFilter(
            subject=self._search_subject.currentData() or None,
            section=self._search_section.currentText().strip() or None,
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

        # 科目列表变化后，检索区的板块候选与知识点补全需按新科目重建
        self._reload_search_sections()
        self._reload_search_completer()

    def reload_knowledge_points(self) -> None:
        """按已有知识点刷新录入与检索的自动补全（用户需求：完成题库相关内容）。"""
        # 检索区的板块候选与知识点补全随科目 / 板块联动（用户需求：检索可按板块过滤）
        self._reload_search_sections()
        self._reload_search_completer()

        # 录入页按当前科目重新联动板块与知识点（科目下拉刷新后需重建）
        self._reload_sections()
        self._reload_knowledge_completer()

    def _on_search_subject_changed(self) -> None:
        """检索科目切换：重建板块下拉并刷新知识点补全。"""
        self._reload_search_sections()
        self._reload_search_completer()

    def _reload_search_sections(self) -> None:
        """按检索科目重建检索区的板块候选（保留已输入文本）。"""
        subject = self._search_subject.currentData() or ""
        sections = ui_utils.safe_call(
            self._question_service.list_sections, subject, default=None
        ) or {}
        ui_utils.reload_combo_candidates(self._search_section, list(sections))

    def _reload_search_completer(self) -> None:
        """按检索科目 / 板块刷新检索框的知识点补全候选（多板块取并集）。"""
        subject = self._search_subject.currentData() or ""
        selected = split_sections(self._search_section.currentText())
        sections = ui_utils.safe_call(
            self._question_service.list_sections, subject, default=None
        ) or {}
        if selected:
            candidates = [
                point for name in selected for point in sections.get(name, [])
            ]
        else:
            candidates = [point for group in sections.values() for point in group]
        if not candidates:
            candidates = list(
                ui_utils.safe_call(
                    self._question_service.list_knowledge_points,
                    subject or None,
                    default=None,
                )
                or []
            )
        search_completer = QCompleter(
            QStringListModel(candidates, self._search_knowledge), self._search_knowledge
        )
        search_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        search_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._search_knowledge.setCompleter(search_completer)

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
                question.section,
                "、".join(question.knowledge_points),
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

    def _on_deduplicate(self) -> None:
        """全库去重：扫描题干重复的题目，确认后清理（用户需求：题库自动去重）。

        每组保留最早录入的一道；删除的题目同时清理图片并写入题库操作台账。
        """
        ok, groups = ui_utils.run_guarded(self, self._question_service.scan_duplicates)
        if not ok:
            return
        if not groups:
            ui_utils.info(
                self,
                "未发现重复题目（按题干判定，忽略空白、标点、全角半角与大小写差异）。",
            )
            return
        dialog = _DuplicateReviewDialog(self, groups)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        ok, report = ui_utils.run_guarded(
            self, self._question_service.deduplicate, groups, True
        )
        if not ok or report is None:
            return
        self.reload_questions()
        self.reload_knowledge_points()
        self.questions_changed.emit()
        # 状态文本放在刷新之后：reload_questions 会重写状态区为"共 N 道题"
        self.show_status(
            f"全库去重完成：清理 {report.group_count} 组，"
            f"删除 {report.deleted_count} 道重复题（每组保留最早录入的一道）",
            8000,
        )

    def _on_reanalyze_selected(self) -> None:
        """批量重析难度：先确认再调用 AI（用户需求：AI 使用需手动确认）。"""
        questions = self._selected_questions()
        if questions:
            ids = [question.id for question in questions]
            prompt = f"是否对选中的 {len(ids)} 道题重新调用 AI 分析难度？（人工难度不会被覆盖）"
        else:
            ids = ui_utils.safe_call(
                self._question_service.all_question_ids, default=None
            ) or []
            if not ids:
                ui_utils.info(self, "题库为空，无可重析的题目。")
                return
            prompt = (
                f"未选择题目，是否对全库 {len(ids)} 道题重新调用 AI 分析难度？"
                "（人工难度不会被覆盖）"
            )

        if not self._question_service.ai_configured():
            ui_utils.warning(
                self,
                "AI 服务未配置，无法重析难度；请先在「设置 -> AI 设置」中配置。",
            )
            return
        if not ui_utils.confirm_action(
            self,
            prompt,
            title="AI 难度分析",
            accept_text="AI 分析难度",
            reject_text="取消",
        ):
            return

        ok, summary = ui_utils.run_guarded(
            self, self._question_service.reanalyze_difficulties, ids, True
        )
        if not ok or not summary:
            return
        self.show_status(
            f"难度重析完成：更新 {summary['updated']} 道，"
            f"跳过人工难度 {summary['skipped']} 道，失败 {summary['failed']} 道",
            8000,
        )
        self.reload_questions()

    def _on_reanalyze_selected_local(self) -> None:
        """批量重析难度（本地模型）：不依赖远程 API。"""
        questions = self._selected_questions()
        if questions:
            ids = [question.id for question in questions]
            prompt = f"是否对选中的 {len(ids)} 道题用本地模型重新分析难度？（人工难度不会被覆盖）"
        else:
            ids = ui_utils.safe_call(
                self._question_service.all_question_ids, default=None
            ) or []
            if not ids:
                ui_utils.info(self, "题库为空，无可重析的题目。")
                return
            prompt = (
                f"未选择题目，是否对全库 {len(ids)} 道题用本地模型重新分析难度？"
                "（人工难度不会被覆盖）"
            )

        if not ui_utils.confirm_action(
            self,
            prompt,
            title="本地难度分析",
            accept_text="本地分析",
            reject_text="取消",
        ):
            return

        ok, summary = ui_utils.run_guarded(
            self,
            self._question_service.reanalyze_difficulties_local,
            ids,
        )
        if not ok or not summary:
            return
        self.show_status(
            f"本地难度重析完成：更新 {summary['updated']} 道，"
            f"跳过人工难度 {summary['skipped']} 道，失败 {summary['failed']} 道",
            8000,
        )
        self.reload_questions()

    def show_status(self, message: str, timeout_ms: int = 5000) -> None:
        """在检索页状态区显示临时消息（主窗口状态栏不可达时的本地反馈）。"""
        self._search_status.setText(message)
