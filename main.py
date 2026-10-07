"""自动出题与组卷工具 —— 程序入口。

启动流程：
  1. 显示启动画面（Windows 风格旋转动画）
  2. 后台线程构建容器（装配各种 repo/service，不加载模型）
  3. 容器就绪 -> 主窗口立即显示、启动画面关闭
  4. 主窗口显示后，后台线程预热本地难度模型
  5. 状态栏报告模型加载状态

依赖：app.container.build_container、app.infrastructure.database.schema、
      app.presentation.main_window.MainWindow
被使用：命令行 ``python main.py``
"""

import os
import sys
import traceback

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget


class _Loader(QThread):
    """后台加载容器，完成后发出信号。"""

    loaded = Signal(object, object)

    def run(self) -> None:
        try:
            from app.container import build_container
            from app.infrastructure.database.schema import ensure_schema

            container = build_container()
            ensure_schema(container.db.connect())
            self.loaded.emit(container, None)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.loaded.emit(None, exc)


class _ModelWarmer(QThread):
    """后台预热本地难度模型（触发懒加载）。"""

    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, container):
        super().__init__()
        self._container = container

    def run(self) -> None:
        try:
            clf = getattr(self._container.ai_client, "_local_classifier", None)
            if clf is None:
                self.finished_ok.emit()
                return
            ensure = getattr(clf, "ensure_loaded", None)
            if ensure is not None:
                ensure()
            self.finished_ok.emit()
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.failed.emit(str(exc))


class _Splash(QWidget):
    """Windows 开机风格：用 Segoe Boot 字体绘制旋转圆点动画。"""

    FONT_PATHS = [
        r"C:\Windows\Boot\Fonts\segoe_slboot.ttf",
        r"C:\Windows\Boot\Fonts\segoen_slboot.ttf",
    ]
    CHAR_START = 0xE052
    CHAR_END = 0xE0C8

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
        )
        self.setFixedSize(480, 300)

        self._font_family = None
        self._load_font()

        self._frame = self.CHAR_START
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._next_frame)
        self._timer.start(30)

    def _load_font(self) -> None:
        for path in self.FONT_PATHS:
            if not os.path.exists(path):
                continue
            font_id = QFontDatabase.addApplicationFont(path)
            if font_id == -1:
                continue
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                self._font_family = families[0]
                return

    def _next_frame(self) -> None:
        self._frame += 1
        if self._frame > self.CHAR_END:
            self._frame = self.CHAR_START
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        painter.fillRect(self.rect(), QColor("#1a5490"))

        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Microsoft YaHei", 19, QFont.Weight.Bold))
        painter.drawText(
            self.rect().adjusted(0, 40, 0, 0),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            "高考数学题 AI 分析器",
        )

        painter.setPen(QPen(QColor("#3a7cb8"), 1))
        painter.drawLine(150, 92, 330, 92)

        if self._font_family:
            painter.setFont(QFont(self._font_family, 32))
            painter.setPen(QColor("#ffffff"))
            painter.drawText(
                self.rect().adjusted(0, 110, 0, -80),
                Qt.AlignmentFlag.AlignCenter,
                chr(self._frame),
            )
        else:
            import math
            chars = ["高", "考", "数", "学"]
            font = QFont("Microsoft YaHei", 30, QFont.Weight.Bold)
            painter.setFont(font)
            fm = painter.fontMetrics()
            widths = [fm.horizontalAdvance(c) for c in chars]
            total = sum(widths) + 20 * (len(chars) - 1)
            start_x = (self.width() - total) / 2.0
            phase = (self._frame - self.CHAR_START) / 40.0
            for i, ch in enumerate(chars):
                local = (phase - i * 0.25) % 1.0
                b = 0.3 + 0.7 * math.exp(-((local * 4) ** 2))
                painter.setPen(QColor(int(255 * b), int(255 * b), int(255 * b)))
                painter.drawText(QPointF(start_x, 175), ch)
                start_x += widths[i] + 20

        painter.setPen(QColor("#cfd8e3"))
        painter.setFont(QFont("Microsoft YaHei", 11))
        painter.drawText(
            self.rect().adjusted(0, 210, 0, 0),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            "正在启动…",
        )

        painter.setPen(QColor("#8fa8c4"))
        painter.setFont(QFont("Microsoft YaHei", 9))
        painter.drawText(
            self.rect().adjusted(0, 0, 0, -18),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
            "本地运行 · 数据仅存本机",
        )


def main() -> int:
    import time
    import random

    app = QApplication(sys.argv)

    # 1. 立即显示启动画面
    splash = _Splash()
    splash.show()
    app.processEvents()

    # 记录 splash 起始时间；最小显示时长 1s ± 0.2s
    splash_t0 = time.monotonic()
    min_show = 1.0 + random.uniform(-0.2, 0.2)
    state: dict = {"window": None, "loader": None, "warmer": None}

    def _on_loaded(container, error) -> None:
        """容器装配完成（主线程回调）。"""
        if error is not None:
            splash.close()
            QMessageBox.critical(None, "启动失败", f"容器装配失败：\n\n{error}")
            app.quit()
            return

        try:
            from app.presentation.main_window import MainWindow

            window = MainWindow(container)
        except Exception:  # noqa: BLE001
            tb = traceback.format_exc()
            print(tb, file=sys.stderr)
            splash.close()
            QMessageBox.critical(None, "创建主窗口失败", tb)
            app.quit()
            return

        state["window"] = window

        def _show_window_and_warm() -> None:
            """关闭启动画面、显示主窗口、启动模型预热。"""
            window.show()
            window.raise_()
            window.activateWindow()
            splash.close()

            # 主窗口显示后，后台预热模型
            window.show_status("本地模型后台加载中…", 0)
            warmer = _ModelWarmer(container)
            state["warmer"] = warmer

            def on_warm_ok():
                window.show_status("本地模型已就绪", 3000)

            def on_warm_fail(msg):
                window.show_status(f"本地模型加载失败：{msg}", 8000)

            warmer.finished_ok.connect(on_warm_ok)
            warmer.failed.connect(on_warm_fail)
            warmer.start()

        # 计算剩余停留时间：至少显示 min_show 秒
        elapsed = time.monotonic() - splash_t0
        remaining_ms = int(max(0.0, min_show - elapsed) * 1000)
        QTimer.singleShot(remaining_ms, _show_window_and_warm)

    def _kick_loader() -> None:
        loader = _Loader()
        loader.loaded.connect(
            lambda c, e: QTimer.singleShot(0, lambda: _on_loaded(c, e))
        )
        state["loader"] = loader
        loader.start()

    # 让 splash 先渲染一次，再启动 loader
    QTimer.singleShot(50, _kick_loader)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
