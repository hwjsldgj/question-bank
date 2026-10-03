"""应用默认配置。

集中存放评分因子默认权重、冷却窗口默认值、AI 调用默认参数与本地
数据库文件名，对应需求文档 Open Decisions 中待确认的默认值项；
用户在设置界面修改后经 ConfigStore 持久化覆盖。

依赖：app.domain.entities.configs
被使用：app.container、app.presentation.views.history_settings_view、
        app.infrastructure.config_store（无配置时的兜底值）
"""

from app.domain.entities.configs import AIConfig, ScoringConfig

#: 本地 SQLite 数据库文件名（相对当前工作目录，需求 R18：数据存本机）
DEFAULT_DB_PATH = "question_bank.db"

#: 评分因子默认权重（需求 R8；合计 1.0，惩罚项为减法系数）
DEFAULT_SCORING_CONFIG = ScoringConfig(
    weight_difficulty=0.4,
    weight_knowledge_coverage=0.2,
    weight_quality=0.05,
    weight_use_count=0.15,
    weight_recency=0.2,
    cooldown_value=30,
)

#: AI 服务默认配置（默认为空：未配置状态，需求 R15 第 2 条降级依据）
DEFAULT_AI_CONFIG = AIConfig(
    base_url="",
    api_key="",
    model="",
    timeout_ms=30_000,
    max_retries=2,
)

#: AI 补题在单次组卷请求内的重试上限（需求 R10 第 4 条）
QUESTION_GENERATOR_MAX_RETRIES = 2
