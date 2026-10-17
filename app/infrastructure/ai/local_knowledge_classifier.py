"""本地知识点分类器：加载微调好的 RoBERTa 模型预测板块。"""
import json
import torch
import torch.nn as nn
from transformers import AutoTokenizer, AutoModel
from pathlib import Path

class KnowledgeClassifier(nn.Module):
    def __init__(self, base_model_dir, num_k=15):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(str(base_model_dir))
        hidden = self.encoder.config.hidden_size
        self.dropout = nn.Dropout(0.1)
        self.classifier = nn.Linear(hidden, num_k)

    # 👇 这里加上了 **kwargs，用来吞掉多余的 token_type_ids 等参数
    def forward(self, input_ids, attention_mask, **kwargs):
        out = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        cls = out.last_hidden_state[:, 0]
        return self.classifier(self.dropout(cls))

class LocalKnowledgeClassifier:
    """本地知识点分类器（CPU 极速推理）。"""
    def __init__(self, model_dir):
        model_dir = Path(model_dir)
        self.weight_path = model_dir / "knowledge_model.pt"
        self.tok_dir = model_dir / "knowledge_tokenizer"
        self.label_map_path = model_dir / "label_map.json"
        
        # 底座模型在项目根目录的 models/base_model
        self.base_model_dir = Path(__file__).resolve().parents[3] / "models" / "base_model"
        
        self.device = "cpu"
        self._loaded = False
        self.tokenizer = None
        self.model = None
        self.id2label = None

    def _ensure_loaded(self):
        if self._loaded:
            return
        with open(self.label_map_path, "r", encoding="utf-8") as f:
            label2id = json.load(f)
        self.id2label = {v: k for k, v in label2id.items()}
        
        self.tokenizer = AutoTokenizer.from_pretrained(str(self.tok_dir))
        
        self.model = KnowledgeClassifier(self.base_model_dir, num_k=len(label2id))
        self.model.load_state_dict(torch.load(self.weight_path, map_location=self.device))
        self.model.eval().to(self.device)
        self._loaded = True

    def predict(self, stem: str, options: str = "", answer: str = "") -> str:
        self._ensure_loaded()
        text = f"题目：{stem} 选项：{options} 答案：{answer}"
        
        enc = self.tokenizer(text, truncation=True, max_length=512, return_tensors="pt").to(self.device)
        with torch.no_grad():
            logits = self.model(**enc)
            probs = torch.sigmoid(logits)[0].cpu().numpy()
        
        preds = []
        for idx, p in enumerate(probs):
            if p > 0.45:
                label = self.id2label[idx]
                if label != "其他":
                    preds.append(label)
        
        if not preds:
            return "其他"
        return "、".join(preds)
