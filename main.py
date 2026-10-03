"""自动出题与组卷工具 —— 程序入口。

启动流程：装配组合根容器 -> 初始化数据库结构 -> 创建并显示主窗口。

依赖：app.container.build_container、app.infrastructure.database.schema、
      app.presentation.main_window.MainWindow
被使用：命令行 ``python main.py``
"""

import sys

from PySide6.QtWidgets import QApplication


def main() -> int:
    """应用主入口：返回退出码。"""
    # 延迟导入，保证 --help 等轻量场景不触发重量级装配
    from app.container import build_container
    from app.infrastructure.database.schema import ensure_schema
    from app.presentation.main_window import MainWindow

    container = build_container()
    ensure_schema(container.db.connect())

    app = QApplication(sys.argv)
    window = MainWindow(container)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
