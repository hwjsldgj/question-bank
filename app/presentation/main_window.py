"""主窗口：应用程序外壳与四个功能标签页的容器。

职责（对应需求 R1-R15 的界面入口）：

- 装配"题库管理 / 组卷 / 历史 / 设置"四个标签页（历史与设置已分开）
- 菜单栏：刷新当前视图（F5）、退出（Ctrl+Q）、视图切换（Ctrl+1/2/3/4）、关于
- 状态栏：常驻显示 AI 服务配置状态，并提供临时状态消息
- 跨视图协调：题库变更 -> 组卷命中量刷新 + 历史视图刷新；
  设置变更 -> 状态栏刷新、命中量刷新、各视图科目下拉框重建；
  历史条件复用 -> 回填组卷表单并切换标签页（需求 R14 第 3 条）
- 关闭窗口时释放本地数据库连接，保证写入落盘（需求 R16 第 1 条）

视图仅通过本窗口注入的 ``Container`` 取用应用服务，不直接访问数据库。

依赖：PySide6.QtGui / QtWidgets、app.container.Container、
      app.presentation.views.*、app.presentation.ui_utils
被使用：main.py
"""

from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
)

from app.container import Container
from app.domain.entities.criteria import PaperCriteria
from app.presentation import ui_utils
from app.presentation.views.history_view import HistoryView
from app.presentation.views.paper_generation_view import PaperGenerationView
from app.presentation.views.question_bank_view import QuestionBankView
from app.presentation.views.settings_view import SettingsView

#: 标签页标题（顺序即视图切加快捷键 Ctrl+1..4 的顺序）
TAB_TITLES: tuple[str, ...] = ("题库管理", "组卷", "历史", "设置")


