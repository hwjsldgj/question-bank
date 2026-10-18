
import json
import torch
import torch.nn as nn
from transformers import AutoTokenizer, AutoModel
from pathlib import Path

# ================= 一级大类分类器 =================
class SectionModel(nn.Module):
    def __init__(self, base_dir, num_classes):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(str(base_dir), local_files_only=True)
        self.classifier = nn.Linear(self.encoder.config.hidden_size, num_classes)
    def forward(self, input_ids, attention_mask, **kwargs):
        out = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        return self.classifier(out.last_hidden_state[:, 0])

class LocalSectionClassifier:
    def __init__(self, model_dir):
        model_dir = Path(model_dir)
        self.weight_path = model_dir / "section_model.pt"
        self.tok_dir = model_dir / "section_tokenizer"
        self.base_model_dir = Path(__file__).resolve().parents[3] / "models" / "base_model"
        self.label_map_path = Path(__file__).resolve().parents[3] / "label_map_section.json"
        self.device = "cpu"
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded: return
        self.tokenizer = AutoTokenizer.from_pretrained(str(self.tok_dir), local_files_only=True)
        with open(self.label_map_path, "r", encoding="utf-8") as f:
            self.id2label = {v: k for k, v in json.load(f).items()}
        self.model = SectionModel(self.base_model_dir, len(self.id2label))
        self.model.load_state_dict(torch.load(self.weight_path, map_location=self.device))
        self.model.eval().to(self.device)
        self._loaded = True

    def predict(self, stem: str, options: str = "", answer: str = "") -> str:
        self._ensure_loaded()
        text = f"{stem} {options} {answer}".strip()
        enc = self.tokenizer(text, truncation=True, max_length=512, return_tensors="pt", return_token_type_ids=False).to(self.device)
        with torch.no_grad():
            logits = self.model(**enc)
            pred = torch.argmax(logits, dim=-1).item()
        return self.id2label[pred]

# ================= 二级细分分类器 =================
class SubtopicModel(nn.Module):
    def __init__(self, base_dir, num_classes):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(str(base_dir), local_files_only=True)
        self.classifier = nn.Linear(self.encoder.config.hidden_size, num_classes)
    def forward(self, input_ids, attention_mask, **kwargs):
        out = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        return self.classifier(out.last_hidden_state[:, 0])

class LocalSubtopicClassifier:
    def __init__(self, model_dir):
        model_dir = Path(model_dir)
        self.weight_path = model_dir / "subtopic_model.pt"
        self.tok_dir = model_dir / "subtopic_tokenizer"
        self.base_model_dir = Path(__file__).resolve().parents[3] / "models" / "base_model"
        
        # 加载 label_map 和 大类映射树
        root_dir = Path(__file__).resolve().parents[3]
        with open(root_dir / "label_map_subtopic.json", "r", encoding="utf-8") as f:
            self.label2id = json.load(f)
        self.id2label = {v: k for k, v in self.label2id.items()}
        
        with open(root_dir / "knowledge_sections.json", "r", encoding="utf-8") as f:
            self.tree = json.load(f)["数学"]
            
        self.device = "cpu"
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded: return
        self.tokenizer = AutoTokenizer.from_pretrained(str(self.tok_dir), local_files_only=True)
        self.model = SubtopicModel(self.base_model_dir, len(self.label2id))
        self.model.load_state_dict(torch.load(self.weight_path, map_location=self.device))
        self.model.eval().to(self.device)
        self._loaded = True

    def predict(self, stem: str, section: str, options: str = "", answer: str = "") -> list[str]:
        self._ensure_loaded()
        # 拼上大类标签
        text = f"【大类】{section} {stem} {options} {answer}".strip()
        enc = self.tokenizer(text, truncation=True, max_length=512, return_tensors="pt", return_token_type_ids=False).to(self.device)
        with torch.no_grad():
            logits = self.model(**enc)
            probs = torch.sigmoid(logits)[0].cpu().numpy()
            
        # 遮蔽不属于当前大类的考点
        valid_kps = self.tree.get(section, [])
        candidates = []
        for kp in valid_kps:
            if kp in self.label2id:
                idx = self.label2id[kp]
                candidates.append((probs[idx], kp))
                
        # 按照概率降序，取前 3 个
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [c[1] for c in candidates[:3]]
