import sys
import pytest
from unittest.mock import patch, MagicMock

# =========================================================
# 🚀 极速黑科技：完美劫持 torch 导入，防止加载大库卡顿
# =========================================================
if "torch" not in sys.modules:
    mock_torch = MagicMock()
    mock_torch.cuda.is_available.return_value = False
    
    sys.modules["torch"] = mock_torch
    sys.modules["torch.nn"] = mock_torch
    sys.modules["torch.nn.functional"] = mock_torch
    sys.modules["torch.optim"] = mock_torch
    sys.modules["torch.utils"] = mock_torch
    sys.modules["torch.utils.data"] = mock_torch
    sys.modules["transformers"] = mock_torch

# =========================================================
# 本地模型打桩（现在只 Mock 统一引擎，防止加载实体）
# =========================================================
@pytest.fixture(autouse=True)
def mock_local_ai_engine():
    with patch("app.infrastructure.ai.local_ai_engine.LocalAIEngine._load_model") as mock_load:
        yield
