# -*- coding: utf-8 -*-
"""PresetRepository 端口：组卷条件预设的持久化抽象。

职责单一：只负责自定义预设（用户创建的）的读写。
内置预设（app.config.builtin_presets）由 PresetService 提供，
不经过本端口。

依赖：app.domain.entities.preset
被使用：app.application.preset_service、app.container
"""

from abc import ABC, abstractmethod

from app.domain.entities.preset import PaperPreset


class PresetRepository(ABC):
    """自定义预设仓储抽象接口。"""

    @abstractmethod
    def load_all(self) -> list[PaperPreset]:
        """读取全部用户自定义预设（无记录时返回空列表）。"""
        pass

    @abstractmethod
    def save_all(self, presets: list[PaperPreset]) -> None:
        """全量覆盖保存（调用方负责合并 / 去重）。"""
        pass