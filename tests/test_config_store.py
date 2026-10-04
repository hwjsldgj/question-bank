"""配置存储测试：AI 配置、评分与冷却、提示词与科目列表的持久化与兜底。"""

from app.application.prompt_utils import load_prompt_config, render
from app.config.settings import DEFAULT_PROMPT_CONFIG, DEFAULT_SUBJECTS
from app.container import build_container
from app.domain.entities.configs import AIConfig, PromptConfig
from app.infrastructure.database.schema import ensure_schema


def _container(tmp_path):
    """临时库上的完整对象图（含建表）。"""
    graph = build_container(str(tmp_path / "config.db"))
    ensure_schema(graph.db.connect())
    return graph


def test_subjects_default_and_persist(tmp_path) -> None:
    """科目列表：默认提供，保存后读取一致且自动去重。"""
    container = _container(tmp_path)
    try:
        assert container.config_store.load_subjects() == DEFAULT_SUBJECTS
        container.config_store.save_subjects(["数学", "物理", "数学"])
        assert container.config_store.load_subjects() == ["数学", "物理"]
    finally:
        container.db.close()


def test_prompt_config_roundtrip_and_fallback(tmp_path) -> None:
    """提示词：空模板回退默认值，自定义模板原样保留（AI 设置中可修改）。"""
    container = _container(tmp_path)
    try:
        store = container.config_store
        assert store.load_prompt_config().recognize_prompt == (
            DEFAULT_PROMPT_CONFIG.recognize_prompt
        )

        store.save_prompt_config(
            PromptConfig(recognize_prompt="自定义辨识 {stem}", supplement_prompt="")
        )
        loaded = store.load_prompt_config()
        assert loaded.recognize_prompt == "自定义辨识 {stem}"
        # 空模板回退默认值，避免 AI 调用失去上下文
        assert loaded.supplement_prompt == DEFAULT_PROMPT_CONFIG.supplement_prompt
    finally:
        container.db.close()


def test_legacy_difficulty_prompt_is_dropped(tmp_path) -> None:
    """旧的难度分析提示词配置被忽略：难度只在模块提示词里维护一处（用户需求）。"""
    import json

    container = _container(tmp_path)
    try:
        store = container.config_store
        store._write_key(
            store.KEY_PROMPT,
            json.dumps(
                {
                    "recognize_prompt": "旧总述 {stem}",
                    "difficulty_prompt": "旧的难度分析提示词",
                    "module_prompts": {"difficulty": "difficulty：只给 easy/medium/hard"},
                },
                ensure_ascii=False,
            ),
        )
        loaded = store.load_prompt_config()
        assert not hasattr(loaded, "difficulty_prompt")
        assert loaded.recognize_prompt == "旧总述 {stem}"
        assert loaded.module_prompts["difficulty"] == "difficulty：只给 easy/medium/hard"
    finally:
        container.db.close()


def test_module_prompts_merge_per_module(tmp_path) -> None:
    """模块化输出提示词：只覆盖部分模块时，其余模块仍用默认片段（按需给出）。"""
    from app.config.settings import DEFAULT_MODULE_PROMPTS
    from app.domain.enums import RecognizeModule

    container = _container(tmp_path)
    try:
        store = container.config_store
        loaded = store.load_prompt_config()
        assert set(loaded.module_prompts) == set(DEFAULT_MODULE_PROMPTS)
        for module in RecognizeModule:
            assert loaded.module_prompts[module.value]

        # 只改「答案」与「难度」两个模块，并把「解析」清空
        store.save_prompt_config(
            PromptConfig(
                module_prompts={
                    "answer": "answer：只给标号",
                    "difficulty": "",
                    "solution": "   ",
                }
            )
        )
        loaded = store.load_prompt_config()
        assert loaded.module_prompts["answer"] == "answer：只给标号"
        # 空片段回退默认
        assert loaded.module_prompts["difficulty"] == DEFAULT_MODULE_PROMPTS["difficulty"]
        assert loaded.module_prompts["solution"] == DEFAULT_MODULE_PROMPTS["solution"]
        assert loaded.module_prompts["subject"] == DEFAULT_MODULE_PROMPTS["subject"]
    finally:
        container.db.close()


def test_prompt_render_keeps_unknown_placeholders(tmp_path) -> None:
    """提示词填充：未知占位符原样保留，不抛异常。"""
    container = _container(tmp_path)
    try:
        prompts = load_prompt_config(container.config_store)
        text = render("题干：{stem}，未知：{unknown}", "", stem="内容")
        assert text == "题干：内容，未知：{unknown}"
        assert prompts.recognize_prompt
        assert render("", "兜底 {stem}", stem="X") == "兜底 X"
    finally:
        container.db.close()


def test_ai_config_roundtrip(tmp_path) -> None:
    """AI 配置保存后读取一致，未配置时 is_configured 为假（需求 R15）。"""
    container = _container(tmp_path)
    try:
        store = container.config_store
        assert store.load_ai_config().is_configured() is False
        store.save_ai_config(
            AIConfig(base_url="https://api.example.com/v1", api_key="k", model="m")
        )
        config = store.load_ai_config()
        assert config.is_configured() is True
        assert config.model == "m"
    finally:
        container.db.close()
