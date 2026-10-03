"""表现层冒烟测试：离屏构建主窗口与四个视图，验证装配、新功能入口与跨视图信号。

使用 Qt 的 ``offscreen`` 平台，无需图形显示即可在 CI 中运行；
当环境缺少 PySide6 时整文件跳过（框架在无 GUI 依赖时仍可测其余各层）。

覆盖的用户需求：题库 / 组卷 / 历史 / 设置分开的四个标签页、科目下拉选择、
题目图片导入入口、AI 辨识按钮（仅供参考提示）、设置中的提示词与科目管理。

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


def test_views_share_container(window) -> None:
    """四个视图均以同一容器为依赖来源，刷新调用不抛异常地降级。"""
    window.paper_generation_view.refresh_hit_counts()
    window.question_bank_view.reload_questions()
    window.history_view.reload_tasks()
    window.history_view.reload_question_history()


def test_subject_widgets_are_dropdowns(window) -> None:
    """科目使用下拉选择（题库录入、检索过滤与组卷条件）。"""
    bank = window.question_bank_view
    assert bank._subject_combo.count() > 0
    assert bank._search_subject.itemData(0) is None  # "全部科目"
    for combo in (
        window.paper_generation_view._single_subject,
        window.paper_generation_view._multiple_subject,
        window.paper_generation_view._solution_subject,
    ):
        assert combo.count() > 0


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
    """组卷视图能按 PaperCriteria 回填四个题型条件（需求 R14 第 3 条）。"""
    criteria = PaperCriteria(
        choice_enabled=True,
        solution_enabled=True,
        choice_items=[
            TypeRequirement(QuestionType.SINGLE, "数学", Difficulty.EASY, 4),
            TypeRequirement(QuestionType.MULTIPLE, "数学", Difficulty.HARD, 2),
        ],
        solution_item=TypeRequirement(QuestionType.SOLUTION, "数学", Difficulty.MEDIUM, 1),
    )
    window.paper_generation_view.apply_criteria(criteria)
    assert window.paper_generation_view._single_subject.currentText() == "数学"
    assert window.paper_generation_view._single_count.value() == 4
    assert window.paper_generation_view._solution_enabled.isChecked() is True


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
    assert window.centralWidget().currentWidget() is window.paper_generation_view


def test_settings_has_prompt_and_subject_editors(window) -> None:
    """设置视图提供提示词编辑与科目管理（用户需求）。"""
    settings = window.settings_view
    assert settings._recognize_prompt.toPlainText()
    assert settings._difficulty_prompt.toPlainText()
    assert settings._supplement_prompt.toPlainText()
    assert settings._subject_list.count() > 0


def test_config_changed_does_not_crash(window) -> None:
    """配置变更信号触发状态栏与科目下拉刷新，界面不崩溃。"""
    window.settings_view.config_changed.emit()
    assert window._ai_status_label.text().startswith("AI：")
