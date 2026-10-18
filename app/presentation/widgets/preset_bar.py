# -*- coding: utf-8 -*-
"""PresetBar：组卷预设模板操作条（纯 UI 组件）。

设计原则：
- 零业务逻辑：不依赖 PresetService，不碰数据库
- 通过 3 个信号（load_clicked / save_clicked / delete_clicked）通知父组件
- 父组件通过 selected_name() / selected_is_builtin() 查询当前选择
- 父组件通过 set_presets(presets) 填充列表

这样 PresetBar 可在任意组卷相关视图复用（如未来历史页的"另存为预设"），
不与具体页面耦合。

依赖：app.domain.entities.preset.PaperPreset（仅数据结构）
被使用：app.presentation.views.paper_generation_view
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from app.domain.entities.preset import PaperPreset


class PresetBar(QGroupBox):
    """预设操作条：下拉选择 + 加载 / 另存为 / 删除 三个按钮。"""

    load_clicked = Signal()
    """用户点击「加载」按钮。"""

    save_clicked = Signal()
    """用户点击「另存为...」按钮。"""

    delete_clicked = Signal()
    """用户点击「删除」按钮。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("预设模板", parent)

        self._presets: list[PaperPreset] = []

        layout = QHBoxLayout(self)

        layout.addWidget(QLabel("预设"))
        self._combo = QComboBox()
        self._combo.setMinimumWidth(200)
        self._combo.currentIndexChanged.connect(self._sync_button_states)
        layout.addWidget(self._combo)

        self._load_btn = QPushButton("加载")
        self._load_btn.clicked.connect(self.load_clicked.emit)
        layout.addWidget(self._load_btn)

        self._save_btn = QPushButton("另存为...")
        self._save_btn.clicked.connect(self.save_clicked.emit)
        layout.addWidget(self._save_btn)

        self._delete_btn = QPushButton("删除")
        self._delete_btn.clicked.connect(self.delete_clicked.emit)
        layout.addWidget(self._delete_btn)

        layout.addStretch(1)

        self._sync_button_states()

    # ---------- 公开 API ----------

    def set_presets(self, presets: list[PaperPreset]) -> None:
        """刷新下拉列表（保持当前选择；若不存在则默认第一项）。

        内置预设在名称后加「（内置）」后缀，避免用户误删。
        """
        current = self.selected_name()
        self._presets = list(presets)

        self._combo.blockSignals(True)
        self._combo.clear()
        for preset in presets:
            label = f"{preset.name}（内置）" if preset.is_builtin else preset.name
            self._combo.addItem(label, preset.name)
        if current:
            idx = self._combo.findData(current)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
        self._combo.blockSignals(False)

        self._sync_button_states()

    def selected_name(self) -> str | None:
        """当前选中预设的名称；无预设时返回 None。"""
        data = self._combo.currentData()
        return str(data) if data else None

    def selected_is_builtin(self) -> bool:
        """当前选中项是否为内置预设（内置不可删）。"""
        name = self.selected_name()
        if not name:
            return False
        return any(p.name == name and p.is_builtin for p in self._presets)

    # ---------- 内部 ----------

    def _sync_button_states(self) -> None:
        has = self._combo.count() > 0
        self._load_btn.setEnabled(has)
        self._save_btn.setEnabled(True)
        self._delete_btn.setEnabled(has and not self.selected_is_builtin())