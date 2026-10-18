"""主题定义：颜色常量 + QSS 生成 + 应用入口。

用法：
    from app.presentation.theme import apply_theme
    apply_theme(QApplication.instance(), "dark")

模式：``light`` / ``dark``。色板由调色板函数 ``palette(mode)`` 统一提供，
硬编码颜色应改为从 ``palette()`` 读取，避免两套颜色散落各处。
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication


# 暗色调色板（基于 #151517 / #1B1B1C / #121314 / #191A1B / #0D0D0E 派生）
DARK: dict[str, str] = {
    "window":    "#151517",   # 主窗口 / 一般面板
    "base":      "#1B1B1C",   # 表格 / 卡片 / 分组框
    "input":     "#121314",   # 输入框 / 下拉框
    "hover":     "#191A1B",   # hover 高亮
    "deepest":   "#0D0D0E",   # 状态栏 / 分隔条
    "border":    "#2A2A2C",
    "text":      "#E6E6E6",
    "text_dim":  "#A0A0A2",
    "text_weak": "#6E6E70",
    "accent":    "#4A9EFF",
    "select_bg": "#2D4A6F",
    "danger":    "#E06C75",
    "success":   "#98C379",
}

# 浅色调色板（沿用 Fusion 默认观感，只规范化少量语义色）
LIGHT: dict[str, str] = {
    "window":    "#F5F5F7",
    "base":      "#FFFFFF",
    "input":     "#FFFFFF",
    "hover":     "#E8E8EA",
    "deepest":   "#E0E0E2",
    "border":    "#C8C8CA",
    "text":      "#1A1A1A",
    "text_dim":  "#5A5A5C",
    "text_weak": "#8A8A8C",
    "accent":    "#1E6FD9",
    "select_bg": "#CCE4FF",
    "danger":    "#B00020",
    "success":   "#2E7D32",
}


def palette(mode: str) -> dict[str, str]:
    """按模式返回调色板；未知模式回退到浅色。"""
    return DARK if str(mode).lower() == "dark" else LIGHT


def build_qss(mode: str) -> str:
    """根据模式生成 Qt 样式表。"""
    c = palette(mode)
    return f"""
/* ===== 全局 ===== */
QWidget {{
    background-color: {c['window']};
    color: {c['text']};
}}
QDialog, QMainWindow {{
    background-color: {c['window']};
}}
QToolTip {{
    background-color: {c['base']};
    color: {c['text']};
    border: 1px solid {c['border']};
    padding: 4px 6px;
}}

/* ===== 按钮 ===== */
QPushButton {{
    background-color: {c['base']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 2px;
    padding: 4px 12px;
    min-height: 20px;
}}
QPushButton:hover {{
    background-color: {c['hover']};
}}
QPushButton:pressed {{
    background-color: {c['deepest']};
}}
QPushButton:disabled {{
    color: {c['text_weak']};
    border-color: {c['deepest']};
}}
QPushButton:default {{
    border: 1px solid {c['accent']};
}}

/* ===== 文本输入 ===== */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {c['input']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 2px;
    padding: 2px 4px;
    selection-background-color: {c['select_bg']};
    selection-color: {c['text']};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {c['accent']};
}}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{
    color: {c['text_weak']};
}}

