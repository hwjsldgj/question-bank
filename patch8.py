# patch8.py
# AI 辨识：如果只勾了"难度"，走本地模型；否则走远程
from pathlib import Path

QS = Path("app/application/question_service.py")
s = QS.read_text(encoding="utf-8")

old = """        if not include_solution:
            prompt += "\\n注意：本次不要输出解题解析，solution 请留空字符串。"
        data = self._ai_client.complete(prompt, recognize_schema(effective))
        report = self._normalize_recognition(data, effective, options, subjects)"""

new = """        if not include_solution:
            prompt += "\\n注意：本次不要输出解题解析，solution 请留空字符串。"

        # 用户需求：能走本地的就走本地。
        # AI 辨识是多字段一次调用，本地模型只做难度；因此仅当"只勾了难度"时走本地。
        local_clf = getattr(self._ai_client, "_local_classifier", None)
        if local_clf is not None and effective == [RecognizeModule.DIFFICULTY]:
            try:
                options_text = "；".join(f"{o.key}. {o.text}" for o in options) or "无"
                local_result = local_clf.predict(stem=stem, options=options_text, answer="")
                data = {"difficulty": local_result}
            except Exception as e:
                print(f"[本地辨识] 出错，降级走远程：{e}")
                data = self._ai_client.complete(prompt, recognize_schema(effective))
        else:
            data = self._ai_client.complete(prompt, recognize_schema(effective))

        report = self._normalize_recognition(data, effective, options, subjects)"""

if old not in s:
    print("X 找不到目标代码段")
    exit(1)

s = s.replace(old, new, 1)
QS.write_text(s, encoding="utf-8")
print("OK 已改")
print("")
print("效果：")
print("  AI 辨识只勾「难度」        -> 走本地（秒回）")
print("  AI 辨识勾了其他任意字段    -> 走远程 API")