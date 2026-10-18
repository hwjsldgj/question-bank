"""本地四核 AI 推理引擎：题型 / 大类 / 细分考点 / 难度。

- 四个模型：type(4) / section(13) / subtopic(81 多标签) / difficulty(3)
- 延迟导入：首次调用才 import torch/transformers，避免启动加载重型库
- 置信度策略：模型 top-1 概率 >= 0.7 直接采用；否则回退规则
- type：模型只判"选择题 vs 非选择题"大方向，单选/多选/填空/解答的具体细分
  由答案形态与选项结构（最硬信号）决定；避免答案拼接干扰模型
- subtopic 依赖 section：section 为空时跳过（无前置大类无法定位考点）
- difficulty：规则明确 hard/medium 时直接采用；easy 或拿不准时调模型复核
"""

from app.interfaces.local_ai import ILocalAIEngine

import json
from pathlib import Path
import re
import threading
from typing import Any


#: 置信度阈值：模型 top-1 概率 >= 0.7 直接采用；否则走规则
CONFIDENCE_THRESHOLD = 0.7


#: 大类关键词规则（section 模型置信度不足时兜底）
_SECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "1 集合与常用逻辑用语": (
        "集合", "交集", "并集", "补集", "子集", "∈", "∉", "⊆", "⊇",
        "充分条件", "必要条件", "充要条件", "全称量词", "存在量词",
    ),
    "2 函数": (
        "定义域", "值域", "奇函数", "偶函数", "周期函数", "对数函数",
        "指数函数", "幂函数", "函数零点", "函数图像",
    ),
    "3 导数": (
        "导数", "极值点", "极大值", "极小值", "切线方程", "切点",
        "单调区间", "导函数",
    ),
    "4 三角函数与解三角形": (
        "三角函数", "sin", "cos", "tan", "正弦", "余弦", "正切",
        "解三角形", "三角形面积",
    ),
    "5 平面向量": (
        "平面向量", "数量积", "向量共线", "向量垂直", "向量夹角", "向量模",
    ),
    "6 数列": (
        "等差数列", "等比数列", "通项公式", "前n项和", "递推公式",
        "公差", "公比",
    ),
    "7 不等式": (
        "一元二次不等式", "基本不等式", "线性规划", "恒成立",
    ),
    "8 立体几何": (
        "棱锥", "棱柱", "圆锥", "圆柱", "二面角", "异面直线",
        "线面平行", "线面垂直", "面面平行", "面面垂直", "表面积",
    ),
    "9 解析几何": (
        "椭圆", "双曲线", "抛物线", "圆心", "圆的方程",
        "弦长", "焦点", "离心率", "准线", "轨迹方程",
    ),
    "10 计数原理": (
        "排列数", "组合数", "二项式", "展开式", "计数原理",
    ),
    "11 概率与统计": (
        "古典概型", "随机变量", "分布列", "数学期望", "方差",
        "抽样", "回归方程", "独立性检验",
    ),
    "12 复数": (
        "复数", "虚部", "实部", "共轭复数", "复数的模",
    ),
    "13 算法初步": (
        "程序框图", "算法语句", "伪代码", "循环结构", "判断框",
    ),
}

#: 难度规则关键词
_HARD_LOGIC_KW = ("恒成立", "任意", "存在", "唯一", "至少", "至多", "恰有")
_HARD_OPS_KW = (
    "证明", "极值", "零点个数", "取值范围", "轨迹方程",
    "抛物线", "双曲线", "椭圆", "导数",
)
_MEDIUM_OPS_KW = ("等比", "等差", "三角函数", "单调性", "离心率", "距离", "向量")

#: 答案中的分隔符：多个字母或标点视为多选信号
_ANSWER_SEPARATORS = (",", "，", "、", ";", "；", " ")


