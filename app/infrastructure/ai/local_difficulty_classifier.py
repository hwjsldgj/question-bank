"""本地难度分类器：加载训练好的 RoBERTa 模型判断题目难度。"""
from pathlib import Path

import torch
import torch.nn as nn
from transformers import AutoTokenizer, AutoModel

BASE_MODEL = "hfl/chinese-roberta-wwm-ext"
DIFFICULTY_MAP = {0: "easy", 1: "medium", 2: "hard"}


_BASE_MODEL_LOCAL = Path(__file__).resolve().parents[3] / "models" / "base_model"


class _MultiTaskModel(nn.Module):
    def __init__(self, base_name, num_k=16, num_d=3):
        super().__init__()
        if _BASE_MODEL_LOCAL.exists():
            self.encoder = AutoModel.from_pretrained(str(_BASE_MODEL_LOCAL), local_files_only=True)
        else:
            self.encoder = AutoModel.from_pretrained(base_name)
        hidden = self.encoder.config.hidden_size
        self.dropout = nn.Dropout(0.1)
        self.head_k = nn.Linear(hidden, num_k)
        self.head_d = nn.Linear(hidden, num_d)

    def forward(self, input_ids, attention_mask):
        out = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        cls = out.last_hidden_state[:, 0]
        return self.head_k(cls), self.head_d(cls)


class LocalDifficultyClassifier:
    """本地难度分类器：输入题干+选项+答案，输出 easy/medium/hard。"""

    def __init__(self, model_dir):
        model_dir = Path(model_dir)
        weight = model_dir / "math_multitask_model.pt"
        tok_dir = model_dir / "math_multitask_tokenizer"
        if not weight.exists() or not tok_dir.exists():
            raise FileNotFoundError(f"本地模型不存在：{model_dir}")

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self._weight_path = weight
        self._tok_dir = tok_dir
        self._loaded = False
        self.tokenizer = None
        self.model = None

    def _ensure_loaded(self):
        if self._loaded:
            return
        self.tokenizer = AutoTokenizer.from_pretrained(self._tok_dir)
        self.model = _MultiTaskModel(BASE_MODEL, num_k=16, num_d=3)
        self.model.load_state_dict(torch.load(self._weight_path, map_location=self.device))
        self.model.eval().to(self.device)
        self._loaded = True

    def predict(self, stem: str, options: str = "", answer: str = "") -> str:
        self._ensure_loaded()
        parts = []
        if stem:
            parts.append(f"题目：{stem}")
        if options:
            parts.append(f"选项：{options}")
        if answer:
            parts.append(f"答案：{answer}")
        text = "\n".join(parts)

        enc = self.tokenizer(
            text, return_tensors="pt", truncation=True,
            max_length=512, return_token_type_ids=False,
        ).to(self.device)
        with torch.no_grad():
            _, d_logits = self.model(**enc)
            probs = torch.softmax(d_logits, dim=-1)[0].cpu().numpy()

        if probs[2] >= 0.30:
            pred = 2
        elif probs[1] >= 0.40:
            pred = 1
        else:
            pred = int(probs.argmax())
        return DIFFICULTY_MAP[pred]

