"""配置值对象：ScoringConfig / AIConfig / ExportOptions。

对应设计文档 "Data Models -> ScoringConfig / AIConfig"。
默认取值见 app.config.settings；持久化由 ConfigStore 接口的
基础设施实现负责（需求 R15）。

依赖：app.domain.enums
被使用：app.config.settings、app.interfaces.repositories.ConfigStore、
        app.application.selection_scorer、app.application.cooldown_policy、
        app.application.weighted_sampler、app.infrastructure.ai.ai_client
"""

from dataclasses import dataclass, field

from app.domain.enums import CooldownMode, ExportFormat


@dataclass
class ScoringConfig:
    """选题评分与冷却窗口配置（需求 R8 / R13）。

    权重因子方向：difficulty_match / knowledge_coverage / quality 为正向加分，
    use_count / recency 对应的惩罚项为负向减法。
    """

    weight_difficulty: float = 0.4
    """难度匹配度权重 w1。"""

    weight_knowledge_coverage: float = 0.2
    """知识点覆盖权重 w2。"""

    weight_quality: float = 0.05
    """人工质量权重 w3。"""

    weight_use_count: float = 0.15
    """使用频次惩罚系数 w4。"""

    weight_recency: float = 0.2
    """最近使用惩罚系数 w5。"""

    cooldown_mode: CooldownMode = CooldownMode.DAYS
    """冷却窗口计量方式：按天数或按最近 N 次组卷任务。"""

    cooldown_value: int = 30
    """冷却窗口长度：mode 为 days 时表示天数，为 tasks 时表示组卷任务次数。"""

    epsilon: float = 1e-6
    """抽样权重下限（设计文档 Correctness Properties #6：权重恒正）。"""


@dataclass
class AIConfig:
    """AI 服务 API 配置（需求 R15），密钥仅存本机。

    接口约定为 OpenAI 兼容 HTTP API，用户可配置 base_url / model / key。
    """

    base_url: str = ""
    """API 接口地址，如 https://api.example.com/v1。"""

    api_key: str = ""
    """API Key，仅保存在本机配置存储。"""

    model: str = ""
    """模型名称。"""

    timeout_ms: int = 30_000
    """单次请求超时（毫秒），需求 R15 第 4 条。"""

    max_retries: int = 2
    """失败重试次数上限。"""

    def is_configured(self) -> bool:
        """判断配置是否完整（base_url / api_key / model 均非空）。"""
        return bool(self.base_url and self.api_key and self.model)


@dataclass
class PromptConfig:
    """AI 提示词配置（用户需求：AI 设置中可修改提示词）。

    可编辑模板分两类：

    - ``recognize_prompt``：AI 辨识总述模板（占位符 ``{subjects}`` / ``{stem}`` /
      ``{options}`` / ``{modules}``，其中 ``{modules}`` 由被勾选的模块提示词拼装）
    - ``module_prompts``：模块化输出提示词，键为
      :class:`app.domain.enums.RecognizeModule` 取值（科目 / 知识点 / 题型 / 难度 /
      质量标记 / 答案 / 解析）；出题者按需勾选模块，服务层只拼装被勾选的部分，
      一次 AI 调用即返回全部所需字段（用户需求：模块化输出、按需给出、一次返回）
    - ``supplement_prompt``：题库不足时的 AI 补题

    难度只维护一处提示词：``module_prompts["difficulty"]`` 既用于 AI 辨识的难度字段，
    也作为入库后难度分析（含批量重析）的输出要求，不再单独设置难度提示词
    （用户需求：AI 的提示词中难度不要重复）。

    模板中的 ``{name}`` 占位符由调用方填充；修改后立即用于后续 AI 调用。
    """

    recognize_prompt: str = ""
    """AI 辨识总述提示词模板。"""

    module_prompts: dict[str, str] = field(default_factory=dict)
    """模块化输出提示词：模块键 -> 该字段的输出要求片段。"""

    supplement_prompt: str = ""
    """AI 补题提示词模板。"""


@dataclass
class ExportOptions:
    """导出选项（需求 R12 / R18）。

    :param include_answer_page: 是否在卷末附答案页（当前需求恒为 True，
        保留开关以便扩展）
    :param formats: 允许的导出格式集合，当前支持 MD / PDF
    """

    include_answer_page: bool = True
    formats: tuple[ExportFormat, ...] = (ExportFormat.MD, ExportFormat.PDF)
