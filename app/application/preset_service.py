# -*- coding: utf-8 -*-
"""PresetService：组卷条件预设的业务编排。

职责：
- 合并内置预设与用户自定义预设（内置在前，自定义在后）
- 自定义预设的保存、删除、改名
- 名称冲突校验

分层：
- 依赖 Port：app.interfaces.preset_repository.PresetRepository
- 不依赖任何 Infrastructure 具体类，由 container 装配

依赖：app.domain.entities.preset、app.domain.errors.PresetError、
      app.interfaces.preset_repository.PresetRepository、
      app.config.builtin_presets.DEFAULT_PRESETS
被使用：app.presentation.widgets.preset_bar、app.container
"""

from __future__ import annotations

from app.application.preset_validator import validate_preset_name
from app.config.builtin_presets import DEFAULT_PRESETS
from app.domain.entities.preset import PaperPreset
from app.domain.errors import PresetError
from app.interfaces.preset_repository import PresetRepository


class PresetService:
    """预设业务编排：内置 + 自定义合并，增删校验。"""

    def __init__(self, repository: PresetRepository) -> None:
        self._repository = repository

    # ---------- 查询 ----------

    def list_all(self) -> list[PaperPreset]:
        """返回内置预设 + 用户自定义预设（内置在前）。"""
        builtin = list(DEFAULT_PRESETS)
        custom = self._repository.load_all()
        return builtin + custom

    def find(self, name: str) -> PaperPreset | None:
        """按名称查找预设（含内置）；未找到返回 None。"""
        for preset in self.list_all():
            if preset.name == name:
                return preset
        return None

    # ---------- 增删 ----------

    def save_custom(self, preset: PaperPreset) -> None:
        """新增或覆盖一条自定义预设（按名称匹配）。

        - 名称不能为空
        - 名称不能与内置预设冲突
        - 覆盖自定义预设时保留名称
        """
        validate_preset_name(preset.name)

        if any(b.name == preset.name for b in DEFAULT_PRESETS):
            raise PresetError(
                f"预设名称「{preset.name}」与内置预设冲突，请换一个名称。"
            )

        preset.is_builtin = False
        custom = self._repository.load_all()
        replaced = False
        for index, item in enumerate(custom):
            if item.name == preset.name:
                custom[index] = preset
                replaced = True
                break
        if not replaced:
            custom.append(preset)
        self._repository.save_all(custom)

    def delete_custom(self, name: str) -> None:
        """删除一条自定义预设；内置预设不可删。"""
        if any(b.name == name for b in DEFAULT_PRESETS):
            raise PresetError(f"内置预设「{name}」不可删除。")

        custom = self._repository.load_all()
        remaining = [p for p in custom if p.name != name]
        if len(remaining) == len(custom):
            raise PresetError(f"未找到预设「{name}」。")
        self._repository.save_all(remaining)