class MainWindow(QMainWindow):
    """主窗口：装配四个标签页并协调视图间的刷新与配置复用。"""

    def __init__(self, container: Container) -> None:
        """注入组合根容器，构建视图、菜单、状态栏并完成信号连接。"""
        super().__init__()
        self._container = container
        self.setWindowTitle("自动出题与组卷工具")
        self.resize(1220, 860)

        self._build_views()
        self._build_tabs()
        self._build_menu()
        self._build_statusbar()
        self._wire_signals()

        self._center_on_screen()
        self.refresh_ai_status()

    # ------------------------------------------------------------------ 构建

    def _build_views(self) -> None:
        """实例化四个视图（均以容器为唯一依赖来源）。"""
        self.question_bank_view = QuestionBankView(self._container)
        self.paper_generation_view = PaperGenerationView(self._container)
        self.history_view = HistoryView(self._container)
        self.settings_view = SettingsView(self._container)

    def _build_tabs(self) -> None:
        """构建标签页并设为中央部件。"""
        self._tabs = QTabWidget(self)
        self._tabs.addTab(self.question_bank_view, TAB_TITLES[0])
        self._tabs.addTab(self.paper_generation_view, TAB_TITLES[1])
        self._tabs.addTab(self.history_view, TAB_TITLES[2])
        self._tabs.addTab(self.settings_view, TAB_TITLES[3])
        self.setCentralWidget(self._tabs)

    def _build_menu(self) -> None:
        """构建菜单栏：文件 / 视图 / 帮助。"""
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("文件(&F)")
        refresh_action = QAction("刷新当前视图(&R)", self)
        refresh_action.setShortcut("F5")
        refresh_action.setStatusTip("重新加载当前标签页的数据")
        refresh_action.triggered.connect(self._refresh_current_view)
        file_menu.addAction(refresh_action)

        file_menu.addSeparator()
        quit_action = QAction("退出(&Q)", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.setStatusTip("关闭程序")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = menu_bar.addMenu("视图(&V)")
        for index, title in enumerate(TAB_TITLES):
            action = QAction(title, self)
            action.setShortcut(f"Ctrl+{index + 1}")
            action.setStatusTip(f"切换到「{title}」标签页")
            action.triggered.connect(
                lambda _checked=False, i=index: self._tabs.setCurrentIndex(i)
            )
            view_menu.addAction(action)

        help_menu = menu_bar.addMenu("帮助(&H)")
        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _build_statusbar(self) -> None:
        """构建状态栏：临时消息区 + 常驻 AI 配置状态。"""
        self._status = self.statusBar()
        self._status.showMessage("就绪")
        self._ai_status_label = QLabel("AI：检查中…")
        self._status.addPermanentWidget(self._ai_status_label)

    def _wire_signals(self) -> None:
        """连接跨视图协调信号。"""
        self.question_bank_view.questions_changed.connect(
            self._on_questions_changed
        )
        self.settings_view.config_changed.connect(self._on_config_changed)
        self.history_view.reuse_criteria_requested.connect(self._on_reuse_criteria)

    # ------------------------------------------------------------------ 槽函数

    def refresh_ai_status(self) -> None:
        """刷新状态栏中的 AI 配置状态（需求 R15 第 2 条）。"""
        config = ui_utils.safe_call(
            self._container.config_store.load_ai_config, default=None
        )
        if config is None:
            self._ai_status_label.setText("AI：状态未知")
        elif config.is_configured():
            self._ai_status_label.setText(f"AI：已配置（{config.model}）")
        else:
            self._ai_status_label.setText("AI：未配置（辨识 / 难度分析 / 补题不可用）")

    def show_status(self, message: str, timeout_ms: int = 5000) -> None:
        """在状态栏显示临时消息（供视图调用）。"""
        self._status.showMessage(message, timeout_ms)

    def _refresh_current_view(self) -> None:
        """F5：按当前标签页刷新对应视图数据。"""
        current = self._tabs.currentWidget()
        if current is self.question_bank_view:
            self.question_bank_view.reload_subjects()
            self.question_bank_view.reload_questions()
        elif current is self.paper_generation_view:
            self.paper_generation_view.refresh_hit_counts()
        elif current is self.history_view:
            self.history_view.reload_tasks()
            self.history_view.reload_question_history()
        elif current is self.settings_view:
            self.refresh_ai_status()
        self.show_status("已刷新", 3000)

    def _on_questions_changed(self) -> None:
        """题库变更：刷新组卷命中量与历史视图的题库操作台账。"""
        self.paper_generation_view.refresh_hit_counts()
        self.history_view.reload_question_history()

    def _on_config_changed(self) -> None:
        """设置保存后：刷新 AI 状态、命中量与各视图的科目下拉框。"""
        self.refresh_ai_status()
        self.question_bank_view.reload_subjects()
        self.paper_generation_view.reload_subjects()
        self.show_status("设置已保存，应用于后续操作", 5000)

    def _on_reuse_criteria(self, criteria: PaperCriteria) -> None:
        """历史条件复用：回填组卷表单并切换到组卷标签页（需求 R14 第 3 条）。"""
        self.paper_generation_view.apply_criteria(criteria)
        self._tabs.setCurrentWidget(self.paper_generation_view)
        self.show_status("已回填历史组卷条件，题单将在组卷时按当前题库重新选组", 8000)

    def _show_about(self) -> None:
        """关于对话框：说明工具定位与需求来源。"""
        QMessageBox.about(
            self,
            "关于 自动出题与组卷工具",
            "自动出题与组卷工具\n\n"
            "题库优先、评分决策、加权随机的桌面端组卷工具。\n"
            "支持科目选择式录入、题目图片导入、AI 辨识（仅供参考）与\n"
            "AI 提示词自定义；导出按「选择题 / 解答题」两部分分区、\n"
            "含分值与总分、卷末附答案页的 TXT / PDF 试卷。\n\n"
            "需求与设计见 .monkeycode/specs/question-paper-generator/",
        )

    def _center_on_screen(self) -> None:
        """将窗口移动到主屏中央。"""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    # ------------------------------------------------------------------ 生命周期

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt 命名约定
        """关闭窗口前释放本地数据库连接（需求 R16：写入落盘、解除文件占用）。

        退出阶段不再向用户抛错：关闭失败只保留连接交由进程结束时回收。
        """
        try:
            self._container.db.close()
        except Exception:  # noqa: BLE001 - 退出路径必须保证窗口能关闭
            pass
        super().closeEvent(event)
