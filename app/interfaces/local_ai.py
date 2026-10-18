"""本地 AI 引擎端口（接口）。"""
from abc import ABC, abstractmethod

class ILocalAIEngine(ABC):
    """本地四核 AI 推理引擎抽象接口。"""

    @abstractmethod
    def warm_up(self) -> None:
        """后台预热加载所有模型。"""
        pass

    @abstractmethod
    def predict_all(self, stem: str, options: str = "", answer: str = "") -> dict:
        """一次性预测题型、大类、细分考点、难度。"""
        pass
