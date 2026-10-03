"""提示词填充工具：把用户可编辑的提示词模板安全地实例化。

用户在"设置 -> AI 设置"中修改提示词（用户需求），模板使用 ``{name}`` 占位符；
本模块提供容错填充：未知占位符原样保留、模板残缺时退回模板文本本身，
保证提示词配置异常不会导致 AI 调用直接失败。

依赖：app.domain.entities.configs、app.config.settings
被使用：app.application.difficulty_service、app.application.question_service
"""

from app.config.settings import DEFAULT_PROMPT_CONFIG
from app.domain.entities.configs import PromptConfig


class _SafeDict(dict):
    """缺失键返回 ``{key}`` 原文，避免因占位符拼写错误抛 KeyError。"""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def load_prompt_config(config_store) -> PromptConfig:
    """读取提示词配置；读取失败或无配置时返回默认模板。"""
    if config_store is None:
        return DEFAULT_PROMPT_CONFIG
    try:
        return config_store.load_prompt_config()
    except Exception:  # noqa: BLE001 - 配置读取失败不应阻断业务
        return DEFAULT_PROMPT_CONFIG


def render(template: str, fallback: str = "", **values: object) -> str:
    """填充提示词模板中的 ``{name}`` 占位符。

    :param template: 模板文本（用户可编辑）
    :param fallback: 模板为空时使用的兜底模板
    :param values: 占位符取值
    """
    text = template or fallback
    try:
        return text.format_map(_SafeDict(**values))
    except (ValueError, IndexError):
        return text
