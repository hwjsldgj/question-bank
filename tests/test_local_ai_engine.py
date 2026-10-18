import pytest
from unittest.mock import patch
from app.infrastructure.ai.local_ai_engine import LocalAIEngine

def test_local_ai_engine_init():
    """测试统一引擎能否正常实例化。"""
    engine = LocalAIEngine("fake/path")
    assert engine is not None
    assert engine._warm_up_done == False

@patch("app.infrastructure.ai.local_ai_engine.LocalAIEngine._load_model")
def test_predict_all_type_rules(mock_load):
    """测试在没有实际加载模型（或模型加载失败）时，题型规则是否绝对正确。"""
    engine = LocalAIEngine("fake/path")
    
    # 场景1：带真实选项的单选题
    res1 = engine.predict_all("已知集合A={1,2}，求A", "A. 1 B. 2", "")
    assert res1["type"] == "single"

    # 场景2：无选项，有横线 -> 填空
    res2 = engine.predict_all("已知复数z=1+i，则|z| = ___。", "", "")
    assert res2["type"] == "fill"

    # 场景3：无选项，无横线 -> 解答
    res3 = engine.predict_all("已知函数 f(x)=ln x，求导。", "", "")
    assert res3["type"] == "solution"
    
    # 场景4：选项只有空壳（A. B. C. D.），无实际内容 -> 解答
    res4 = engine.predict_all("已知函数 f(x)=x^2，求最值。", "A. B. C. D.", "")
    assert res4["type"] == "solution"
