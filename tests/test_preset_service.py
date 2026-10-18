# -*- coding: utf-8 -*-
"""PresetService 单元测试：覆盖增删、内置保护、名称校验、序列化往返。"""

from __future__ import annotations

import pytest

from app.application.preset_service import PresetService
from app.application.preset_validator import validate_preset_name
from app.config.builtin_presets import DEFAULT_PRESETS
from app.domain.entities.criteria import PaperCriteria, TypeRequirement
from app.domain.entities.preset import (
    PaperPreset,
    criteria_from_dict,
    criteria_to_dict,
)
from app.domain.enums import Difficulty, QuestionType
from app.domain.errors import PresetError
from app.interfaces.preset_repository import PresetRepository


class _InMemoryRepo(PresetRepository):
    """测试用内存仓储。"""

    def __init__(self) -> None:
        self._data: list[PaperPreset] = []

    def load_all(self) -> list[PaperPreset]:
        return list(self._data)

    def save_all(self, presets: list[PaperPreset]) -> None:
        self._data = list(presets)


def _sample_preset(name: str = "我的预设") -> PaperPreset:
    return PaperPreset(
        name=name,
        criteria=PaperCriteria(
            subject="数学",
            choice_enabled=True,
            choice_items=[
                TypeRequirement(
                    QuestionType.SINGLE, "数学", Difficulty.MEDIUM, 5
                ),
            ],
        ),
        is_builtin=False,
    )


# ---------- 序列化 ----------

def test_criteria_roundtrip() -> None:
    original = PaperCriteria(
        subject="数学",
        choice_enabled=True,
        choice_items=[
            TypeRequirement(
                QuestionType.SINGLE, "数学", Difficulty.EASY, 8,
                knowledge_points=["椭圆"], section="9 解析几何",
            ),
        ],
        fill_enabled=True,
        fill_items=[
            TypeRequirement(QuestionType.FILL, "数学", Difficulty.HARD, 2),
        ],
        solution_enabled=True,
        solution_items=[
            TypeRequirement(QuestionType.SOLUTION, "数学", Difficulty.MEDIUM, 3),
        ],
    )
    restored = criteria_from_dict(criteria_to_dict(original))
    assert restored.subject == original.subject
    assert restored.choice_enabled == original.choice_enabled
    assert len(restored.choice_items) == 1
    assert restored.choice_items[0].knowledge_points == ["椭圆"]
    assert restored.choice_items[0].section == "9 解析几何"


# ---------- 名称校验 ----------

@pytest.mark.parametrize("bad", ["", "  ", "\t", "\n", "x" * 41])
def test_validate_preset_name_rejects(bad: str) -> None:
    with pytest.raises(PresetError):
        validate_preset_name(bad)


def test_validate_preset_name_accepts() -> None:
    validate_preset_name("一轮复习")
    validate_preset_name("a" * 40)


# ---------- 服务：列表 / 增删 ----------

def test_list_all_returns_builtin_first() -> None:
    service = PresetService(_InMemoryRepo())
    presets = service.list_all()
    assert len(presets) == len(DEFAULT_PRESETS)
    assert all(p.is_builtin for p in presets)


def test_save_custom_appends() -> None:
    repo = _InMemoryRepo()
    service = PresetService(repo)
    service.save_custom(_sample_preset("我的"))
    all_presets = service.list_all()
    assert any(p.name == "我的" and not p.is_builtin for p in all_presets)


def test_save_custom_rejects_builtin_name() -> None:
    service = PresetService(_InMemoryRepo())
    with pytest.raises(PresetError, match="内置"):
        service.save_custom(_sample_preset(DEFAULT_PRESETS[0].name))


def test_save_custom_overwrites_same_name() -> None:
    repo = _InMemoryRepo()
    service = PresetService(repo)
    service.save_custom(_sample_preset("我的"))
    modified = _sample_preset("我的")
    modified.description = "更新后"
    service.save_custom(modified)

    custom = [p for p in service.list_all() if not p.is_builtin]
    assert len(custom) == 1
    assert custom[0].description == "更新后"


def test_delete_custom_ok() -> None:
    repo = _InMemoryRepo()
    service = PresetService(repo)
    service.save_custom(_sample_preset("待删"))
    service.delete_custom("待删")
    assert not any(p.name == "待删" for p in service.list_all())


def test_delete_builtin_rejected() -> None:
    service = PresetService(_InMemoryRepo())
    with pytest.raises(PresetError, match="内置"):
        service.delete_custom(DEFAULT_PRESETS[0].name)


def test_delete_missing_rejected() -> None:
    service = PresetService(_InMemoryRepo())
    with pytest.raises(PresetError, match="未找到"):
        service.delete_custom("不存在的名字")


def test_find_returns_builtin_and_custom() -> None:
    repo = _InMemoryRepo()
    service = PresetService(repo)
    service.save_custom(_sample_preset("我的"))
    assert service.find(DEFAULT_PRESETS[0].name) is not None
    assert service.find("我的") is not None
    assert service.find("不存在") is None