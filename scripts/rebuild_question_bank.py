# rebuild_db.py
# 完整重建数据库：删除旧库 -> 用应用 schema 建表 -> 全量导入 2236 条（不去重）
import json
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

LABELED = r"E:\code\题目\output\labeled\labeled_all.jsonl"
TRAIN   = r"E:\code\题目\output\multilabel\train.jsonl"
TEST    = r"E:\code\题目\output\multilabel\test.jsonl"
DB      = "question_bank.db"

DIFF_MAP = {0: "easy", 1: "medium", 2: "hard"}

# 让 Python 能 import app
sys.path.insert(0, str(Path.cwd()))


def parse_options(s):
    if not s or not s.strip():
        return []
    opts = []
    for line in s.split("\n"):
        m = re.match(r"^([A-D])[.、．]\s*(.+)$", line.strip())
        if m:
            opts.append({"key": m.group(1), "text": m.group(2).strip()})
    return opts


def parse_answer(s):
    if not s or not s.strip():
        return []
    return [s.strip()]


def guess_type(stem, options_str, answer):
    opts = parse_options(options_str)
    if opts:
        ans = answer.strip()
        if len(ans) > 1 and all(c in "ABCD" for c in ans):
            return "multiple"
        return "single"
    if re.search(r"[（(]\s*1\s*[）)]", stem) and re.search(r"[（(]\s*2\s*[）)]", stem):
        return "solution"
    return "fill"


def main():
    # ========== 1. 备份并删除旧数据库 ==========
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if Path(DB).exists():
        backup = f"question_bank_backup_{ts}.db"
        shutil.copy(DB, backup)
        print(f"[1/5] 已备份: {backup}")
        Path(DB).unlink()
        print(f"      已删除旧库: {DB}")
    else:
        print(f"[1/5] 无旧库可删")

    # ========== 2. 用应用的 schema 重建空库 ==========
    print(f"[2/5] 重建表结构...")
    from app.infrastructure.database.connection import DatabaseConnection
    from app.infrastructure.database.schema import ensure_schema

    db_conn = DatabaseConnection(DB)
    conn = db_conn.connect()
    ensure_schema(conn)
    print(f"      表结构已创建")

    # ========== 3. 读难度 ==========
    print(f"[3/5] 读取难度映射...")
    difficulty_map = {}
    for f in [TRAIN, TEST]:
        if not Path(f).exists():
            continue
        with open(f, encoding="utf-8") as fp:
            for line in fp:
                o = json.loads(line)
                difficulty_map[o["id"]] = DIFF_MAP[o["difficulty"]]
    print(f"      共 {len(difficulty_map)} 条带难度")

    # ========== 4. 读题目 ==========
    print(f"[4/5] 读取题目数据...")
    questions = []
    with open(LABELED, encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            labels = o.get("labels") or []
            stem = (o.get("stem") or "").strip()
            options_str = o.get("options") or ""
            answer_str = o.get("answer") or ""

            questions.append({
                "id": o["id"],
                "subject": "数学",
                "section": labels[0] if labels else "",
                "knowledge_points": [],
                "type": guess_type(stem, options_str, answer_str),
                "stem": stem,
                "options": parse_options(options_str),
                "answer": parse_answer(answer_str),
                "solution": o.get("solution") or "",
                "difficulty": difficulty_map.get(o["id"], "pending"),
                "difficulty_source": "ai",
                "options_text": options_str,
                "answer_text": answer_str,
            })
    print(f"      共 {len(questions)} 条")

    # 缺难度用本地模型补
    missing = [q for q in questions if q["difficulty"] == "pending"]
    if missing:
        print(f"      缺失难度 {len(missing)} 条，用本地模型补...")
        try:
            from app.infrastructure.ai.local_difficulty_classifier import LocalDifficultyClassifier
            clf = LocalDifficultyClassifier("models/difficulty_model")
            t0 = time.time()
            for i, q in enumerate(missing):
                try:
                    q["difficulty"] = clf.predict(stem=q["stem"], options=q["options_text"], answer=q["answer_text"])
                except Exception:
                    pass
                if (i + 1) % 100 == 0:
                    print(f"        {i+1}/{len(missing)}  {time.time()-t0:.1f}s")
            print(f"      补完，用时 {time.time()-t0:.1f}s")
        except Exception as e:
            print(f"      本地模型失败：{e}")

    # ========== 5. 导入 ==========
    print(f"[5/5] 导入数据...")
    cur = conn.cursor()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    inserted = 0
    failed = 0

    for q in questions:
        try:
            cur.execute("""
                INSERT INTO questions
                (id, subject, section, knowledge_points, type, stem, options, answer, solution,
                 difficulty, difficulty_source, quality_flag, source, image_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                q["id"], q["subject"], q["section"],
                json.dumps(q["knowledge_points"], ensure_ascii=False),
                q["type"], q["stem"],
                json.dumps(q["options"], ensure_ascii=False),
                json.dumps(q["answer"], ensure_ascii=False),
                q["solution"],
                q["difficulty"], q["difficulty_source"], "normal", "bank",
                None, now, now,
            ))
            inserted += 1
        except Exception as e:
            failed += 1
            print(f"      插入失败 {q['id']}: {e}")

    conn.commit()

    # ========== 统计 ==========
    cur.execute("SELECT COUNT(*) FROM questions")
    total = cur.fetchone()[0]

    print()
    print("=" * 60)
    print(f"完成")
    print("=" * 60)
    print(f"  插入成功: {inserted}")
    print(f"  插入失败: {failed}")
    print(f"  数据库总数: {total}")

    print()
    print("板块分布：")
    cur.execute("SELECT section, COUNT(*) FROM questions GROUP BY section ORDER BY COUNT(*) DESC")
    for s, c in cur.fetchall():
        print(f"  {s or '(空)'}: {c}")

    print()
    print("难度分布：")
    cur.execute("SELECT difficulty, COUNT(*) FROM questions GROUP BY difficulty")
    for d, c in cur.fetchall():
        print(f"  {d}: {c}")

    print()
    print("题型分布：")
    cur.execute("SELECT type, COUNT(*) FROM questions GROUP BY type")
    for t, c in cur.fetchall():
        print(f"  {t}: {c}")

    conn.close()


if __name__ == "__main__":
    main()