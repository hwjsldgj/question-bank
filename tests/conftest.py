import sys
import pytest
from unittest.mock import MagicMock

# =========================================================
# 🚀 极速黑科技：拦截超重型库的导入 (专治 Windows 加载 PyTorch 卡 20+ 秒)
# =========================================================
class FakeModule(MagicMock):
    pass

# 如果测试不需要真正跑神经网络，直接注入假库。
# 这绝不会影响任何业务逻辑与UI测试，纯为了让测试秒开。
if "torch" not in sys.modules:
    sys.modules["torch"] = FakeModule()
if "torch.nn" not in sys.modules:
    sys.modules["torch.nn"] = FakeModule()
if "transformers" not in sys.modules:
    sys.modules["transformers"] = FakeModule()

# 某些代码会调用 torch.cuda.is_available()
sys.modules["torch"].cuda.is_available.return_value = False

# =========================================================
# 本地模型打桩（业务层降级测试）
# =========================================================
@pytest.fixture(autouse=True)
def mock_local_knowledge_model(monkeypatch):
    """Mock 本地知识点模型，防止加载真实大模型并卡住测试。"""
    from app.infrastructure.ai.local_knowledge_classifier import LocalKnowledgeClassifier
    
    def fake_predict(self, stem, options="", answer=""):
        return "其他"
        
    monkeypatch.setattr(LocalKnowledgeClassifier, "predict", fake_predict)


# =========================================================
# ⏱️ 预计剩余时间 (ETA) 插件
# =========================================================
import time
import sys

_eta_start_time = 0.0
_eta_total = 0
_eta_completed = 0

def pytest_sessionstart(session):
    global _eta_start_time, _eta_total, _eta_completed
    _eta_start_time = time.time()
    _eta_total = session.testscollected
    _eta_completed = 0

def pytest_runtest_logreport(report):
    global _eta_completed
    # 只在 test 结束 (call) 或 setup 失败时计数
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        _eta_completed += 1
        
    if _eta_completed > 0 and _eta_completed < _eta_total:
        elapsed = time.time() - _eta_start_time
        avg_time = elapsed / _eta_completed
        remaining_tests = _eta_total - _eta_completed
        eta_seconds = int(avg_time * remaining_tests)
        
        # 用 \r 覆盖行首，不干扰 pytest-sugar 的输出
        sys.stdout.write(f"\r\033[K⏳ 预计剩余: {eta_seconds} 秒 | 进度: {_eta_completed}/{_eta_total}")
        sys.stdout.flush()
