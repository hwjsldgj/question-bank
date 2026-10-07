"""自动出题与组卷工具 —— 程序入口。

启动流程：Windows 风格旋转圆点动画 -> 后台线程加载容器 -> 主线程创建主窗口。
动画使用 Windows 自带的 Segoe Boot 字体（segoe_slboot.ttf），
字体缺失时降级为纯文字提示。
"""

import os
import sys
import traceback

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget


class _Loader(QThread):
    """后台加载容器，完成后发出信号。"""

    loaded = Signal(object, object)  # (container, error)

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


class _Splash(QWidget):
    """Windows 开机风格：用 Segoe Boot 字体绘制旋转圆点动画。"""

    # Windows 启动字体路径（多个候选）
    FONT_PATHS = [
        r"C:\Windows\Boot\Fonts\segoe_slboot.ttf",
        r"C:\Windows\Boot\Fonts\segoen_slboot.ttf",
    ]

    # 动画字符序列（Windows 10/11 通用）
    CHAR_SEQUENCE = [chr(c) for c in range(0xE052, 0xE0C9)]

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
        )
        self.setFixedSize(480, 300)

        self._font_family = None
        self._load_font()

        self._frame_index = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._next_frame)
        self._timer.start(25)  # 约 40fps，动画流畅

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
                print(f"[splash] 已加载开机动画字体: {self._font_family}")
                return
        print("[splash] 未找到 Windows 开机字体，将使用备用动画")

    def _next_frame(self) -> None:
        self._frame_index = (self._frame_index + 1) % len(self.CHAR_SEQUENCE)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # 背景
        painter.fillRect(self.rect(), QColor("#1a5490"))

        # 主标题
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Microsoft YaHei", 19, QFont.Weight.Bold))
        painter.drawText(
            self.rect().adjusted(0, 40, 0, 0),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            "高考数学题 AI 分析器",
        )

        # 分隔线
        painter.setPen(QPen(QColor("#3a7cb8"), 1))
        painter.drawLine(150, 92, 330, 92)

        # 旋转圆点动画（居中）
        if self._font_family:
            # 字号设为 32，可根据喜好微调
            painter.setFont(QFont(self._font_family, 32))
            painter.setPen(QColor("#ffffff"))
            # 绘制区域：水平居中，垂直方向留出空间
            center_rect = self.rect().adjusted(0, 110, 0, -80)
            painter.drawText(
                center_rect,
                Qt.AlignmentFlag.AlignCenter,
                self.CHAR_SEQUENCE[self._frame_index],
            )
        else:
            # 字体缺失时的降级方案：简单的旋转圆弧
            cx, cy, r = 240, 165, 24
            painter.setPen(QPen(QColor("#2a6490"), 4))
            painter.drawArc(cx - r, cy - r, 2 * r, 2 * r, 0, 360 * 16)
            angle = (self._frame_index * 8) % 360
            pen = QPen(QColor("#ffffff"), 4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(cx - r, cy - r, 2 * r, 2 * r, -angle * 16, 120 * 16)

        # 副标题
        painter.setPen(QColor("#cfd8e3"))
        painter.setFont(QFont("Microsoft YaHei", 11))
        painter.drawText(
            self.rect().adjusted(0, 215, 0, 0),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            "正在加载本地模型…",
        )

        # 底部提示
        painter.setPen(QColor("#8fa8c4"))
        painter.setFont(QFont("Microsoft YaHei", 9))
        painter.drawText(
            self.rect().adjusted(0, 0, 0, -18),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
            "首次启动约 10~15 秒 · 数据仅存本机",
        )


def main() -> int:
    app = QApplication(sys.argv)

    splash = _Splash()
    splash.show()
    app.processEvents()

    state: dict = {"window": None, "loader": None}

    def _show_main(container, error) -> None:
        if error is not None:
            splash.hide()
            QMessageBox.critical(
                None, "启动失败",
                f"本地模型加载失败：\n\n{error}",
            )
            app.quit()
            return

        try:
            from app.presentation.main_window import MainWindow

            window = MainWindow(container)
            window.show()
            window.raise_()
            window.activateWindow()
            state["window"] = window
            splash.hide()
            splash.deleteLater()
        except Exception:  # noqa: BLE001
            tb = traceback.format_exc()
            print(tb, file=sys.stderr)
            splash.hide()
            QMessageBox.critical(None, "创建主窗口失败", tb)
            app.quit()

    def on_loaded(container, error) -> None:
        QTimer.singleShot(0, lambda: _show_main(container, error))

    loader = _Loader()
    loader.loaded.connect(on_loaded)
    state["loader"] = loader
    loader.start()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())