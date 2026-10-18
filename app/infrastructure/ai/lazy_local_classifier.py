
from pathlib import Path

class LazyLocalClassifier:
    """兼容旧 DifficultyService 的占位代理（真正推理已迁移至 LocalAIEngine）"""
    def __init__(self, model_dir) -> None:
        self._model_dir = Path(model_dir)
    
    def is_available(self) -> bool:
        return False 
        
    def predict(self, stem: str, options: str = "", answer: str = "") -> str:
        return "medium"
