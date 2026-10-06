# patch7.py
# AI 辨识强制走远程 API；难度分析仍走本地优先
from pathlib import Path

ROOT = Path(__file__).resolve().parent
def read(p): return p.read_text(encoding="utf-8")
def write(p, s): p.write_text(s, encoding="utf-8")

# ========== 1. ai_client.py: complete 加 force_remote ==========
print("[1/2] ai_client.py 加 force_remote...")
AI = ROOT / "app" / "infrastructure" / "ai" / "ai_client.py"
s = read(AI)

old = '''    def complete(self, prompt: str, response_schema: dict | None = None) -> dict:
        # 若本地模型可用且是难度请求，走本地（save 时的 AI 分析也会走本地）
        if self._local_classifier is not None and self._is_difficulty_prompt(prompt):'''
new = '''    def complete(self, prompt: str, response_schema: dict | None = None,
                 force_remote: bool = False) -> dict:
        # AI 辨识等场景要求强制走远程（force_remote=True）时不拦截；
        # 否则本地模型可用且是难度请求时走本地。
        if (not force_remote
                and self._local_classifier is not None
                and self._is_difficulty_prompt(prompt)):'''
if old not in s:
    print("  X 找不到 complete 定义")
    idx = s.find("def complete")
    print(repr(s[idx:idx+500]))
    exit(1)
s = s.replace(old, new, 1)

# 加：force_remote=True 时若远程未配置，抛错
old2 = '''        config = self._provider()
        self._ensure_configured(config)'''
new2 = '''        config = self._provider()
        self._ensure_configured(config)'''
# 保持原样（_ensure_configured 已经在 force_remote 分支抛错）
write(AI, s)
print("  OK ai_client.py 已改")

# ========== 2. question_service.py: AI 辨识调用加 force_remote=True ==========
print("[2/2] question_service.py AI 辨识加 force_remote...")
QS = ROOT / "app" / "application" / "question_service.py"
s = read(QS)

old = "        data = self._ai_client.complete(prompt, recognize_schema(effective))"
new = "        data = self._ai_client.complete(prompt, recognize_schema(effective), force_remote=True)"
if old not in s:
    print("  X 找不到 AI 辨识调用")
    idx = s.find("recognize_schema(effective)")
    print(repr(s[idx-200:idx+200]))
    exit(1)
s = s.replace(old, new, 1)
write(QS, s)
print("  OK question_service.py 已改")

print("")
print("完成。跑 python main.py 测试")