"""设置视图：AI 设置（含提示词）/ 评分与冷却 / 科目管理。

用户需求：历史与设置界面分开后，本视图只承担配置职责：

- AI 设置：base_url / api_key / model / 超时 / 重试（需求 R15），
  以及 AI 提示词的查看与修改：辨识总述 + 7 个模块化输出提示词
  （科目 / 知识点 / 题型 / 难度 / 质量标记 / 答案 / 解析，按需勾选、一次返回）
  + 难度分析 + AI 补题
- 评分与冷却：五项评分权重、冷却窗口计量方式与长度、抽样权重下限
  （需求 R8 第 7 条 / R13 第 4 条）
- 科目管理：维护可选科目列表（科目改为选择式录入，提供默认科目）
- 知识板块：维护"科目 -> 知识板块 -> 细分知识点"的三级结构，供录入页联动与
  AI 辨识分级使用

保存任意配置后发出 ``config_changed`` 信号，由主窗口刷新状态栏、
命中量与各视图的科目下拉框。

依赖：PySide6.QtCore / QtWidgets、app.container.Container、
      app.domain.entities.configs、app.domain.enums、app.presentation.ui_utils
调用服务：ConfigStore
被使用：app.presentation.main_window
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.config.settings import (
    DEFAULT_KNOWLEDGE_SECTIONS,
    DEFAULT_MODULE_PROMPTS,
    DEFAULT_PROMPT_CONFIG,
    DEFAULT_SUBJECTS,
)
from app.domain.entities.configs import AIConfig, PromptConfig, ScoringConfig
from app.domain.entities.knowledge_section import KnowledgeSection
from app.domain.enums import CooldownMode, RecognizeModule
from app.presentation import ui_utils


class SettingsView(QWidget):
    """设置视图：AI 配置与提示词、评分与冷却、科目管理。"""

    #: 配置保存后发出，供主窗口刷新 AI 状态、命中量与科目下拉框。
    config_changed = Signal()

    def __init__(self, container) -> None:
        """注入容器、构建界面并加载全部配置。"""
        super().__init__()
        self._container = container
        self._config_store = container.config_store

        self._build_ui()
        self._load_ai_config()
        self._load_prompt_config()
        self._load_scoring_config()
        self._load_subjects()
        self._load_sections()

    # ------------------------------------------------------------------ 构建

    def _build_ui(self) -> None:
        """构建三个设置页签。"""
        root = QVBoxLayout(self)
        self._inner_tabs = QTabWidget(self)
        self._inner_tabs.addTab(self._build_ai_tab(), "AI 设置")
        self._inner_tabs.addTab(self._build_scoring_tab(), "评分与冷却")
        self._inner_tabs.addTab(self._build_subject_tab(), "科目管理")
        self._inner_tabs.addTab(self._build_sections_tab(), "知识板块")
        root.addWidget(self._inner_tabs)

    def _build_ai_tab(self) -> QWidget:
        """构建 AI 设置页：接口参数 + 提示词编辑（需求 R15 / 用户需求）。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()

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

        save_ai_button = QPushButton("保存 AI 配置")
        save_ai_button.clicked.connect(self._on_save_ai)
        form.addRow(save_ai_button)

        self._ai_status = QLabel("")
        form.addRow(self._ai_status)
        layout.addLayout(form)

        layout.addWidget(
            QLabel(
                "提示词修改（可用占位符：辨识总述 {subjects} {stem} {options} {modules}；"
                "模块提示词 {subjects}；补题 {subject} {knowledge_points} {type} "
                "{difficulty} {count}）"
            )
        )

        self._recognize_prompt = self._new_prompt_edit()
        self._supplement_prompt = self._new_prompt_edit()
        prompt_form = QFormLayout()
        prompt_form.addRow("AI 辨识总述提示词", self._recognize_prompt)

        # 模块化输出提示词：每个字段一段，AI 辨识时只拼装被勾选的模块（用户需求）
        modules_group = QGroupBox("AI 辨识模块提示词（按需勾选模块，一次调用返回）")
        modules_form = QFormLayout(modules_group)
        self._module_prompts: dict[str, QPlainTextEdit] = {}
        for module in RecognizeModule:
            edit = self._new_prompt_edit(height=64)
            self._module_prompts[module.value] = edit
            modules_form.addRow(ui_utils.RECOGNIZE_MODULE_LABELS[module], edit)
        modules_note = QLabel(
            "「难度」模块提示词同时用于 AI 辨识与入库后的难度分析（含批量重析），"
            "难度只在此处维护一处，不再单独设置难度提示词。"
        )
        modules_note.setWordWrap(True)
        modules_form.addRow(modules_note)
        layout.addLayout(prompt_form)
        layout.addWidget(modules_group)

        other_form = QFormLayout()
        other_form.addRow("AI 补题提示词", self._supplement_prompt)
        layout.addLayout(other_form)

        prompt_row = QHBoxLayout()
        save_prompt_button = QPushButton("保存提示词")
        save_prompt_button.clicked.connect(self._on_save_prompt)
        reset_prompt_button = QPushButton("恢复默认提示词")
        reset_prompt_button.clicked.connect(
            lambda _checked=False: self._fill_prompt_form(DEFAULT_PROMPT_CONFIG)
        )
        prompt_row.addWidget(save_prompt_button)
        prompt_row.addWidget(reset_prompt_button)
        prompt_row.addStretch(1)
        layout.addLayout(prompt_row)
        layout.addStretch(1)
        return page

    @staticmethod
    def _new_prompt_edit(height: int = 90) -> QPlainTextEdit:
        """构建提示词编辑框。"""
        edit = QPlainTextEdit()
        edit.setFixedHeight(height)
        edit.setPlaceholderText("在此修改提示词，保存后用于后续 AI 调用")
        return edit

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

    def _build_subject_tab(self) -> QWidget:
        """构建科目管理页（用户需求：科目只能从列表中选，新科目在此维护）。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(
            QLabel(
                "科目列表用于题库录入、检索与组卷的科目下拉框；"
                "只能从列表中选择，请在此新增或删除科目。"
            )
        )

        self._subject_list = QListWidget()
        layout.addWidget(self._subject_list)

        edit_row = QHBoxLayout()
        self._subject_input = QLineEdit()
        self._subject_input.setPlaceholderText("输入新科目名称，如：信息技术")
        add_button = QPushButton("添加")
        add_button.clicked.connect(self._on_add_subject)
        remove_button = QPushButton("删除选中")
        remove_button.clicked.connect(self._on_remove_subject)
        edit_row.addWidget(self._subject_input, 1)
        edit_row.addWidget(add_button)
        edit_row.addWidget(remove_button)
        layout.addLayout(edit_row)

        button_row = QHBoxLayout()
        save_button = QPushButton("保存科目列表")
        save_button.clicked.connect(self._on_save_subjects)
        default_button = QPushButton("恢复默认科目")
        default_button.clicked.connect(self._on_reset_subjects)
        button_row.addWidget(save_button)
        button_row.addWidget(default_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self._subject_status = QLabel("")
        layout.addWidget(self._subject_status)
        return page

    def _build_sections_tab(self) -> QWidget:
        """构建知识板块页（用户需求：手动导入时提供板块与对应知识点细分）。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(
            QLabel(
                "知识板块是科目与知识点之间的中间层级：录入时先选科目、再选板块，"
                "最后从该板块的细分知识点中选取；AI 辨识也会先按板块分级、再细化知识点。"
            )
        )

        # 科目：决定左右两栏的数据范围
        subject_row = QHBoxLayout()
        subject_row.addWidget(QLabel("科目"))
        self._section_subject_combo = QComboBox()
        self._section_subject_combo.setMinimumWidth(120)
        self._section_subject_combo.setToolTip("切换科目以维护该科目的板块与知识点")
        self._section_subject_combo.currentIndexChanged.connect(self._on_section_subject_changed)
        subject_row.addWidget(self._section_subject_combo, 1)
        subject_row.addStretch(1)
        layout.addLayout(subject_row)

        # 左右并排：板块列表 ↔ 细分知识点列表
        splitter = QSplitter(Qt.Orientation.Horizontal)
        section_group = QGroupBox("知识板块")
        section_layout = QVBoxLayout(section_group)
        self._section_list = QListWidget()
        self._section_list.currentItemChanged.connect(self._on_section_changed)
        section_layout.addWidget(self._section_list)

        section_edit_row = QHBoxLayout()
        self._section_input = QLineEdit()
        self._section_input.setPlaceholderText("输入新板块名称，如：代数")
        section_add_button = QPushButton("添加")
        section_add_button.clicked.connect(self._on_add_section)
        section_remove_button = QPushButton("删除选中")
        section_remove_button.clicked.connect(self._on_remove_section)
        section_edit_row.addWidget(self._section_input, 1)
        section_edit_row.addWidget(section_add_button)
        section_edit_row.addWidget(section_remove_button)
        section_layout.addLayout(section_edit_row)
        splitter.addWidget(section_group)

        group = QGroupBox("细分知识点（随选中板块变化）")
        point_layout = QVBoxLayout(group)
        self._point_list = QListWidget()
        point_layout.addWidget(self._point_list)

        point_edit_row = QHBoxLayout()
        self._point_input = QLineEdit()
        self._point_input.setPlaceholderText("输入细分知识点，如：一元二次方程")
        point_add_button = QPushButton("添加")
        point_add_button.clicked.connect(self._on_add_point)
        point_remove_button = QPushButton("删除选中")
        point_remove_button.clicked.connect(self._on_remove_point)
        point_edit_row.addWidget(self._point_input, 1)
        point_edit_row.addWidget(point_add_button)
        point_edit_row.addWidget(point_remove_button)
        point_layout.addLayout(point_edit_row)
        splitter.addWidget(group)

        splitter.setSizes([200, 300])
        layout.addWidget(splitter)

        button_row = QHBoxLayout()
        save_button = QPushButton("保存知识板块")
        save_button.clicked.connect(self._on_save_sections)
        default_button = QPushButton("恢复默认知识板块")
        default_button.clicked.connect(self._on_reset_sections)
        button_row.addWidget(save_button)
        button_row.addWidget(default_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self._section_status = QLabel("")
        layout.addWidget(self._section_status)
        self._point_status = QLabel("")
        layout.addWidget(self._point_status)
        return page

    @staticmethod
    def _new_weight_spin() -> QDoubleSpinBox:
        """构建评分权重输入框。"""
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 10.0)
        spin.setDecimals(2)
        spin.setSingleStep(0.05)
        return spin

    # --------------------------------------------------------------- 科目

    def _load_subjects(self) -> None:
        """读取科目列表并渲染（需求：科目改为选择式录入）。"""
        subjects = ui_utils.safe_call(self._config_store.load_subjects, default=None)
        self._render_subjects(subjects if subjects else list(DEFAULT_SUBJECTS))

    def _render_subjects(self, subjects: list[str]) -> None:
        """把科目列表写入列表控件。"""
        self._subject_list.clear()
        for subject in subjects:
            self._subject_list.addItem(subject)
        self._subject_status.setText(f"共 {len(subjects)} 个科目")

    def _current_subjects(self) -> list[str]:
        """返回列表控件中的科目列表。"""
        return [
            self._subject_list.item(index).text()
            for index in range(self._subject_list.count())
        ]

    def _on_add_subject(self) -> None:
        """添加一个科目到列表（未保存前仅作用于界面）。"""
        name = self._subject_input.text().strip()
        if not name:
            ui_utils.info(self, "请输入科目名称。")
            return
        if name in self._current_subjects():
            ui_utils.info(self, f"科目「{name}」已存在。")
            return
        self._subject_list.addItem(name)
        self._subject_input.clear()
        self._subject_status.setText("科目已添加，请点击「保存科目列表」生效")

    def _on_remove_subject(self) -> None:
        """删除列表中选中的科目。"""
        row = self._subject_list.currentRow()
        if row < 0:
            ui_utils.info(self, "请先在列表中选择要删除的科目。")
            return
        if self._subject_list.count() <= 1:
            ui_utils.warning(self, "至少保留一个科目。")
            return
        self._subject_list.takeItem(row)
        self._subject_status.setText("科目已删除，请点击「保存科目列表」生效")

    def _on_reset_subjects(self) -> None:
        """恢复默认科目列表（未保存前仅作用于界面）。"""
        self._render_subjects(list(DEFAULT_SUBJECTS))
        self._subject_status.setText("已恢复默认科目，请点击「保存科目列表」生效")

    def _on_save_subjects(self) -> None:
        """保存科目列表并通知主窗口刷新各视图下拉框。"""
        subjects = self._current_subjects()
        if not subjects:
            ui_utils.warning(self, "科目列表不能为空。")
            return
        ok, _ = ui_utils.run_guarded(
            self,
            self._config_store.save_subjects,
            subjects,
            success_message="科目列表已保存，各视图下拉框已更新",
        )
        if ok:
            self._render_subjects(subjects)
            self.config_changed.emit()

    # ------------------------------------------------------------- 知识板块

    def _load_sections(self) -> None:
        """读取科目与知识板块并渲染（需求：手动导入时提供板块与知识点细分）。"""
        subjects = ui_utils.safe_call(self._config_store.load_subjects, default=None) or list(
            DEFAULT_SUBJECTS
        )
        self._render_section_subjects(subjects)
        self._on_section_subject_changed()

    @staticmethod
    def _sections_to_dict(
        sections: list[KnowledgeSection], subject: str | None = None
    ) -> dict[str, list[str]]:
        """``KnowledgeSection`` 列表 -> ``{板块: [细分知识点]}``，可按科目过滤。"""
        return {
            section.section: list(section.knowledge_points)
            for section in sections
            if subject is None or section.subject == subject
        }

    @staticmethod
    def _dict_to_sections(mapped: dict[str, dict[str, list[str]]]) -> list[KnowledgeSection]:
        """``{科目: {板块: [细分知识点]}}`` -> ``KnowledgeSection`` 列表。"""
        return [
            KnowledgeSection(subject=subject, section=section, knowledge_points=list(points))
            for subject, subject_data in mapped.items()
            for section, points in subject_data.items()
        ]

    def _render_section_subjects(self, subjects: list[str]) -> None:
        """重建知识板块页的科目下拉框。"""
        current = self._section_subject_combo.currentData()
        self._section_subject_combo.blockSignals(True)
        self._section_subject_combo.clear()
        for subject in subjects:
            self._section_subject_combo.addItem(subject, subject)
        index = self._section_subject_combo.findData(current)
        self._section_subject_combo.setCurrentIndex(index if index >= 0 else 0)
        self._section_subject_combo.blockSignals(False)

    def _on_section_subject_changed(self) -> None:
        """切换科目时重建该科目的板块列表。"""
        self._render_sections()

    def _render_sections(self) -> None:
        """按当前科目渲染板块列表（同时渲染首个板块的知识点）。"""
        subject = self._section_subject_combo.currentText().strip()
        sections = ui_utils.safe_call(
            self._config_store.load_sections, default=None
        ) or []
        subject_sections = self._sections_to_dict(sections, subject)
        self._section_list.clear()
        for section in subject_sections:
            self._section_list.addItem(section)
        if subject_sections:
            self._section_list.setCurrentRow(0)
        self._section_status.setText(f"科目「{subject}」共 {len(subject_sections)} 个板块")
        self._render_points()

    def _on_section_changed(self, current, previous) -> None:
        """切换选中板块时渲染该板块的细分知识点。"""
        self._render_points()

    def _render_points(self) -> None:
        """渲染当前选中板块的细分知识点列表。"""
        section = self._current_section()
        subject = self._section_subject_combo.currentText().strip()
        sections = ui_utils.safe_call(
            self._config_store.load_sections, default=None
        ) or []
        points = self._sections_to_dict(sections, subject).get(section, [])
        self._point_list.clear()
        for point in points:
            self._point_list.addItem(point)
        self._point_status_hint(section, len(points))

    def _current_section(self) -> str:
        """返回当前选中的板块名称，未选中时返回空串。"""
        item = self._section_list.currentItem()
        return item.text() if item is not None else ""

    def _current_points(self) -> list[str]:
        """返回当前板块列表控件中的知识点列表。"""
        return [
            self._point_list.item(index).text()
            for index in range(self._point_list.count())
        ]

    def _point_status_hint(self, section: str, count: int) -> None:
        """更新知识点状态提示。"""
        if section:
            self._point_status.setText(f"板块「{section}」共 {count} 个细分知识点")
        else:
            self._point_status.setText("请先在左侧选择一个板块")

    def _on_add_section(self) -> None:
        """添加一个板块（未保存前仅作用于界面）。"""
        name = self._section_input.text().strip()
        if not name:
            ui_utils.info(self, "请输入板块名称。")
            return
        if name in self._current_sections():
            ui_utils.info(self, f"板块「{name}」已存在。")
            return
        self._section_list.addItem(name)
        self._section_input.clear()
        self._section_status.setText("板块已添加，请点击「保存知识板块」生效")

    def _on_remove_section(self) -> None:
        """删除选中的板块及其知识点。"""
        row = self._section_list.currentRow()
        if row < 0:
            ui_utils.info(self, "请先在板块列表中选择要删除的板块。")
            return
        self._section_list.takeItem(row)
        self._point_list.clear()
        self._section_status.setText("板块已删除，请点击「保存知识板块」生效")

    def _on_add_point(self) -> None:
        """为当前板块添加一个细分知识点（未保存前仅作用于界面）。"""
        if not self._current_section():
            ui_utils.info(self, "请先在左侧选择一个板块。")
            return
        name = self._point_input.text().strip()
        if not name:
            ui_utils.info(self, "请输入细分知识点名称。")
            return
        if name in self._current_points():
            ui_utils.info(self, f"知识点「{name}」已存在。")
            return
        self._point_list.addItem(name)
        self._point_input.clear()
        self._point_status.setText("知识点已添加，请点击「保存知识板块」生效")

    def _on_remove_point(self) -> None:
        """删除当前板块选中的细分知识点。"""
        row = self._point_list.currentRow()
        if row < 0:
            ui_utils.info(self, "请先在知识点列表中选择要删除的知识点。")
            return
        self._point_list.takeItem(row)
        self._point_status.setText("知识点已删除，请点击「保存知识板块」生效")

    def _on_reset_sections(self) -> None:
        """恢复默认知识板块（未保存前仅作用于界面）。"""
        subject = self._section_subject_combo.currentText().strip()
        self._section_list.clear()
        for section in DEFAULT_KNOWLEDGE_SECTIONS.get(subject, {}):
            self._section_list.addItem(section)
        if DEFAULT_KNOWLEDGE_SECTIONS.get(subject):
            self._section_list.setCurrentRow(0)
        self._render_points()
        self._section_status.setText("已恢复默认知识板块，请点击「保存知识板块」生效")

    def _on_save_sections(self) -> None:
        """保存知识板块映射并通知主窗口刷新各视图下拉框。"""
        subject = self._section_subject_combo.currentText().strip()
        sections = ui_utils.safe_call(
            self._config_store.load_sections, default=None
        ) or []
        mapped = self._sections_to_dict(sections)
        mapped.setdefault(subject, {})
        mapped[subject] = {
            self._section_list.item(index).text(): [
                self._point_list.item(p).text()
                for p in range(self._point_list.count())
            ]
            for index in range(self._section_list.count())
        }
        ok, _ = ui_utils.run_guarded(
            self,
            self._config_store.save_sections,
            self._dict_to_sections(mapped),
            success_message="知识板块已保存，录入页下拉框已更新",
        )
        if ok:
            self._render_sections()
            self._render_points()
            self.config_changed.emit()

    def _current_sections(self) -> list[str]:
        """返回当前科目列表控件中的板块列表。"""
        return [
            self._section_list.item(index).text()
            for index in range(self._section_list.count())
        ]

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
            self._ai_status.setText(
                "当前状态：已配置，AI 辨识 / 难度分析 / AI 补题可用"
            )
        else:
            self._ai_status.setText(
                "当前状态：未配置，AI 辨识 / 难度分析 / AI 补题不可用"
            )

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

    # --------------------------------------------------------------- 提示词

    def _load_prompt_config(self) -> None:
        """读取提示词配置并回填表单（用户需求：AI 设置中可修改提示词）。"""
        config = ui_utils.safe_call(self._config_store.load_prompt_config, default=None)
        self._fill_prompt_form(config or DEFAULT_PROMPT_CONFIG)

    def _fill_prompt_form(self, config: PromptConfig) -> None:
        """把提示词写入编辑框（模块提示词缺失时补默认片段）。"""
        self._recognize_prompt.setPlainText(config.recognize_prompt)
        self._supplement_prompt.setPlainText(config.supplement_prompt)
        for module in RecognizeModule:
            edit = self._module_prompts.get(module.value)
            if edit is None:
                continue
            text = (config.module_prompts or {}).get(module.value) or DEFAULT_MODULE_PROMPTS.get(
                module.value, ""
            )
            edit.setPlainText(text)

    def _on_save_prompt(self) -> None:
        """保存提示词配置，后续 AI 调用立即使用新提示词。

        难度只在模块提示词里维护一处（用户需求），保存后 AI 辨识与难度分析同时生效。
        """
        config = PromptConfig(
            recognize_prompt=self._recognize_prompt.toPlainText().strip(),
            module_prompts={
                module.value: self._module_prompts[module.value].toPlainText().strip()
                for module in RecognizeModule
                if module.value in self._module_prompts
            },
            supplement_prompt=self._supplement_prompt.toPlainText().strip(),
        )
        ok, _ = ui_utils.run_guarded(
            self,
            self._config_store.save_prompt_config,
            config,
            success_message="提示词已保存，用于后续 AI 调用",
        )
        if ok:
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
