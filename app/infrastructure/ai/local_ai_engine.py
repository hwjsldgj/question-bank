from app.interfaces.local_ai import ILocalAIEngine

from pathlib import Path
import re
import json

class BaseClassifierModel:
    # 删除了继承 nn.Module，改为在内部动态构建
    def __new__(cls, base_model_dir, num_classes):
        import torch.nn as nn
        from transformers import AutoModel
        
        class _Model(nn.Module):
            def __init__(self):
                super().__init__()
                self.encoder = AutoModel.from_pretrained(str(base_model_dir), local_files_only=True)
                self.dropout = nn.Dropout(0.1)
                self.classifier = nn.Linear(self.encoder.config.hidden_size, num_classes)
            def forward(self, input_ids, attention_mask, **kwargs):
                out = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
                return self.classifier(self.dropout(out.last_hidden_state[:, 0]))
        return _Model()

class LocalAIEngine(ILocalAIEngine):
    """四核本地 AI 统一推理引擎（延迟加载）。"""
    def __init__(self, models_root):
        # 防御性转换：无论传 str 还是 Path 都能处理
        self.models_root = Path(models_root)
        self.base_model_dir = self.models_root / "base_model"
        self.device = "cpu"
        self._loaded = {
            "type": False, "section": False, "subtopic": False, "difficulty": False
        }
        
        self.paths = {
            "type": self.models_root / "type_model",
            "section": self.models_root / "section_model",
            "subtopic": self.models_root / "subtopic_model",
            "difficulty": self.models_root / "difficulty_train_model"
        }
        
        self.models = {}
        self.tokenizers = {}
        self._warm_up_done = False
        self.on_status_change = None

    def _load_model(self, name: str, num_classes: int):
        if self._loaded[name]: return
        
        # 🚀 核心黑科技：在真正用到时，才导入这几百兆的重型库
        import torch
        import torch.nn as nn
        from transformers import AutoTokenizer, AutoModel
        
        path = self.paths[name]
        
        pt_file = None
        if name == "difficulty":
            pt_file = path / "difficulty_model.pt"
        elif name == "type":
            pt_file = path / "type_model.pt"
        elif name == "section":
            pt_file = path / "section_model.pt"
        elif name == "subtopic":
            pt_file = path / "subtopic_model.pt"

        if not pt_file or not pt_file.exists():
            pt_files = list(path.glob("*.pt"))
            if pt_files:
                pt_file = pt_files[0]
            else:
                print(f"[LocalAIEngine] 找不到 {name} 的模型权重: {path}")
                return

        tok_dir = path / f"{name}_tokenizer"
        if name == "difficulty":
            tok_dir = path / "difficulty_tokenizer"

        try:
            self.tokenizers[name] = AutoTokenizer.from_pretrained(str(tok_dir), local_files_only=True)
            model = BaseClassifierModel(self.base_model_dir, num_classes)
            model.load_state_dict(torch.load(pt_file, map_location=self.device))
            model.eval().to(self.device)
            self.models[name] = model
            self._loaded[name] = True
        except Exception as e:
            print(f"[LocalAIEngine] 模型 {name} 加载失败: {e}")


    def warm_up(self):
        """后台预热加载所有模型（供启动时调用）。"""
        import threading
        def _warm():
            if self.on_status_change: self.on_status_change("AI: 正在后台加载模型...")
            print("[LocalAIEngine] 开始后台预热四大模型...")
            self._load_model("type", 4)
            self._load_model("section", 13)
            self._load_model("subtopic", 81)
            self._load_model("difficulty", 3)
            self._warm_up_done = True
            self._warm_up_done = True
            if self.on_status_change: self.on_status_change("AI: 本地四核已就绪")
            print("[LocalAIEngine] 后台预热完毕！")
        
        threading.Thread(target=_warm, daemon=True).start()

    def is_ready(self) -> bool:
        """检查四个模型是否都已成功加载。"""
        return all(self._loaded.values())

    def predict_all(self, stem: str, options: str = "", answer: str = "") -> dict:

        text = f"{stem} {options}".strip()
        results = {"type": "single", "section": "", "knowledge_points": "", "difficulty": "medium"}
        
        # 1. 题型（模型置信度 > 0.8 采用，否则规则兜底）
        try:
            self._load_model("type", 4)
            if self._loaded["type"]:
                enc = self.tokenizers["type"](text, truncation=True, max_length=512, return_tensors="pt", return_token_type_ids=False).to(self.device)
                with torch.no_grad():
                    logits = self.models["type"](**enc)
                    probs = torch.softmax(logits, dim=-1)[0].cpu().numpy()
                    idx = int(probs.argmax())
                    max_prob = float(probs[idx])
                    
                    type_map = {0: "single", 1: "multiple", 2: "fill", 3: "solution"}
                    if max_prob >= 0.8:
                        results["type"] = type_map.get(idx, "single")
                    else:
                        raise ValueError(f"置信度不足 ({max_prob:.2f})")
            else:
                raise ValueError("模型未加载")
        except Exception as e:
            # print(f"[LocalAIEngine] 题型降级为规则: {e}")
            clean_opt = re.sub(r'[A-Z][\.\、]?\s*', '', options).strip()
            if not clean_opt:
                results["type"] = "fill" if ("____" in stem or "___" in stem) else "solution"
            else:
                if answer and ("," in str(answer) or "、" in str(answer)):
                    results["type"] = "multiple"
                else:
                    results["type"] = "single"

        # 2. 大类（模型置信度 > 0.8 采用）
        try:
            self._load_model("section", 13)
            if self._loaded["section"]:
                enc = self.tokenizers["section"](text, truncation=True, max_length=512, return_tensors="pt", return_token_type_ids=False).to(self.device)
                with torch.no_grad():
                    logits = self.models["section"](**enc)
                    probs = torch.softmax(logits, dim=-1)[0].cpu().numpy()
                    idx = int(probs.argmax())
                    max_prob = float(probs[idx])
                    
                    if max_prob >= 0.8:
                        root = Path(__file__).resolve().parents[3]
                        label_map_path = root / "label_map_section.json"
                        if label_map_path.exists():
                            with open(label_map_path, "r", encoding="utf-8") as f:
                                id2label = {v: k for k, v in json.load(f).items()}
                                results["section"] = id2label.get(idx, "")
        except Exception as e:
            pass

        # 3. 细分考点
        if results["section"]:
            try:
                self._load_model("subtopic", 81)
                if self._loaded["subtopic"]:
                    sub_text = f"【大类】{results['section']} {stem} {options}".strip()
                    enc = self.tokenizers["subtopic"](sub_text, truncation=True, max_length=512, return_tensors="pt", return_token_type_ids=False).to(self.device)
                    with torch.no_grad():
                        logits = self.models["subtopic"](**enc)
                        probs = torch.sigmoid(logits)[0].cpu().numpy()
                    
                    root = Path(__file__).resolve().parents[3]
                    with open(root / "knowledge_sections.json", "r", encoding="utf-8") as f:
                        tree = json.load(f)["数学"]
                    with open(root / "label_map_subtopic.json", "r", encoding="utf-8") as f:
                        label2id = json.load(f)
                        
                    valid_kps = tree.get(results["section"], [])
                    candidates = [(probs[label2id[kp]], kp) for kp in valid_kps if kp in label2id]
                    # 过滤置信度 > 0.5 的，并取前 3 个
                    high_conf = [c for c in candidates if c[0] > 0.5]
                    high_conf.sort(key=lambda x: x[0], reverse=True)
                    if high_conf:
                        results["knowledge_points"] = "、".join([c[1] for c in high_conf[:3]])
            except Exception as e:
                print(f"[LocalAIEngine] 考点预测失败: {e}")

        # 4. 难度（规则 + 模型兜底）
        try:
            hard_logic = ["恒成立", "任意", "存在", "唯一", "至少", "至多", "恰有"]
            hard_ops = ["证明", "极值", "零点个数", "取值范围", "轨迹方程", "抛物线", "双曲线", "椭圆", "导数"]
            is_multi_question = bool(re.search(r'[（(]\s*[1IⅡ]\s*[）)]', text))
            has_hard_logic = any(kw in text for kw in hard_logic)
            has_hard_ops = any(kw in text for kw in hard_ops)
            
            if (has_hard_logic and has_hard_ops) or (is_multi_question and has_hard_ops and len(text) > 150):
                results["difficulty"] = "hard"
            else:
                cond_count = len(re.findall(r'[，,；;]|若|且', text))
                medium_ops = ["等比", "等差", "三角函数", "单调性", "离心率", "距离", "向量"]
                if cond_count >= 3 or any(kw in text for kw in medium_ops) or has_hard_logic:
                    results["difficulty"] = "medium"
                elif len(text) < 80 and cond_count <= 2:
                    results["difficulty"] = "easy"
                else:
                    self._load_model("difficulty", 3)
                    if self._loaded["difficulty"]:
                        enc = self.tokenizers["difficulty"](text, truncation=True, max_length=512, return_tensors="pt", return_token_type_ids=False).to(self.device)
                        with torch.no_grad():
                            logits = self.models["difficulty"](**enc)
                            probs = torch.softmax(logits, dim=-1)[0].cpu().numpy()
                            pred_idx = int(probs.argmax())
                            max_prob = float(probs[pred_idx])
                            
                        if max_prob > 0.8:
                            results["difficulty"] = {0: "easy", 1: "medium", 2: "hard"}[pred_idx]
        except Exception as e:
            print(f"[LocalAIEngine] 难度预测失败: {e}")

        return results
