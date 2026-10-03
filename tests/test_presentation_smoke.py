"""表现层冒烟测试：离屏构建主窗口与三个视图，验证装配与跨视图信号。

使用 Qt 的 ``offscreen`` 平台，无需图形显示即可在 CI 中运行；
当环境缺少 PySide6 时整文件跳过（框架在无 GUI 依赖时仍可测其余各层）。

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
from app.domain.enums import Difficulty, QuestionType  # noqa: E402
from app.infrastructure.database.schema import ensure_schema  # noqa: E402
from app.presentation.main_window import MainWindow  # noqa: E402


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


def test_main_window_has_three_tabs(window) -> None:
    """主窗口含题库 / 组卷 / 历史与设置三个标签页（需求 R1-R15 界面入口）。"""
    tabs = window.centralWidget()
    assert tabs.count() == 3
    assert [tabs.tabText(index) for index in range(3)] == [
        "题库管理",
        "组卷",
        "历史与设置",
    ]


def test_views_share_container(window) -> None:
    """三个视图均以同一容器为依赖来源，服务方法调用不抛异常地降级。"""
    # 命中量统计与检索在框架阶段为 TODO，应静默降级而非崩溃（safe_call）。
    window.paper_generation_view.refresh_hit_counts()
    window.question_bank_view.reload_questions()
    window.history_settings_view.reload_tasks()


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
    assert window.paper_generation_view._single_subject.text() == "数学"
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
    window.history_settings_view.reuse_criteria_requested.emit(criteria)
    assert window.paper_generation_view._single_subject.text() == "物理"
    assert window.paper_generation_view._single_count.value() == 6
    assert window.centralWidget().currentWidget() is window.paper_generation_view


def test_config_changed_does_not_crash(window) -> None:
    """配置变更信号触发状态栏与命中量刷新，框架阶段应安全降级。"""
    window.history_settings_view.config_changed.emit()
    assert window._ai_status_label.text().startswith("AI：")
