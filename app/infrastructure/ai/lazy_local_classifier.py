"""LazyLocalClassifier：延迟加载的本地难度分类器代理。

目的：避免在容器装配时 import torch/transformers（约 8~10 秒），
让主窗口能立即显示；真正用到时（首次 predict 或预热）才加载。
"""

from pathlib import Path


class LazyLocalClassifier:
    """延迟实例化本地难度分类器的代理。"""

    def __init__(self, model_dir) -> None:
        self._model_dir = Path(model_dir)
        self._instance = None
        self._failed = False

    def _get(self):
        if self._failed:
            return None
        if self._instance is None:
            try:
                from app.infrastructure.ai.local_difficulty_classifier import (
                    LocalDifficultyClassifier,
                )
                self._instance = LocalDifficultyClassifier(self._model_dir)
            except Exception as e:  # noqa: BLE001
                print(f"[lazy] 本地难度模型加载失败：{e}")
                self._failed = True
                return None
        return self._instance

    def is_available(self) -> bool:
        """模型文件是否存在（不触发 import）。"""
        weight = self._model_dir / "math_multitask_model.pt"
        tok = self._model_dir / "math_multitask_tokenizer"
        return weight.exists() and tok.exists()

    def ensure_loaded(self) -> None:
        """强制加载（供后台预热调用）。"""
        clf = self._get()
        if clf is not None:
            clf._ensure_loaded()

    def predict(self, stem: str, options: str = "", answer: str = "") -> str:
        clf = self._get()
        if clf is None:
            raise RuntimeError("本地难度模型不可用")
        return clf.predict(stem=stem, options=options, answer=answer)

    # 兼容性：某些代码通过属性访问 _ensure_loaded / _loaded
    def __getattr__(self, name):
        if name.startswith("_"):
            clf = self._get()
            if clf is not None:
                return getattr(clf, name)
        raise AttributeError(name)
