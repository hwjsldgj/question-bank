"""SQLiteConfigStore：AI 与评分配置的本机持久化实现。

实现接口：app.interfaces.repositories.ConfigStore
依赖：app.infrastructure.database.connection.DatabaseConnection、
      app.infrastructure.database.schema（settings 键值表）、
      app.domain.entities.configs
被使用：app.container（装配）、app.presentation.views.settings_view

隐私约束（需求 R18）：API Key 仅保存在本机 settings 表，禁止外传或写入日志。

说明：本模块的"读取失败回退默认值 / JSON 键值存取"属于框架级管道代码，
已实现以便组合根（container）完成装配；业务规则一概位于 application 层。
"""

import json
import sqlite3

from app.config.settings import (
    DEFAULT_AI_CONFIG,
    DEFAULT_KNOWLEDGE_SECTIONS,
    DEFAULT_MODULE_PROMPTS,
    DEFAULT_PROMPT_CONFIG,
    DEFAULT_SCORING_CONFIG,
    DEFAULT_SUBJECTS,
)
from app.domain.entities.configs import AIConfig, PromptConfig, ScoringConfig
from app.domain.entities.knowledge_section import KnowledgeSection
from app.infrastructure.database.connection import DatabaseConnection
from app.interfaces.repositories import ConfigStore