class BaseClassifierModel:
    """动态构建 BERT 分类头（base_model + Dropout + Linear）。"""

    def __new__(cls, base_model_dir: Path, num_classes: int):
        import torch.nn as nn
        from transformers import AutoModel

        class _Model(nn.Module):
            def __init__(self):
                super().__init__()
                self.encoder = AutoModel.from_pretrained(
                    str(base_model_dir), local_files_only=True
                )
                self.dropout = nn.Dropout(0.1)
                self.classifier = nn.Linear(
                    self.encoder.config.hidden_size, num_classes
                )

            def forward(self, input_ids, attention_mask, **kwargs):
                out = self.encoder(
                    input_ids=input_ids, attention_mask=attention_mask
                )
                return self.classifier(self.dropout(out.last_hidden_state[:, 0]))

        return _Model()


class LocalAIEngine(ILocalAIEngine):
    """四核本地 AI 统一推理引擎（延迟加载 + 规则兜底）。"""

    #: 模型名 -> (类别数, 模型目录名, tokenizer 子目录名, 权重文件名)
    _MODEL_SPECS: dict[str, tuple[int, str, str, str]] = {
        "type":       (4,  "type_model",             "type_tokenizer",       "type_model.pt"),
        "section":    (13, "section_model",          "section_tokenizer",    "section_model.pt"),
        "subtopic":   (81, "subtopic_model",         "subtopic_tokenizer",   "subtopic_model.pt"),
        "difficulty": (3,  "difficulty_train_model", "difficulty_tokenizer", "difficulty_model.pt"),
    }

    def __init__(self, models_root: str | Path):
        self.models_root = Path(models_root)
        self.base_model_dir = self.models_root / "base_model"
        self.device = "cpu"
        self._loaded: dict[str, bool] = {name: False for name in self._MODEL_SPECS}
        self.models: dict[str, Any] = {}
        self.tokenizers: dict[str, Any] = {}
        self._warm_up_done = False
        self.on_status_change = None

        self._root = Path(__file__).resolve().parents[3]
        self._id2section: dict[int, str] | None = None
        self._subtopic_label2id: dict[str, int] | None = None
        self._section_tree: dict[str, list[str]] | None = None

    # ----- 模型加载 -----

    def _load_model(self, name: str) -> None:
        if self._loaded.get(name):
            return
        try:
            import torch
            from transformers import AutoTokenizer
        except Exception as exc:
            print(f"[LocalAIEngine] {name} 导入 torch/transformers 失败: {exc}")
            return

        num_classes, dir_name, tok_subdir, weight_name = self._MODEL_SPECS[name]
        model_dir = self.models_root / dir_name
        pt_file = model_dir / weight_name
        if not pt_file.exists():
            candidates = list(model_dir.glob("*.pt"))
            if not candidates:
                print(f"[LocalAIEngine] 找不到 {name} 模型权重: {model_dir}")
                return
            pt_file = candidates[0]

        tok_dir = model_dir / tok_subdir
        try:
            self.tokenizers[name] = AutoTokenizer.from_pretrained(
                str(tok_dir), local_files_only=True
            )
            model = BaseClassifierModel(self.base_model_dir, num_classes)
            state = torch.load(pt_file, map_location=self.device)
            if isinstance(state, dict) and "model_state_dict" in state:
                state = state["model_state_dict"]
            model.load_state_dict(state)
            model.eval().to(self.device)
            self.models[name] = model
            self._loaded[name] = True
            print(f"[LocalAIEngine] {name} 模型加载完成")
        except Exception as exc:
            print(f"[LocalAIEngine] {name} 模型加载失败: {type(exc).__name__}: {exc}")

    def warm_up(self) -> None:
        def _warm():
            if self.on_status_change:
                self.on_status_change("AI: 正在后台加载模型...")
            print("[LocalAIEngine] 开始后台预热四大模型...")
            for name in ("type", "section", "subtopic", "difficulty"):
                self._load_model(name)
            self._warm_up_done = True
            if self.on_status_change:
                self.on_status_change("AI: 本地四核已就绪")
            print("[LocalAIEngine] 后台预热完毕！")

        threading.Thread(target=_warm, daemon=True).start()

    def is_ready(self) -> bool:
        return all(self._loaded.values())

    # ----- 单模型 top-1 推理 -----

    def _predict_top1(self, name: str, text: str) -> tuple[int, float] | None:
        """返回 (类别下标, 概率)；模型未加载或推理失败返回 None。"""
        import torch

        self._load_model(name)
        if not self._loaded.get(name):
            return None
        try:
            enc = self.tokenizers[name](
                text,
                truncation=True,
                max_length=512,
                return_tensors="pt",
                return_token_type_ids=False,
            ).to(self.device)
            with torch.no_grad():
                logits = self.models[name](**enc)
                probs = torch.softmax(logits, dim=-1)[0].cpu().numpy()
            idx = int(probs.argmax())
            return idx, float(probs[idx])
        except Exception as exc:
            print(f"[LocalAIEngine] {name} 推理失败: {type(exc).__name__}: {exc}")
            return None

    # ----- 规则兜底 -----

    @staticmethod
    def _answer_letters(answer: str) -> str:
        """从答案中提取字母序列（去标点/空白），用于判断单选还是多选。"""
        return re.sub(r"[^A-Za-z]", "", str(answer or "")).upper()

    @staticmethod
    def _has_real_options(options: str) -> bool:
        """判断 options 是否有真实内容（排除只有 A./B./C./D. 标记的空壳）。"""
        if not options or not options.strip():
            return False
        stripped = re.sub(
            r"[\(\（]?\b[A-Z]\s*[\.\、\．\:：\)）]\s*", "", options
        )
        return bool(stripped.strip())

    def _rule_type(self, stem: str, options: str, answer: str) -> str:
        """规则判题型：选项结构 + 答案形态。

        - 无选项或选项只有标记（A./B./C./D.）：填空（含下划线）或解答
        - 有真实选项 + 答案多个字母：多选
        - 有真实选项 + 答案单个字母：单选
        """
        if not self._has_real_options(options):
            return "fill" if ("____" in stem or "___" in stem) else "solution"
        letters = self._answer_letters(answer)
        if len(letters) >= 2:
            return "multiple"
        return "single"

    def _reconcile_type(
        self, model_type: str, stem: str, options: str, answer: str
    ) -> str:
        """模型与规则交叉校验题型。

        模型只判"选择题 vs 非选择题"大方向（需语义理解）；
        单选/多选/填空/解答的细分由规则依据选项结构与答案形态决定。
        """
        rule_type = self._rule_type(stem, options, answer)
        if not model_type:
            return rule_type
        # 模型判选择题，规则也判选择题 → 用规则细分 single/multiple
        if model_type in ("single", "multiple") and rule_type in ("single", "multiple"):
            return rule_type
        # 模型判非选择题，规则也判非选择题 → 用规则细分 fill/solution
        if model_type in ("fill", "solution") and rule_type in ("fill", "solution"):
            return rule_type
        # 模型与规则大方向矛盾：优先采用规则（选项结构是最硬的事实）
        return rule_type

    @staticmethod
    def _rule_section(text: str) -> str:
        best, best_hits = "", 0
        for section, keywords in _SECTION_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw in text)
            if hits > best_hits:
                best, best_hits = section, hits
        return best

    @staticmethod
    def _rule_difficulty(stem: str, options: str) -> str:
        """难度规则：只给出高置信结论；easy 与拿不准都返回空串交给模型复核。"""
        text = f"{stem} {options}".strip()
        has_logic = any(kw in text for kw in _HARD_LOGIC_KW)
        has_hard_op = any(kw in text for kw in _HARD_OPS_KW)
        is_multi_question = bool(re.search(r"[（(]\s*[1IⅡ]\s*[）)]", text))
        if (has_logic and has_hard_op) or (
            is_multi_question and has_hard_op and len(text) > 150
        ):
            return "hard"
        cond_count = len(re.findall(r"[，,；;]|若|且", text))
        if cond_count >= 3 or any(kw in text for kw in _MEDIUM_OPS_KW) or has_logic:
            return "medium"
        # 短题不等于简单：easy 必须模型复核
        return ""

    # ----- 主入口 -----

    def predict_all(self, stem: str, options: str = "", answer: str = "") -> dict:
        """一次性预测四个字段。

        - type：模型 top-1 >= 0.7 判"选择题 vs 非选择题"大方向，
          单选/多选/填空/解答由规则依据答案形态与选项结构决定
        - section：模型 top-1 >= 0.7 采用，否则关键词兜底
        - subtopic：依赖 section；在 section 域内 top-3
        - difficulty：规则明确 hard/medium 时直接采用；否则调模型复核
        """
        text = f"{stem} {options}".strip()

        # 1) 题型（模型只喂题干+选项，答案不参与推理，避免拼接干扰）
        model_type = ""
        pred = self._predict_top1("type", text)
        if pred and pred[1] >= CONFIDENCE_THRESHOLD:
            model_type = {0: "single", 1: "multiple", 2: "fill", 3: "solution"}.get(
                pred[0], ""
            )
        qtype = self._reconcile_type(model_type, stem, options, answer)

        # 2) 大类
        section = ""
        pred = self._predict_top1("section", text)
        if pred and pred[1] >= CONFIDENCE_THRESHOLD:
            section = self._section_label(pred[0])
        if not section:
            section = self._rule_section(text)

        # 3) 细分考点（依赖 section）
        knowledge_points = ""
        if section:
            knowledge_points = self._predict_subtopics(section, stem, options)

        # 4) 难度
        rule_difficulty = self._rule_difficulty(stem, options)
        if rule_difficulty in ("hard", "medium"):
            difficulty = rule_difficulty
        else:
            difficulty_map = {0: "easy", 1: "medium", 2: "hard"}
            pred = self._predict_top1("difficulty", text)
            if pred and pred[1] >= CONFIDENCE_THRESHOLD and pred[0] in difficulty_map:
                difficulty = difficulty_map[pred[0]]
            else:
                difficulty = rule_difficulty or "medium"

        return {
            "type": qtype,
            "section": section,
            "knowledge_points": knowledge_points,
            "difficulty": difficulty,
        }

    # ----- 映射文件 -----

    def _section_label(self, idx: int) -> str:
        if self._id2section is None:
            path = self._root / "label_map_section.json"
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    name2id = json.load(f)
                self._id2section = {v: k for k, v in name2id.items()}
            else:
                self._id2section = {}
        return self._id2section.get(idx, "")

    def _predict_subtopics(self, section: str, stem: str, options: str) -> str:
        """在指定大类内预测细分考点，返回顿号分隔的 top-3 字符串。"""
        import torch

        self._load_model("subtopic")
        if not self._loaded.get("subtopic"):
            return ""
        try:
            if self._subtopic_label2id is None:
                with open(self._root / "label_map_subtopic.json", "r", encoding="utf-8") as f:
                    self._subtopic_label2id = json.load(f)
            if self._section_tree is None:
                with open(self._root / "knowledge_sections.json", "r", encoding="utf-8") as f:
                    self._section_tree = json.load(f).get("数学", {})

            valid_kps = self._section_tree.get(section, [])
            if not valid_kps:
                return ""

            sub_text = f"【大类】{section} {stem} {options}".strip()
            enc = self.tokenizers["subtopic"](
                sub_text,
                truncation=True,
                max_length=512,
                return_tensors="pt",
                return_token_type_ids=False,
            ).to(self.device)
            with torch.no_grad():
                logits = self.models["subtopic"](**enc)
                probs = torch.sigmoid(logits)[0].cpu().numpy()

            label2id = self._subtopic_label2id
            candidates = [
                (float(probs[label2id[kp]]), kp)
                for kp in valid_kps
                if kp in label2id
            ]
            candidates.sort(reverse=True)
            if not candidates or candidates[0][0] < CONFIDENCE_THRESHOLD:
                return ""
            return "、".join(kp for prob, kp in candidates[:3] if prob >= 0.5)
        except Exception as exc:
            print(f"[LocalAIEngine] subtopic 推理失败: {type(exc).__name__}: {exc}")
            return ""