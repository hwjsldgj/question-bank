# -*- coding: utf-8 -*-
"""预设名称校验：纯函数，独立文件便于复用与单测。

依赖：app.domain.errors.PresetError
被使用：app.application.preset_service
"""

from __future__ import annotations

import re

from app.domain.errors import PresetError


MAX_NAME_LEN = 40
_INVALID_CHARS = re.compile(r"[\r\n\t]")


def validate_preset_name(name: str) -> None:
    """校验预设名称；非法时抛 PresetError。

    规则：
    - 非空
    - 去除首尾空白后非空
    - 长度 <= 40
    - 不含控制字符（换行 / 制表符）
    """
    text = (name or "").strip()
    if not text:
        raise PresetError("预设名称不能为空。")
    if len(text) > MAX_NAME_LEN:
        raise PresetError(f"预设名称不能超过 {MAX_NAME_LEN} 个字符。")
    if _INVALID_CHARS.search(text):
        raise PresetError("预设名称不能包含换行或制表符。")