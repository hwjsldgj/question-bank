# -*- coding: utf-8 -*-
"""PaperPreset 实体与序列化：命名组卷条件预设。

分层：
- 本模块只含纯数据 + 序列化逻辑，零外部依赖
- 持久化由 app.interfaces.preset_repository.PresetRepository 抽象
- 业务编排由 app.application.preset_service.PresetService 负责

依赖：app.domain.entities.criteria、app.domain.enums
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.entities.criteria import PaperCriteria, TypeRequirement
from app.domain.enums import Difficulty, QuestionType


@dataclass
class PaperPreset:
    """一条命名预设：名称 + 组卷条件 + 是否内置 + 可选描述。

    内置预设（``is_builtin=True``）来自 app.config.builtin_presets，
    不可删除、不可覆盖；自定义预设可由用户增删。
    """

    name: str
    """预设名称（用户可见；自定义预设中唯一）。"""

    criteria: PaperCriteria
    """组卷条件（含题型、知识点、难度、数量）。"""

    is_builtin: bool = False
    """是否内置预设：True 表示来自默认配置，不可删。"""

    description: str = ""
    """可选描述（UI 悬浮提示）。"""


# ============================================================
# 序列化：dict <-> 实体
# ============================================================

def _item_to_dict(item: TypeRequirement) -> dict:
    return {
        "question_type": item.question_type.value,
        "subject": item.subject,
        "difficulty": item.difficulty.value,
        "count": int(item.count),
        "knowledge_points": list(item.knowledge_points),
        "section": item.section,
    }


def _item_from_dict(raw: dict) -> TypeRequirement | None:
    try:
        return TypeRequirement(
            question_type=QuestionType(raw["question_type"]),
            subject=str(raw.get("subject", "")),
            difficulty=Difficulty(raw["difficulty"]),
            count=int(raw.get("count", 0)),
            knowledge_points=list(raw.get("knowledge_points") or []),
            section=str(raw.get("section", "")),
        )
    except (KeyError, ValueError, TypeError):
        return None


def criteria_to_dict(criteria: PaperCriteria) -> dict:
    """PaperCriteria -> 纯 JSON dict（枚举转 .value）。"""
    return {
        "choice_enabled": bool(criteria.choice_enabled),
        "solution_enabled": bool(criteria.solution_enabled),
        "choice_items": [_item_to_dict(i) for i in criteria.choice_items],
        "fill_enabled": bool(criteria.fill_enabled),
        "fill_items": [_item_to_dict(i) for i in criteria.fill_items],
        "solution_items": [_item_to_dict(i) for i in criteria.solution_items],
        "subject": criteria.subject,
        "title": criteria.title,
        "notes": criteria.notes,
    }


def criteria_from_dict(data: dict) -> PaperCriteria:
    """dict -> PaperCriteria（容忍字段缺失 / 枚举非法）。"""
    def _items(key: str) -> list[TypeRequirement]:
        result = []
        for raw in data.get(key) or []:
            if isinstance(raw, dict):
                item = _item_from_dict(raw)
                if item is not None:
                    result.append(item)
        return result

    return PaperCriteria(
        choice_enabled=bool(data.get("choice_enabled", False)),
        solution_enabled=bool(data.get("solution_enabled", False)),
        choice_items=_items("choice_items"),
        fill_enabled=bool(data.get("fill_enabled", False)),
        fill_items=_items("fill_items"),
        solution_items=_items("solution_items"),
        subject=str(data.get("subject", "")),
        title=str(data.get("title", "")),
        notes=str(data.get("notes", "")),
    )


def preset_to_dict(preset: PaperPreset) -> dict:
    return {
        "name": preset.name,
        "criteria": criteria_to_dict(preset.criteria),
        "is_builtin": bool(preset.is_builtin),
        "description": preset.description,
    }


def preset_from_dict(data: dict) -> PaperPreset | None:
    """dict -> PaperPreset；关键字段缺失时返回 None（容错）。"""
    try:
        return PaperPreset(
            name=str(data["name"]),
            criteria=criteria_from_dict(data.get("criteria") or {}),
            is_builtin=bool(data.get("is_builtin", False)),
            description=str(data.get("description", "")),
        )
    except (KeyError, TypeError):
        return None