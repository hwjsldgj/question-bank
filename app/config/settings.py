"""应用默认配置。

集中存放评分因子默认权重、冷却窗口默认值、AI 调用默认参数与本地
数据库文件名，对应需求文档 Open Decisions 中待确认的默认值项；
用户在设置界面修改后经 ConfigStore 持久化覆盖。

依赖：app.domain.entities.configs
被使用：app.container、app.presentation.views.settings_view、
        app.infrastructure.config_store（无配置时的兜底值）
"""

from app.domain.entities.configs import AIConfig, PromptConfig, ScoringConfig

#: 本地 SQLite 数据库文件名（相对当前工作目录，需求 R18：数据存本机）
DEFAULT_DB_PATH = "question_bank.db"

#: 题目图片的本地存放目录（相对数据库所在目录）
DEFAULT_IMAGE_DIR = "images"

#: 默认科目列表：科目改为"只能从列表中选择"，新科目在设置界面维护
DEFAULT_SUBJECTS: list[str] = [
    "语文",
    "数学",
    "英语",
    "物理",
    "化学",
    "生物",
    "政治",
    "历史",
    "地理",
]

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

#: 默认模块化输出提示词：模块键（见 RecognizeModule）-> 该字段的输出要求片段。
#: 出题者按需勾选模块，服务层只拼装被勾选的片段，一次 AI 调用返回全部所需字段
#: （用户需求：知识点 / 难度 / 答案 / 解析等提供模块化输出提示词，按需给出、一次返回）。
DEFAULT_MODULE_PROMPTS: dict[str, str] = {
    "subject": "subject：科目，必须从这些科目中选择最贴切的一个：{subjects}",
    "knowledge_points": "knowledge_points：知识点数组，1-5 个",
    "question_type": (
        "question_type：single（单选）、multiple（多选）、fill（填空）"
        "或 solution（解答题）"
    ),
    "difficulty": "difficulty：easy、medium 或 hard",
    "quality_flag": "quality_flag：normal、quality 或 low",
    "answer": (
        "answer：选择题填正确选项标号数组（如 [\"A\"]）；"
        "填空题与解答题填参考答案文本数组"
    ),
    "solution": "solution：解析文本，可为空字符串",
}

#: 难度分析框架（不可编辑部分）：入库后的难度分析、批量重析难度都复用它，
#: 其中 ``{module}`` 由用户可编辑的「难度」模块提示词片段填充（用户需求：
#: 提示词里难度不再重复出现两次，难度只维护一处）。
DIFFICULTY_ANALYSIS_FRAME = (
    "你是教辅难度评估专家。请判断下面这道题的难度，只输出难度等级，"
    "不要输出其他内容。\n"
    "输出要求：{module}\n"
    "题型：{type}\n题干：{stem}\n选项：{options}\n答案：{answer}\n"
)

#: 默认 AI 提示词模板（用户可在"设置 -> AI 设置"中修改后持久化）
#: 占位符：辨识总述用 {subjects} / {stem} / {options} / {modules}；
#: 难度模块片段用 {subjects}（同时用于难度分析的输出要求）；
#: 补题用 {subject} / {knowledge_points} / {type} / {difficulty} / {count}
DEFAULT_PROMPT_CONFIG = PromptConfig(
    recognize_prompt=(
        "你是资深出题与审题专家。请阅读下面的题目内容，按下列模块化要求识别字段，"
        "只输出一个 JSON 对象，不要输出多余文字或代码块标记，"
        "并且只包含下列要求中出现的字段：\n"
        "{modules}\n"
        "题干：{stem}\n"
        "现有选项：{options}\n"
        "注意：识别结果仅供参考，最终以出题者人工确认为准。"
    ),
    module_prompts=dict(DEFAULT_MODULE_PROMPTS),
    supplement_prompt=(
        "你是出题专家。请依据以下要求生成题目，输出 JSON 数组，"
        "每道题包含 subject、knowledge_points、type、stem、options、answer、solution 字段。\n"
        "科目：{subject}\n知识点：{knowledge_points}\n题型：{type}\n"
        "难度：{difficulty}\n数量：{count}\n"
    ),
)

