"""应用默认配置。

集中存放评分因子默认权重、冷却窗口默认值、AI 调用默认参数与本地
数据库文件名，对应需求文档 Open Decisions 中待确认的默认值项；
用户在设置界面修改后经 ConfigStore 持久化覆盖。

依赖：app.domain.entities.configs
被使用：app.container、app.presentation.views.settings_view、
        app.infrastructure.config_store（无配置时的兜底值）
"""

from app.domain.entities.configs import AIConfig, PromptConfig, ScoringConfig
from app.domain.enums import QuestionType

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

#: 默认知识板块：科目 -> 知识板块 -> 该板块下的细分知识点。
#: 用于录入页选科后联动板块与知识点，也作为 AI 辨识"先分级、再细分知识点"的
#: 取值范围；用户可在"设置 -> 知识板块"中增删改，新科目下的板块自动使用空映射。
DEFAULT_KNOWLEDGE_SECTIONS: dict[str, dict[str, list[str]]] = {
    "数学": {
        "代数": ["一元二次方程", "因式分解", "分式方程", "整式", "二次函数"],
        "几何": ["三角形", "相似三角形", "圆", "勾股定理", "三角函数"],
        "概率统计": ["概率", "统计", "排列组合", "方差与标准差"],
    },
    "语文": {
        "语言文字": ["字音字形", "词语理解", "病句辨析", "标点符号"],
        "古诗文": ["文言文阅读", "古诗词鉴赏", "默写", "文言实词"],
        "现代文阅读": ["记叙文", "说明文", "议论文", "散文"],
        "写作": ["记叙文写作", "议论文写作", "材料作文"],
    },
    "英语": {
        "语法": ["时态", "语态", "从句", "非谓语动词"],
        "词汇": ["词义辨析", "短语搭配", "构词法"],
        "阅读": ["细节理解", "推理判断", "主旨大意"],
        "写作": ["书面表达", "应用文"],
    },
    "物理": {
        "力学": ["运动学", "牛顿定律", "功与能", "动量"],
        "电磁学": ["静电场", "恒定电流", "磁场", "电磁感应"],
        "热学": ["分子动理论", "热力学定律"],
        "光学": ["几何光学", "波动光学"],
    },
    "化学": {
        "无机化学": ["元素周期表", "氧化还原", "离子反应", "化学键"],
        "有机化学": ["烃", "烃的衍生物", "有机合成"],
        "化学实验": ["物质检验", "气体制备", "实验设计"],
    },
    "生物": {
        "分子与细胞": ["细胞结构", "细胞代谢", "遗传的分子基础"],
        "遗传与进化": ["遗传规律", "生物进化"],
        "稳态与环境": ["内环境", "生态系统", "免疫调节"],
    },
    "政治": {
        "经济生活": ["商品与货币", "企业与经营", "财政与税收"],
        "政治生活": ["公民权利", "政府职能", "国际社会"],
        "文化生活": ["文化传承", "精神文明"],
        "哲学": ["唯物论", "辩证法", "认识论"],
    },
    "历史": {
        "中国古代史": ["先秦", "秦汉", "唐宋", "明清"],
        "中国近现代史": ["近代化探索", "新民主主义革命", "改革开放"],
        "世界史": ["文艺复兴", "工业革命", "两次世界大战"],
    },
    "地理": {
        "自然地理": ["地球运动", "气候", "地形地貌", "水文"],
        "人文地理": ["人口", "城市", "农业与工业"],
        "区域地理": ["中国区域", "世界区域"],
    },
}

#: 评分因子默认权重（需求 R8；合计 1.0，惩罚项为减法系数）
DEFAULT_SCORING_CONFIG = ScoringConfig(
    weight_difficulty=0.4,
    weight_knowledge_coverage=0.2,
    weight_quality=0.05,
    weight_use_count=0.15,
    weight_recency=0.2,
    cooldown_value=30,
)

#: 组卷后各题型的默认单题分值：出题者未设分值时即可直接导出试卷，
#: 仍可在组卷页按题型或逐题调整（需求 R11）
DEFAULT_TYPE_SCORES: dict[QuestionType, float] = {
    QuestionType.SINGLE: 2.0,
    QuestionType.MULTIPLE: 3.0,
    QuestionType.FILL: 2.0,
    QuestionType.SOLUTION: 10.0,
}

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
    "knowledge_points": (
        "knowledge_points：先判断这道题涉及哪些知识板块（只能从下面的板块列表中选，"
        "一道题可涉及多个板块），再对每个板块细化到具体的细分知识点；"
        "输出必须是一个 JSON 对象，格式为 {{\"板块名\": [\"细分知识点1\", \"细分知识点2\"], ...}}，"
        "不要输出解题过程或其他多余文字。\n"
        "可用知识板块（只从下列里选，格式为\"板块名：细分知识点\"）：{sections}"
    ),
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
    "stem": "stem：题目正文（题干）文本；若原文题干残缺或不完整，请依据题意补全为通顺完整的题干",
    "options": "options：选择题选项数组，每项是 {\"key\": \"A\", \"text\": \"…\"} 对象；若原文选项不足 2 项，请依据题意补充到至少 2 项",
}

#: 难度分析框架（不可编辑部分）：入库后的难度分析、批量重析难度都复用它，
#: 其中 ``{module}`` 由用户可编辑的「难度」模块提示词片段填充（用户需求：
#: 提示词里难度不再重复出现两次，难度只维护一处）。
DIFFICULTY_ANALYSIS_FRAME = (
    "你是教辅难度评估专家。请依据题目内容判断难度，只输出难度等级，"
    "不要输出其他内容。\n"
    "难度分级依据（请严格按下列标准，结合题目所涉及的知识点与思维要求判断）：\n"
    "  - 易（easy）：只涉及单一基础知识点，直接套用定义或公式即可，"
    "无需变形与推理，一步可得答案；\n"
    "  - 中（medium）：涉及 1-2 个知识点的简单组合，需要一次变形或"
    "两步以内推理，属于常规训练题；\n"
    "  - 难（hard）：涉及 2 个以上知识点的综合运用，需要多步推理、"
    "分类讨论、构造辅助或非常规思路。\n"
    "注意：所依据的知识点必须出现在题目内容（题干、选项、答案）中，"
    "不得自行补充题目未给出的知识点；若题目内容不足以判断难度，"
    "请返回 medium。\n"
    "输出要求：{module}\n"
    "关联知识点：{knowledge_points}\n"
    "题型：{type}\n题干：{stem}\n选项：{options}\n答案：{answer}\n"
)

#: 默认 AI 提示词模板（用户可在"设置 -> AI 设置"中修改后持久化）
#: 占位符：辨识总述用 {subjects} / {stem} / {options} / {modules}；
#: 难度模块片段用 {subjects}（AI 辨识场景）；
#: 补题用 {subject} / {knowledge_points} / {type} / {difficulty} / {count}；
#: 难度分析框架额外使用 {knowledge_points}，由 DifficultyService 传入
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
