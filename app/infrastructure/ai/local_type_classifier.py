"""本地题型分类器（单标签四分类）。"""
import torch
import torch.nn as nn
from transformers import AutoTokenizer, AutoModel
from pathlib import Path

def format_text(stem: str, options: str, answer: str) -> str:
    s = str(stem).replace("\n", " ").strip()
    o = str(options).replace("\n", " ").strip() if options else ""
    a = str(answer).replace("\n", " ").strip() if answer else ""
    return " ".join([p for p in [s, o, a] if p])

class TypeModel(nn.Module):
    def __init__(self, base_model_dir, num_classes=4):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(str(base_model_dir), local_files_only=True)
        self.dropout = nn.Dropout(0.1)
        self.classifier = nn.Linear(self.encoder.config.hidden_size, num_classes)
        
    # 👇 加上 **kwargs 吞掉多余的 token_type_ids
    def forward(self, input_ids, attention_mask, **kwargs):
        out = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        return self.classifier(self.dropout(out.last_hidden_state[:, 0]))

class LocalTypeClassifier:
    def __init__(self, model_dir):
        model_dir = Path(model_dir)
        self.weight_path = model_dir / "type_model.pt"
        self.tok_dir = model_dir / "type_tokenizer"
        self.base_model_dir = Path(__file__).resolve().parents[3] / "models" / "base_model"
        self.device = "cpu"
        self._loaded = False
        self.id2type = {0: "single", 1: "multiple", 2: "fill", 3: "solution"}

    def _ensure_loaded(self):
        if self._loaded:
            return
        self.tokenizer = AutoTokenizer.from_pretrained(str(self.tok_dir), local_files_only=True)
        self.model = TypeModel(self.base_model_dir, num_classes=4)
        self.model.load_state_dict(torch.load(self.weight_path, map_location=self.device))
        self.model.eval().to(self.device)
        self._loaded = True

    def predict(self, stem: str, options: str = "", answer: str = "") -> str:
        self._ensure_loaded()
        text = format_text(stem, options, answer)
        # 👇 同时加上 return_token_type_ids=False 双保险
        enc = self.tokenizer(text, truncation=True, max_length=512, return_tensors="pt", return_token_type_ids=False).to(self.device)
        with torch.no_grad():
            logits = self.model(**enc)
            pred = torch.argmax(logits, dim=-1).item()
        return self.id2type[pred]
