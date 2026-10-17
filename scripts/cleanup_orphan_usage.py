"""清理 question_usage 中引用了不存在题目的孤儿行（历史误删残留）。"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "question_bank.db"

def main():
    con = sqlite3.connect(DB)
    try:
        orphans = con.execute("""
            SELECT u.question_id, u.use_count, u.last_used_at
            FROM question_usage u
            WHERE NOT EXISTS (SELECT 1 FROM questions q WHERE q.id = u.question_id)
        """).fetchall()
        if not orphans:
            print("无孤儿行，无需清理")
            return
        print(f"发现 {len(orphans)} 条孤儿行：")
        for r in orphans:
            print(f"  {r[0]}  use_count={r[1]}")
        con.execute("""
            DELETE FROM question_usage
            WHERE NOT EXISTS (SELECT 1 FROM questions q WHERE q.id = question_usage.question_id)
        """)
        con.commit()
        print(f"已删除 {len(orphans)} 条")
    finally:
        con.close()

if __name__ == "__main__":
    main()
