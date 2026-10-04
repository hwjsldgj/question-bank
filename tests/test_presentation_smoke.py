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
    for combo in (
        window.paper_generation_view._single_subject,
        window.paper_generation_view._multiple_subject,
        window.paper_generation_view._fill_subject,
        window.paper_generation_view._solution_subject,
    ):
        assert combo.count() > 0


def test_single_and_multiple_are_separately_enabled(window) -> None:
    """组卷时单选与多选分开启用（用户需求）。"""
    view = window.paper_generation_view
    view._single_enabled.setChecked(True)
    view._multiple_enabled.setChecked(False)
    view._fill_enabled.setChecked(False)
    view._solution_enabled.setChecked(False)
    criteria = view._build_criteria()
    assert criteria.choice_enabled is True
    assert [item.question_type for item in criteria.choice_items] == [
        QuestionType.SINGLE
    ]

    view._multiple_enabled.setChecked(True)
    criteria = view._build_criteria()
    assert [item.question_type for item in criteria.choice_items] == [
        QuestionType.SINGLE,
        QuestionType.MULTIPLE,
    ]


def test_fill_type_supported(window) -> None:
    """填空题可用：题库题型下拉、组卷条件与命中量均已接入。"""
    bank = window.question_bank_view
    types = [
        bank._type_combo.itemData(index) for index in range(bank._type_combo.count())
    ]
    assert QuestionType.FILL in types

    view = window.paper_generation_view
    view._fill_enabled.setChecked(True)
    view._fill_count.setValue(4)
    criteria = view._build_criteria()
    assert criteria.fill_enabled is True
    assert criteria.fill_item is not None
    assert criteria.fill_item.question_type is QuestionType.FILL
    assert criteria.fill_item.count == 4
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
    """组卷视图能按 PaperCriteria 回填四个题型条件，含指定知识点（需求 R14 第 3 条）。"""
    criteria = PaperCriteria(
        choice_enabled=True,
        solution_enabled=True,
        choice_items=[
            TypeRequirement(
                QuestionType.SINGLE, "数学", Difficulty.EASY, 4, ["集合", "函数"]
            ),
            TypeRequirement(QuestionType.MULTIPLE, "数学", Difficulty.HARD, 2),
        ],
        solution_item=TypeRequirement(QuestionType.SOLUTION, "数学", Difficulty.MEDIUM, 1),
    )
    view = window.paper_generation_view
    view.apply_criteria(criteria)
    assert view._single_subject.currentText() == "数学"
    assert view._single_count.value() == 4
    assert view._solution_enabled.isChecked() is True
    # 指定知识点回填
    assert view._single_knowledge.currentText() == "集合，函数"
    assert view._knowledge_of(view._single_knowledge) == ["集合", "函数"]
    assert view._knowledge_of(view._multiple_knowledge) == []


def test_paper_view_can_specify_knowledge_points(window) -> None:
    """组卷条件可指定知识点：命中量按知识点过滤，条件携带知识点（用户需求）。"""
    from app.domain.entities.question import Option, Question

    bank = window.question_bank_view
    view = window.paper_generation_view

    for points in (["集合"], ["函数"], ["集合", "函数"]):
        bank._question_service.create_question(
            Question(
                id="",
                subject=view._single_subject.currentText() or "数学",
                knowledge_points=points,
                type=QuestionType.SINGLE,
                stem=f"题干-{'-'.join(points)}",
                options=[Option("A", "1"), Option("B", "2")],
                answer=["A"],
                difficulty=Difficulty.MEDIUM,
            )
        )
    view.reload_knowledge_points()
    assert view._single_knowledge.count() >= 2

    view._single_enabled.setChecked(True)
    ui_utils.select_combo_data(view._single_difficulty, Difficulty.MEDIUM)
    view._single_knowledge.setEditText("集合")
    view.refresh_hit_counts()
    assert "命中：2 道" in view._single_hit.text()
    assert "知识点：集合" in view._single_hit.text()

    criteria = view._build_criteria()
    assert criteria.choice_items[0].knowledge_points == ["集合"]

    view._single_knowledge.setEditText("不存在的知识点")
    view.refresh_hit_counts()
    assert "命中：0 道" in view._single_hit.text()
    view._single_knowledge.setEditText("集合，函数、导数")
    assert view.parse_knowledge(view._single_knowledge.currentText()) == [
        "集合",
        "函数",
        "导数",
    ]
    view._single_knowledge.setEditText("")


def test_reuse_signal_routed_to_paper_view(window) -> None:
    """历史视图发出复用信号后，主窗口把它路由到组卷视图（需求 R14 第 3 条）。"""
    criteria = PaperCriteria(
        choice_enabled=True,
        choice_items=[
            TypeRequirement(QuestionType.SINGLE, "物理", Difficulty.MEDIUM, 6)
        ],
    )
    window.history_view.reuse_criteria_requested.emit(criteria)
    assert window.paper_generation_view._single_subject.currentText() == "物理"
    assert window.paper_generation_view._single_count.value() == 6
    assert window.centralWidget().currentIndex() == TAB_TITLES.index("组卷")


def test_settings_has_prompt_and_subject_editors(window) -> None:
    """设置视图提供提示词（含模块化输出提示词）编辑与科目管理（用户需求）。"""
    from app.domain.enums import RecognizeModule

    settings = window.settings_view
    assert settings._recognize_prompt.toPlainText()
    assert settings._difficulty_prompt.toPlainText()
    assert settings._supplement_prompt.toPlainText()
    assert set(settings._module_prompts) == {module.value for module in RecognizeModule}
    for module in RecognizeModule:
        assert settings._module_prompts[module.value].toPlainText()
    assert settings._subject_list.count() > 0

    # 保存模块提示词后能读回（每个模块独立可改）
    settings._module_prompts["answer"].setPlainText("answer：只给标号")
    settings._on_save_prompt()
    loaded = window._container.config_store.load_prompt_config()
    assert loaded.module_prompts["answer"] == "answer：只给标号"
    assert loaded.module_prompts["subject"]


def test_config_changed_does_not_crash(window) -> None:
    """配置变更信号触发状态栏与科目下拉刷新，界面不崩溃。"""
    window.settings_view.config_changed.emit()
    assert window._ai_status_label.text().startswith("AI：")
