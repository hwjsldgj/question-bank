"""修复历史数据问题：单选误标 + 残缺题标记。

处理清单（已人工分类确认）：
1. 单选→填空 24 道（选项=0，答案是短表达式）
2. 单选→解答 2 道（选项=0，答案含推导/多问）
3. 标 quality_flag=low 30 道（选项丢失 14 + 空答案 16）

幂等：已处理过的题会跳过（type 已是目标值 / quality_flag 已是 low）。
用法：python scripts/fix_bad_questions.py
"""
import shutil
import sqlite3
import time
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "question_bank.db"

# 单选 → 填空（选项=0，短答案）
TO_FILL = [
    "A000136", "A000140", "A000250", "A000316", "A000320",
    "A000487", "A000573", "A000574", "A000647", "A000814", "A000826",
    "A000003", "A000238", "A000486", "A000488", "A000567",
    "A000568", "A000569", "A000646", "A000720", "A000772",
    "A000773", "A000777", "A000818",
]

# 单选 → 解答（选项=0，有解析/多问）
TO_SOLUTION = [
    "A000251", "A000643",
]

# 标 quality_flag=low：选项丢失 14 道
LOW_OPTIONS = [
    "A000044", "A000107", "A000137", "A000220", "A000231",
    "A000255", "A000469", "A000474", "A000477", "A000510",
    "A000602", "A000703", "A000759", "B000104",
]

# 标 quality_flag=low：空答案 16 道
LOW_EMPTY = [
    "G000020", "G000097", "A000135", "J000034", "J000042",
    "G000330", "G000460", "J000127", "J000138", "G000617",
    "G000643", "G000668", "G000694", "G000718", "G000734",
    "A000778",
]


def main() -> None:
    if not DB.exists():
        print("数据库不存在")
        return

    ts = time.strftime("%Y%m%d_%H%M%S")
    backup = DB.with_name(f"question_bank_backup_fix_{ts}.db")
    shutil.copy2(DB, backup)
    print(f"[1/5] 已备份: {backup.name}")

    con = sqlite3.connect(DB)
    try:
        # ---- 统计修复前 ----
        before = {}
        for r in con.execute("SELECT type, COUNT(*) FROM questions GROUP BY type"):
            before[r[0]] = r[1]
        print(f"[2/5] 修复前: {before}")

        # ---- 改 type ----
        changed_fill = 0
        for qid in TO_FILL:
            cur = con.execute("SELECT type FROM questions WHERE id=?", (qid,)).fetchone()
            if cur and cur[0] != "fill":
                con.execute(
                    "UPDATE questions SET type='fill', updated_at=datetime('now','localtime') WHERE id=?",
                    (qid,),
                )
                changed_fill += 1
        changed_sol = 0
        for qid in TO_SOLUTION:
            cur = con.execute("SELECT type FROM questions WHERE id=?", (qid,)).fetchone()
            if cur and cur[0] != "solution":
                con.execute(
                    "UPDATE questions SET type='solution', updated_at=datetime('now','localtime') WHERE id=?",
                    (qid,),
                )
                changed_sol += 1
        print(f"[3/5] 改题型: fill +{changed_fill}, solution +{changed_sol}")

        # ---- 标 low ----
        changed_low = 0
        for qid in LOW_OPTIONS + LOW_EMPTY:
            cur = con.execute("SELECT quality_flag FROM questions WHERE id=?", (qid,)).fetchone()
            if cur and cur[0] != "low":
                con.execute(
                    "UPDATE questions SET quality_flag='low', updated_at=datetime('now','localtime') WHERE id=?",
                    (qid,),
                )
                changed_low += 1
        print(f"      标 low: {changed_low} 道")

        con.commit()

        # ---- 校验 ----
        print("[4/5] 校验...")
        after = {}
        for r in con.execute("SELECT type, COUNT(*) FROM questions GROUP BY type"):
            after[r[0]] = r[1]
        print(f"      修复后: {after}")

        total = sum(after.values())
        print(f"      总数: {total}（应 2361）")

        # 残留检查：单选选项仍<4 且非 low
        bad = con.execute("""
            SELECT COUNT(*) FROM questions
            WHERE type='single'
              AND quality_flag != 'low'
              AND (options IS NULL OR options IN ('', '[]') OR json_array_length(options) < 4)
        """).fetchone()[0]
        print(f"      残留异常单选（选项<4 且非 low）: {bad}（应 0）")

        # low 总数
        low_total = con.execute("SELECT COUNT(*) FROM questions WHERE quality_flag='low'").fetchone()[0]
        print(f"      low 总数: {low_total}（应 30）")

        # ---- 抽样 ----
        print("\n[5/5] 修复后抽样（前 6 道改题型的）---")
        for qid in (TO_FILL + TO_SOLUTION)[:6]:
            r = con.execute(
                "SELECT id, type, quality_flag, legacy_id FROM questions WHERE id=?", (qid,)
            ).fetchone()
            print(f"  {r[0]}  type={r[1]:8s}  flag={r[2]:6s}  {r[3]}")

    finally:
        con.close()


if __name__ == "__main__":
    main()