/* ===== 下拉框 ===== */
QComboBox {{
    background-color: {c['input']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 2px;
    padding: 2px 6px;
    min-height: 20px;
}}
QComboBox:hover {{
    background-color: {c['hover']};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {c['base']};
    color: {c['text']};
    selection-background-color: {c['select_bg']};
    selection-color: {c['text']};
    border: 1px solid {c['border']};
    outline: 0;
}}

/* ===== 表格 ===== */
QTableWidget, QTableView, QTreeWidget, QTreeView {{
    background-color: {c['base']};
    alternate-background-color: {c['window']};
    color: {c['text']};
    gridline-color: {c['border']};
    selection-background-color: {c['select_bg']};
    selection-color: {c['text']};
    border: 1px solid {c['border']};
}}
QHeaderView::section {{
    background-color: {c['window']};
    color: {c['text_dim']};
    border: none;
    border-right: 1px solid {c['border']};
    border-bottom: 1px solid {c['border']};
    padding: 4px 6px;
}}
QTableCornerButton::section {{
    background-color: {c['window']};
    border: none;
}}

/* ===== 标签页 ===== */
QTabWidget::pane {{
    border: 1px solid {c['border']};
    background-color: {c['window']};
    top: -1px;
}}
QTabBar {{
    background-color: transparent;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {c['text_dim']};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 4px 8px;
    margin-right: 0;
    min-width: 36px;
    font-size: 12px;
}}
QTabBar::tab:hover:!selected {{
    color: {c['text']};
    border-bottom: 2px solid {c['border']};
}}
QTabBar::tab:selected {{
    color: {c['accent']};
    border-bottom: 2px solid {c['accent']};
}}

/* ===== 分组框 ===== */
QGroupBox {{
    background-color: {c['window']};
    border: 1px solid {c['border']};
    border-radius: 2px;
    margin-top: 12px;
    padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    color: {c['text_dim']};
}}

/* ===== 滚动条 ===== */
QScrollBar:vertical {{
    background-color: {c['window']};
    width: 12px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background-color: {c['border']};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {c['text_weak']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background-color: {c['window']};
    height: 12px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background-color: {c['border']};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {c['text_weak']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ===== 菜单栏（与标签页同风格：底划线选中） ===== */
QMenuBar {{
    background-color: {c['window']};
    color: {c['text']};
    border-bottom: 1px solid {c['border']};
    padding: 0;
}}
QMenuBar::item {{
    background-color: transparent;
    color: {c['text_dim']};
    padding: 4px 8px;
    border: none;
    border-bottom: 2px solid transparent;
}}
QMenuBar::item:selected {{
    background-color: transparent;
    color: {c['text']};
    border-bottom: 2px solid {c['border']};
}}
QMenuBar::item:pressed {{
    background-color: {c['select_bg']};
    color: {c['text']};
    border-bottom: 2px solid {c['accent']};
}}

/* ===== 菜单弹出 ===== */
QMenu {{
    background-color: {c['base']};
    color: {c['text']};
    border: 1px solid {c['border']};
}}
QMenu::item:selected {{
    background-color: {c['select_bg']};
}}

/* ===== 状态栏 ===== */
QStatusBar {{
    background-color: {c['deepest']};
    color: {c['text_dim']};
}}
QStatusBar::item {{
    border: none;
}}

/* ===== 复选 / 单选 ===== */
QCheckBox, QRadioButton {{
    background-color: transparent;
    color: {c['text']};
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px;
    height: 14px;
}}

/* ===== 进度条 ===== */
QProgressBar {{
    background-color: {c['input']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 2px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {c['accent']};
}}

/* ===== 富文本浏览（详情弹窗） ===== */
QTextBrowser, QTextEdit {{
    background-color: {c['base']};
    color: {c['text']};
    border: 1px solid {c['border']};
    selection-background-color: {c['select_bg']};
    selection-color: {c['text']};
}}

/* ===== 复选 / 单选框指示器 ===== */
QCheckBox::indicator, QRadioButton::indicator {{
    border: 1px solid {c['border']};
    background-color: {c['input']};
}}
QCheckBox::indicator:checked {{
    background-color: {c['accent']};
    border: 1px solid {c['accent']};
}}
QRadioButton::indicator:checked {{
    background-color: {c['accent']};
    border: 1px solid {c['accent']};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border: 1px solid {c['accent']};
}}

/* ===== 数值框箭头 ===== */
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    background-color: {c['base']};
    border-left: 1px solid {c['border']};
    border-bottom: 1px solid {c['border']};
    width: 16px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background-color: {c['base']};
    border-left: 1px solid {c['border']};
    width: 16px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {c['hover']};
}}

/* ===== 分栏 ===== */
QSplitter::handle {{
    background-color: {c['border']};
}}
"""


_current_mode: str = "light"


def set_current_mode(mode: str) -> None:
    """记录当前主题模式（apply_theme 内自动调用）。"""
    global _current_mode
    _current_mode = "dark" if str(mode).lower() == "dark" else "light"


def current_mode() -> str:
    """返回当前主题模式。"""
    return _current_mode


def current_color(key: str) -> str:
    """读当前主题下某个语义色（如 "danger" / "success" / "text_weak"）。"""
    return palette(_current_mode)[key]


def apply_theme(app: QApplication, mode: str) -> None:
    """应用主题：设 Fusion 基础样式 + 覆盖 QSS。"""
    set_current_mode(mode)
    app.setStyle("Fusion")
    app.setStyleSheet(build_qss(_current_mode))