class SQLiteConfigStore(ConfigStore):
    """配置存储 SQLite 实现：settings 表键值对，值为 JSON 文本。"""

    KEY_DEBUG = "debug_config"
    KEY_AI = "ai_config"
    KEY_SCORING = "scoring_config"
    KEY_PROMPT = "prompt_config"
    KEY_SUBJECTS = "subjects"
    KEY_SECTIONS = "knowledge_sections"

    def __init__(self, db: DatabaseConnection) -> None:
        """注入数据库连接管理器。"""
        self._db = db

    def load_debug_config(self) -> "DebugConfig":
        """读取调试配置；无记录时返回默认值。"""
        from app.domain.entities.configs import DebugConfig
        raw = self._read_key(self.KEY_DEBUG)
        if raw is None:
            return DebugConfig()
        try:
            import json as _json
            data = _json.loads(raw)
        except (TypeError, ValueError):
            return DebugConfig()
        return DebugConfig(**self._filter_fields(DebugConfig, data))

    def save_debug_config(self, config) -> None:
        """保存调试配置（UPSERT）。"""
        self._write_key(self.KEY_DEBUG, self._dump(config))

    def load_ai_config(self) -> AIConfig:
        """读取 AI 配置；无记录或解析失败时返回默认值（视为未配置）。"""
        raw = self._read_key(self.KEY_AI)
        if raw is None:
            return DEFAULT_AI_CONFIG
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return DEFAULT_AI_CONFIG
        return AIConfig(**self._filter_fields(AIConfig, data))

    def save_ai_config(self, config: AIConfig) -> None:
        """保存 AI 配置（UPSERT，需求 R15 第 3 条）。"""
        self._write_key(self.KEY_AI, self._dump(config))

    def load_scoring_config(self) -> ScoringConfig:
        """读取评分与冷却配置；无记录时返回默认配置。"""
        raw = self._read_key(self.KEY_SCORING)
        if raw is None:
            return DEFAULT_SCORING_CONFIG
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return DEFAULT_SCORING_CONFIG
        return ScoringConfig(**self._filter_fields(ScoringConfig, data))

    def save_scoring_config(self, config: ScoringConfig) -> None:
        """保存评分与冷却配置（UPSERT）。"""
        self._write_key(self.KEY_SCORING, self._dump(config))

    def load_prompt_config(self) -> PromptConfig:
        """读取 AI 提示词配置；无记录或解析失败时返回默认模板。

        模块化输出提示词（``module_prompts``）按模块逐项合并：用户只覆盖了
        部分模块时，其余模块仍使用默认片段，避免某个模块被清空后失去输出要求。
        """
        raw = self._read_key(self.KEY_PROMPT)
        if raw is None:
            return DEFAULT_PROMPT_CONFIG
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return DEFAULT_PROMPT_CONFIG
        merged = dict(DEFAULT_PROMPT_CONFIG.__dict__)
        saved = self._filter_fields(PromptConfig, data)
        # 空模板回退默认值，避免用户清空后 AI 调用失去上下文
        for key in list(merged):
            if key == "module_prompts":
                continue
            merged[key] = saved.get(key) or merged[key]
        merged["module_prompts"] = self._merge_module_prompts(
            saved.get("module_prompts")
        )
        return PromptConfig(**merged)

    @staticmethod
    def _merge_module_prompts(saved) -> dict[str, str]:
        """逐模块合并输出提示词：未保存或为空的模块使用默认片段。"""
        merged = dict(DEFAULT_MODULE_PROMPTS)
        if isinstance(saved, dict):
            for key, value in saved.items():
                name = str(key).strip()
                text = "" if value is None else str(value).strip()
                if name in merged and text:
                    merged[name] = text
        return merged

    def save_prompt_config(self, config: PromptConfig) -> None:
        """保存 AI 提示词配置（UPSERT），后续 AI 调用立即生效。"""
        self._write_key(self.KEY_PROMPT, self._dump(config))

    def load_subjects(self) -> list[str]:
        """读取可选科目列表；无记录或为空时返回默认科目。"""
        raw = self._read_key(self.KEY_SUBJECTS)
        if raw is None:
            return list(DEFAULT_SUBJECTS)
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return list(DEFAULT_SUBJECTS)
        if not isinstance(data, list):
            return list(DEFAULT_SUBJECTS)
        subjects = [str(item).strip() for item in data if str(item).strip()]
        return subjects or list(DEFAULT_SUBJECTS)

    def save_subjects(self, subjects: list[str]) -> None:
        """保存可选科目列表（去重且保持顺序）。"""
        cleaned: list[str] = []
        for subject in subjects:
            name = str(subject).strip()
            if name and name not in cleaned:
                cleaned.append(name)
        self._write_key(self.KEY_SUBJECTS, json.dumps(cleaned, ensure_ascii=False))

    def load_sections(self) -> list[KnowledgeSection]:
        """读取知识点板块列表；无记录或格式非法时返回默认值。

        返回按科目、板块顺序排列的 ``KnowledgeSection`` 列表，调用方按需按科目过滤。
        """
        raw = self._read_key(self.KEY_SECTIONS)
        if raw is None:
            return self._default_sections()
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return self._default_sections()
        if not isinstance(data, dict):
            return self._default_sections()
        sections: list[KnowledgeSection] = []
        seen = set()
        for subject, subject_data in data.items():
            if not isinstance(subject_data, dict):
                continue
            subject_name = str(subject).strip()
            if not subject_name:
                continue
            for name, points in subject_data.items():
                if not isinstance(points, list):
                    continue
                section_name = str(name).strip()
                if not section_name:
                    continue
                key = (subject_name, section_name)
                if key in seen:
                    continue
                seen.add(key)
                section = KnowledgeSection(subject=subject_name, section=section_name)
                for point in points:
                    point_name = str(point).strip()
                    if point_name and point_name not in section.knowledge_points:
                        section.knowledge_points.append(point_name)
                sections.append(section)
        return sections or self._default_sections()

    def save_sections(self, sections: list[KnowledgeSection]) -> None:
        """保存知识点板块映射（科目 -> 板块 -> 细分知识点，去重并保持顺序）。"""
        normalized: dict[str, dict[str, list[str]]] = {}
        for section in sections:
            if not isinstance(section, KnowledgeSection):
                continue
            subject_name = str(section.subject).strip()
            section_name = str(section.section).strip()
            if not subject_name or not section_name:
                continue
            subject_map = normalized.setdefault(subject_name, {})
            deduped: list[str] = []
            for point in section.knowledge_points:
                point_name = str(point).strip()
                if point_name and point_name not in deduped:
                    deduped.append(point_name)
            if deduped:
                subject_map[section_name] = deduped
        self._write_key(
            self.KEY_SECTIONS, json.dumps(normalized, ensure_ascii=False)
        )

    @staticmethod
    def _default_sections() -> list[KnowledgeSection]:
        """默认知识点板块列表（无持久化配置时的兜底）。"""
        return [
            KnowledgeSection(subject=subject, section=section, knowledge_points=list(points))
            for subject, groups in DEFAULT_KNOWLEDGE_SECTIONS.items()
            for section, points in groups.items()
        ]

    def _read_key(self, key: str) -> str | None:
        """读取单个配置键；表未创建时返回 None（启动早期容错）。"""
        try:
            row = self._db.connect().execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        return row["value"] if row is not None else None

    def _write_key(self, key: str, value: str) -> None:
        """写入单个配置键（UPSERT 语义）。"""
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    @staticmethod
    def _filter_fields(config_cls, data: dict) -> dict:
        """过滤 JSON 数据中与配置字段不匹配的键（向后兼容容错）。"""
        fields = set(config_cls.__dataclass_fields__)
        return {k: v for k, v in data.items() if k in fields}

    @staticmethod
    def _dump(config) -> str:
        """配置对象序列化为 JSON 文本。"""
        return json.dumps(config.__dict__, ensure_ascii=False)
