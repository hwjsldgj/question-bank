"""表现层冒烟测试：离屏构建主窗口与四个视图，验证装配、新功能入口与跨视图信号。

使用 Qt 的 ``offscreen`` 平台，无需图形显示即可在 CI 中运行；
当环境缺少 PySide6 时整文件跳过（框架在无 GUI 依赖时仍可测其余各层）。

覆盖的用户需求：题库 / 组卷 / 历史 / 设置分开的四个标签页、科目下拉选择、
题目图片导入入口、AI 辨识模块化勾选（结果仅供参考）、保存前逐项检查与 AI 填充、
组卷指定知识点、设置中的模块化提示词与科目管理。

依赖：pytest、PySide6、app.container、app.infrastructure.database.schema、
      app.presentation.main_window
被使用：python -m pytest tests/test_presentation_smoke.py
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.container import build_container  # noqa: E402
from app.domain.entities.criteria import PaperCriteria, TypeRequirement  # noqa: E402
from app.domain.enums import Difficulty, QualityFlag, QuestionType  # noqa: E402
from app.infrastructure.database.schema import ensure_schema  # noqa: E402
from app.presentation import ui_utils  # noqa: E402
from app.presentation.main_window import MainWindow, TAB_TITLES  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    """模块级 QApplication（Qt 要求全局唯一）。"""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def window(qt_app, tmp_path):
    """用临时库构建完整容器与主窗口，测试结束关闭数据库。"""
    container = build_container(str(tmp_path / "ui.db"))
    ensure_schema(container.db.connect())
    main_window = MainWindow(container)
    yield main_window
    container.db.close()


def test_main_window_has_four_tabs(window) -> None:
    """主窗口含题库 / 组卷 / 历史 / 设置四个标签页（历史与设置已分开）。"""
    tabs = window.centralWidget()
    assert tabs.count() == 4
    assert [tabs.tabText(index) for index in range(4)] == list(TAB_TITLES)


def test_tabs_are_scrollable(window) -> None:
    """每个标签页包在可滚动容器中（用户需求：内容过高时上下滚动）。"""
    from PySide6.QtWidgets import QScrollArea

    tabs = window.centralWidget()
    for index, view in enumerate(window._tab_views):
        area = tabs.widget(index)
        assert isinstance(area, QScrollArea)
        assert area.widgetResizable() is True
        assert area.widget() is view


def test_views_share_container(window) -> None:
    """四个视图均以同一容器为依赖来源，刷新调用不抛异常地降级。"""
    window.paper_generation_view.refresh_hit_counts()
    window.question_bank_view.reload_questions()
    window.history_view.reload_tasks()
    window.history_view.reload_question_history()


def test_subject_widgets_are_dropdowns(window) -> None:
    """科目使用下拉选择（题库录入、检索过滤与组卷条件，含填空题）。"""
    bank = window.question_bank_view
    assert bank._subject_combo.count() > 0
    assert bank._search_subject.itemData(0) is None  # "全部科目"
    # 组卷改为全局单科目 + 每个题型分组内的知识点下拉（用户需求）
    view = window.paper_generation_view
    assert view._subject_combo.count() > 0
    assert len(view._type_tables) == 4
    assert len(view._type_knowledge) == 4
    for combo in view._type_knowledge.values():
        assert combo.isEditable() is True


def _add_row(
    view,
    question_type: QuestionType,
    point: str,
    difficulty: Difficulty,
    count: int,
    section: str = "",
) -> None:
    """往某题型配置表添加一行（等价界面上点「添加到配置表」）。"""
    view._append_row(
        view._type_tables[question_type], question_type, section, point, difficulty, count
    )


def test_config_and_summary_table_heights(window) -> None:
    """配置表与中间汇总表高度为原中间汇总表的两倍（用户需求）。"""
    view = window.paper_generation_view
    original_summary_height = 120
    expected = original_summary_height * 2
    assert view._stats_table.minimumHeight() == expected
    assert view._stats_table.maximumHeight() == expected
    for table in view._type_tables.values():
        assert table.minimumHeight() == expected
        assert table.maximumHeight() == expected


def test_paper_view_can_limit_by_knowledge_section(window) -> None:
    """组卷可按知识板块限定：板块进入配置行与组卷条件，知识点候选随之过滤。"""
    view = window.paper_generation_view
    view._subject_combo.setCurrentIndex(view._subject_combo.findText("数学"))
    view.reload_knowledge_points()

    section_combo = view._type_sections[QuestionType.SINGLE]
    assert section_combo.count() > 1  # 含"不限"与科目下的板块
    ui_utils.select_combo_data(section_combo, "不存在的板块")
    section_combo.addItem("代数")
    section_combo.setCurrentText("代数")
    view._on_section_changed(QuestionType.SINGLE)

    _add_row(view, QuestionType.SINGLE, "一元二次方程", Difficulty.MEDIUM, 2, "代数")
    view._type_enabled[QuestionType.SINGLE].setChecked(True)
    view._type_enabled[QuestionType.MULTIPLE].setChecked(False)
    view._type_enabled[QuestionType.FILL].setChecked(False)
    view._type_enabled[QuestionType.SOLUTION].setChecked(False)
    view.refresh_hit_counts()

    table = view._type_tables[QuestionType.SINGLE]
    assert table.item(0, 2).text() == "代数"
    assert table.item(0, 3).text() == "一元二次方程"
    assert view._stats_table.item(0, 2).text() == "代数"

    criteria = view._build_criteria()
    assert criteria.choice_items[0].section == "代数"
    assert criteria.choice_items[0].knowledge_points == ["一元二次方程"]


def test_single_and_multiple_are_separately_enabled(window) -> None:
    """组卷时单选与多选分开启用，且只按配置表里的行出题（用户需求）。"""
    view = window.paper_generation_view
    _add_row(view, QuestionType.SINGLE, "集合", Difficulty.EASY, 2)
    view._type_enabled[QuestionType.SINGLE].setChecked(True)
    view._type_enabled[QuestionType.MULTIPLE].setChecked(False)
    view._type_enabled[QuestionType.FILL].setChecked(False)
    view._type_enabled[QuestionType.SOLUTION].setChecked(False)

    criteria = view._build_criteria()
    assert criteria.choice_enabled is True
    assert [item.question_type for item in criteria.choice_items] == [
        QuestionType.SINGLE
    ]
    assert criteria.choice_items[0].count == 2
    assert criteria.choice_items[0].knowledge_points == ["集合"]

    _add_row(view, QuestionType.MULTIPLE, "集合", Difficulty.HARD, 1)
    view._type_enabled[QuestionType.MULTIPLE].setChecked(True)
    criteria = view._build_criteria()
    assert [item.question_type for item in criteria.choice_items] == [
        QuestionType.SINGLE,
        QuestionType.MULTIPLE,
    ]


def test_fill_type_supported(window) -> None:
    """填空题可用：题库题型下拉、组卷条件与配比统计均已接入。"""
    bank = window.question_bank_view
    types = [
        bank._type_combo.itemData(index) for index in range(bank._type_combo.count())
    ]
    assert QuestionType.FILL in types

    view = window.paper_generation_view
    view._subject_combo.setCurrentIndex(0)
    # 走界面路径：填条件 -> 添加到配置表
    view._type_knowledge[QuestionType.FILL].setEditText("集合")
    ui_utils.select_combo_data(
        view._type_difficulty[QuestionType.FILL], Difficulty.EASY
    )
    view._type_count[QuestionType.FILL].setValue(4)
    view._add_from_controls(QuestionType.FILL)
    assert view._type_tables[QuestionType.FILL].rowCount() == 1

    view._type_enabled[QuestionType.SINGLE].setChecked(False)
    view._type_enabled[QuestionType.MULTIPLE].setChecked(False)
    view._type_enabled[QuestionType.FILL].setChecked(True)
    view._type_enabled[QuestionType.SOLUTION].setChecked(False)
    criteria = view._build_criteria()
    assert criteria.fill_enabled is True
    assert criteria.fill_items[0].question_type is QuestionType.FILL
    assert criteria.fill_items[0].count == 4
    assert [item.question_type for item in criteria.enabled_requirements()] == [
        QuestionType.FILL
    ]


def test_cancel_edit_button(window) -> None:
    """修改题目时提供"取消编辑"入口（用户需求）。"""
    from app.domain.entities.question import Option, Question

    bank = window.question_bank_view
    assert bank._cancel_edit_button.text() == "取消编辑"
    assert bank._cancel_edit_button.isVisible() is False

    question = Question(
        id="q-1",
        subject="数学",
        knowledge_points=["集合"],
        type=QuestionType.SINGLE,
        stem="题干",
        options=[Option("A", "1"), Option("B", "2")],
        answer=["A"],
    )
    bank._load_question_into_form(question)
    assert bank._cancel_edit_button.isVisibleTo(bank) is True
    assert bank._save_button.text() == "更新题目"

    bank._on_cancel_edit()
    assert bank._editing_id is None
    assert bank._cancel_edit_button.isVisibleTo(bank) is False
    assert bank._save_button.text() == "保存题目"


def test_save_precheck_offers_ai_for_missing_fields(window) -> None:
    """保存前逐项检查：题干 / 选项缺失必须人工补齐，其余模块可让 AI 填充。"""
    from app.domain.entities.question import Option, Question

    bank = window.question_bank_view
    complete = Question(
        id="",
        subject="数学",
        knowledge_points=["集合"],
        type=QuestionType.SINGLE,
        stem="题干",
        options=[Option("A", "1"), Option("B", "2")],
        answer=["A"],
        difficulty=Difficulty.EASY,
        solution="解析",
    )
    assert bank._stem_or_options_problem(complete) is None
    assert bank._missing_labels(complete) == []
    assert bank._required_missing_labels(complete) == []

    no_stem = Question(id="", subject="数学", knowledge_points=["集合"], stem="")
    assert "题干" in bank._stem_or_options_problem(no_stem)

    one_option = Question(
        id="",
        subject="数学",
        knowledge_points=["集合"],
        type=QuestionType.SINGLE,
        stem="题干",
        options=[Option("A", "1")],
        answer=["A"],
    )
    assert "选项" in bank._stem_or_options_problem(one_option)

    incomplete = Question(
        id="",
        subject="",
        knowledge_points=[],
        type=QuestionType.SINGLE,
        stem="题干",
        options=[Option("A", "1"), Option("B", "2")],
        answer=[],
    )
    labels = bank._missing_labels(incomplete)
    assert "科目" in labels and "知识点" in labels and "答案" in labels
    # 必填项与选填项分开：难度 / 解析缺失不阻塞保存
    required = bank._required_missing_labels(incomplete)
    assert "科目" in required and "知识点" in required and "答案" in required
    assert "难度" in labels and "难度" not in required

    # 逐项检查文本包含题干 / 选项的人工填写说明与缺失标记
    lines = bank._check_lines(incomplete)
    assert any(line.startswith("题干：") for line in lines)
    assert any(line.startswith("选项：") for line in lines)
    assert any("缺失 ✗（必填）" in line for line in lines)
    text = bank._check_text(incomplete, "保存前逐项检查：")
    assert "是否让 AI 填充缺失项" in text


def test_ai_recognition_modules_are_selectable(window) -> None:
    """AI 辨识按模块勾选：默认全选，可单独取消解析（用户需求：按需给出）。"""
    from app.application.question_service import RECOGNIZE_MODULES
    from app.domain.enums import RecognizeModule

    bank = window.question_bank_view
    assert set(bank._module_checks) == set(RECOGNIZE_MODULES)
    assert all(check.isChecked() for check in bank._module_checks.values())
    assert bank._requested_modules() == list(RECOGNIZE_MODULES)
    assert bank._wants_solution() is True

    bank._module_checks[RecognizeModule.SOLUTION].setChecked(False)
    assert bank._wants_solution() is False
    assert RecognizeModule.SOLUTION not in bank._requested_modules()
    bank._module_checks[RecognizeModule.SOLUTION].setChecked(True)


def test_bank_completion_widgets(window) -> None:
    """题库收尾功能入口：概览统计、知识点补全与批量重析难度按钮。"""
    bank = window.question_bank_view
    assert bank._stats_label.text().startswith("题库概览：")
    assert bank._knowledge_edit.completer() is not None
    assert bank._search_knowledge.completer() is not None
    assert bank._selected_questions() == []
    bank._result_table.setRowCount(0)
    assert bank._on_reanalyze_selected is not None


def test_search_results_have_knowledge_points_and_compact_rows(window) -> None:
    """检索结果含知识点板块与知识点列，并收紧行距（用户需求）。"""
    bank = window.question_bank_view
    headers = [
        bank._result_table.horizontalHeaderItem(index).text()
        for index in range(bank._result_table.columnCount())
    ]
    assert headers.index("知识点板块") == headers.index("科目") + 1
    assert headers.index("知识点") == headers.index("知识点板块") + 1
    assert bank._result_table.verticalHeader().defaultSectionSize() == 18
    assert bank._result_table.verticalHeader().minimumSectionSize() == 16


def test_ai_can_skip_solution(window) -> None:
    """AI 辨识可要求不输出解析：取消「解析」模块后不生成也不覆盖解析（用户需求）。"""
    from app.domain.enums import RecognizeModule

    bank = window.question_bank_view
    bank._module_checks[RecognizeModule.SOLUTION].setChecked(False)
    bank._solution_edit.setPlainText("已有解析")
    bank._apply_recognition(
        {
            "subject": "数学",
            "knowledge_points": ["集合"],
            "question_type": QuestionType.SINGLE,
            "difficulty": Difficulty.EASY,
            "quality_flag": QualityFlag.NORMAL,
            "answer": ["A"],
        },
        include_solution=False,
    )
    assert bank._solution_edit.toPlainText() == "已有解析"
    assert "不生成解析" in bank._recognize_note.text()
    bank._module_checks[RecognizeModule.SOLUTION].setChecked(True)


def test_question_bank_has_image_and_ai_widgets(window) -> None:
    """题库录入区提供图片导入入口与 AI 辨识按钮（结果仅供参考）。"""
    bank = window.question_bank_view
    assert bank._image_preview is not None
    assert bank._image_path_label is not None
    assert "AI 辨识" in bank._recognize_button.text()
    assert "仅供参考" in bank._recognize_note.text()


def test_apply_recognition_fills_form(window) -> None:
    """AI 辨识结果写回表单，并保留"仅供参考"提示。"""
    bank = window.question_bank_view
    bank._stem_edit.setPlainText("题干")
    bank._apply_recognition(
        {
            "subject": "数学",
            "knowledge_points": ["集合"],
            "question_type": QuestionType.SINGLE,
            "difficulty": Difficulty.HARD,
            "quality_flag": QualityFlag.QUALITY,
            "answer": ["A"],
            "solution": "解析内容",
        }
    )
    assert bank._subject_combo.currentText() == "数学"
    assert bank._knowledge_edit.text() == "集合"
    assert bank._type_combo.currentData() is QuestionType.SINGLE
    assert bank._difficulty_combo.currentData() is Difficulty.HARD
    assert bank._quality_combo.currentData() is QualityFlag.QUALITY
    assert bank._answer_edit.text() == "A"
    assert bank._solution_edit.toPlainText() == "解析内容"
    assert "仅供参考" in bank._recognize_note.text()


def test_apply_criteria_fills_paper_form(window) -> None:
    """组卷视图能按 PaperCriteria 回填配置行与启用状态（需求 R14 第 3 条）。"""
    criteria = PaperCriteria(
        choice_enabled=True,
        solution_enabled=True,
        subject="数学",
        choice_items=[
            TypeRequirement(QuestionType.SINGLE, "数学", Difficulty.EASY, 4, ["集合"]),
            TypeRequirement(QuestionType.MULTIPLE, "数学", Difficulty.HARD, 2),
        ],
        solution_items=[
            TypeRequirement(QuestionType.SOLUTION, "数学", Difficulty.MEDIUM, 1)
        ],
    )
    view = window.paper_generation_view
    view.apply_criteria(criteria)
    assert view._subject == "数学"
    assert view._type_enabled[QuestionType.SINGLE].isChecked() is True
    assert view._type_enabled[QuestionType.MULTIPLE].isChecked() is True
    assert view._type_enabled[QuestionType.FILL].isChecked() is False
    assert view._type_enabled[QuestionType.SOLUTION].isChecked() is True

    rebuilt = view._build_criteria()
    assert rebuilt.subject == "数学"
    assert [item.count for item in rebuilt.choice_items] == [4, 2]
    assert rebuilt.choice_items[0].knowledge_points == ["集合"]
    assert rebuilt.solution_items[0].difficulty is Difficulty.MEDIUM


def test_stats_follow_configuration(window) -> None:
    """配置行实时汇总到配比统计，并回填该题型的命中题数（用户需求）。"""
    from app.domain.entities.question import Option, Question

    bank = window.question_bank_view
    view = window.paper_generation_view
    view._subject_combo.setCurrentIndex(0)
    subject = view._subject

    for point in ("集合", "函数"):
        bank._question_service.create_question(
            Question(
                id="",
                subject=subject,
                knowledge_points=[point],
                type=QuestionType.SINGLE,
                stem=f"题干-{point}",
                options=[Option("A", "1"), Option("B", "2")],
                answer=["A"],
                difficulty=Difficulty.MEDIUM,
            )
        )
    view.reload_knowledge_points()

    _add_row(view, QuestionType.SINGLE, "集合", Difficulty.MEDIUM, 1)
    view._type_enabled[QuestionType.SINGLE].setChecked(True)
    view._type_enabled[QuestionType.MULTIPLE].setChecked(False)
    view._type_enabled[QuestionType.FILL].setChecked(False)
    view._type_enabled[QuestionType.SOLUTION].setChecked(False)
    view.refresh_hit_counts()

    stats = view._stats_table
    rows = [
        [stats.item(row, column).text() for column in range(stats.columnCount())]
        for row in range(stats.rowCount())
    ]
    assert rows == [["单选题", "中", "集合", "1", "1"]]

    # 该题型配置表同样显示命中题数，且题型列标明题型
    table = view._type_tables[QuestionType.SINGLE]
    assert table.item(0, 1).text() == "单选题"
    assert table.item(0, 6).text() == "1"

    # 数量改为 0 后该行不再计入配比
    table.item(0, 5).setText("0")
    view.refresh_hit_counts()
    assert view._stats_table.rowCount() == 0

    # 命中量为 0 的知识点照样显示
    _add_row(view, QuestionType.SINGLE, "不存在的知识点", Difficulty.MEDIUM, 2)
    view.refresh_hit_counts()
    assert view._stats_table.item(0, 5).text() == "0"


def test_reuse_signal_routed_to_paper_view(window) -> None:
    """历史视图发出复用信号后，主窗口把它路由到组卷视图（需求 R14 第 3 条）。"""
    criteria = PaperCriteria(
        choice_enabled=True,
        subject="物理",
        choice_items=[
            TypeRequirement(QuestionType.SINGLE, "物理", Difficulty.MEDIUM, 6)
        ],
    )
    window.history_view.reuse_criteria_requested.emit(criteria)
    view = window.paper_generation_view
    assert view._subject == "物理"
    assert view._build_criteria().choice_items[0].count == 6
    assert window.centralWidget().currentIndex() == TAB_TITLES.index("组卷")


def test_settings_has_prompt_and_subject_editors(window, monkeypatch) -> None:
    """设置视图提供提示词（含模块化输出提示词）编辑与科目管理（用户需求）。"""
    from app.domain.enums import RecognizeModule
    from app.presentation import ui_utils

    # 保存提示词会弹成功提示；离屏测试里屏蔽所有弹窗，避免阻塞
    monkeypatch.setattr(ui_utils, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(ui_utils, "warning", lambda *args, **kwargs: None)

    settings = window.settings_view
    assert settings._recognize_prompt.toPlainText()
    assert settings._supplement_prompt.toPlainText()
    assert set(settings._module_prompts) == {module.value for module in RecognizeModule}
    for module in RecognizeModule:
        assert settings._module_prompts[module.value].toPlainText()
    assert settings._subject_list.count() > 0

    # 难度提示词只保留一处：不再有独立的「难度分析提示词」编辑框（用户需求）
    assert not hasattr(settings, "_difficulty_prompt")
    assert RecognizeModule.DIFFICULTY.value in settings._module_prompts

    # 保存模块提示词后能读回（每个模块独立可改）
    settings._module_prompts["answer"].setPlainText("answer：只给标号")
    settings._on_save_prompt()
    loaded = window._container.config_store.load_prompt_config()
    assert loaded.module_prompts["answer"] == "answer：只给标号"
    assert loaded.module_prompts["subject"]


def test_import_check_text_lists_missing_items(window) -> None:
    """导入前逐项检查文案列出每题缺失项与必填 / 选填标记（用户需求）。"""
    from app.domain.entities.question import Option, Question

    bank = window.question_bank_view
    draft = Question(
        id="",
        subject="",
        knowledge_points=[],
        type=QuestionType.SINGLE,
        stem="题干",
        options=[Option("A", "1"), Option("B", "2")],
        answer=[],
    )
    bank._paste_drafts = [draft]
    problems = bank._incomplete_drafts()
    assert [index for index, _ in problems] == [1]

    text = bank._import_check_text(problems)
    assert "非题干信息不完整" in text
    assert "第 1 题" in text
    assert "（必填）" in text
    assert "是否让 AI 填充" in text

    # 信息齐全时不进入逐项检查
    complete = Question(
        id="",
        subject="数学",
        knowledge_points=["集合"],
        type=QuestionType.SINGLE,
        stem="题干",
        options=[Option("A", "1"), Option("B", "2")],
        answer=["A"],
        difficulty=Difficulty.EASY,
        solution="解析",
    )
    bank._paste_drafts = [complete]
    assert bank._incomplete_drafts() == []
    assert bank._ensure_drafts_before_import() is True
    bank._paste_drafts = []


def test_ai_response_issues_are_reported(window, monkeypatch) -> None:
    """AI 返回内容有问题时弹窗提示，无问题时静默（用户需求）。"""
    from app.presentation import ui_utils

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        ui_utils,
        "warning",
        lambda parent, text, title="无法继续": calls.append((title, text)),
    )

    bank = window.question_bank_view
    bank._show_ai_issues([])
    assert calls == []

    bank._show_ai_issues(
        ["AI 未返回知识点（knowledge_points）", "AI 返回的难度无法识别：'一般'"]
    )
    assert len(calls) == 1
    title, text = calls[0]
    assert "AI 返回内容有问题" == title
    assert "AI 未返回知识点" in text and "无法识别" in text


def test_config_changed_does_not_crash(window) -> None:
    """配置变更信号触发状态栏与科目下拉刷新，界面不崩溃。"""
    window.settings_view.config_changed.emit()
    assert window._ai_status_label.text().startswith("AI：")
