# -*- coding: utf-8 -*-
"""SQLitePresetRepository：自定义预设的 SQLite 实现。

存储位置：settings 表 ``paper_presets`` key，JSON 数组。
沿用现有 settings 表结构，不新增表（避免 schema 迁移）。

依赖：app.infrastructure.database.connection.DatabaseConnection、
      app.domain.entities.preset
被使用：app.container
"""

from __future__ import annotations

import json

from app.domain.entities.preset import (
    PaperPreset,
    preset_from_dict,
    preset_to_dict,
)
from app.infrastructure.database.connection import DatabaseConnection
from app.interfaces.preset_repository import PresetRepository


class SQLitePresetRepository(PresetRepository):
    """自定义预设仓储 SQLite 实现（settings 表 UPSERT）。"""

    KEY = "paper_presets"

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    def load_all(self) -> list[PaperPreset]:
        try:
            row = self._db.connect().execute(
                "SELECT value FROM settings WHERE key = ?", (self.KEY,)
            ).fetchone()
        except Exception:
            return []
        if row is None:
            return []
        try:
            data = json.loads(row["value"])
        except (TypeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        result: list[PaperPreset] = []
        for item in data:
            if isinstance(item, dict):
                preset = preset_from_dict(item)
                if preset is not None:
                    preset.is_builtin = False  # 存储中一律视为自定义
                    result.append(preset)
        return result

    def save_all(self, presets: list[PaperPreset]) -> None:
        payload = [
            preset_to_dict(p) for p in presets if not p.is_builtin
        ]
        text = json.dumps(payload, ensure_ascii=False)
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (self.KEY, text),
            )