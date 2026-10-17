"""从题目 id 解析卷源，写入 questions.paper_source 列（幂等）。

id 格式：<卷源>_<q|fig><数字>，如 2016_上海卷文科_q00001
卷源 = 去掉 _qNNNNN / _figNNNNN 后缀的部分。

用法：python scripts/migrate_add_paper_source.py
"""
import re
import shutil
import sqlite3
import time
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "question_bank.db"
PATTERN = re.compile(r"^(.*)_(q|fig)\d+$")


def main() -> None:
    if not DB.exists():
        print(f"数据库不存在：{DB}")
        return

    ts = time.strftime("%Y%m%d_%H%M%S")
    backup = DB.with_name(f"question_bank_backup_{ts}.db")
    shutil.copy2(DB, backup)
    print(f"[1/4] 已备份: {backup.name}")

    con = sqlite3.connect(DB)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(questions)")]
        if "paper_source" not in cols:
            con.execute("ALTER TABLE questions ADD COLUMN paper_source TEXT")
            con.commit()
            print("[2/4] 已加列 paper_source")
        else:
            print("[2/4] 列 paper_source 已存在")

        rows = con.execute("SELECT id, paper_source FROM questions").fetchall()
        print(f"[3/4] 扫描 {len(rows)} 条")

        todo = []
        unmatched = []
        for qid, existing in rows:
            if existing:
                continue
            m = PATTERN.match(qid)
            if not m:
                unmatched.append(qid)
                continue
            todo.append((m.group(1), qid))

        if unmatched:
            print(f"  警告：{len(unmatched)} 条 id 无法解析：")
            for qid in unmatched[:10]:
                print(f"    {qid}")

        if todo:
            con.executemany(
                "UPDATE questions SET paper_source = ? WHERE id = ?", todo
            )
            con.commit()
            print(f"  已更新 {len(todo)} 条")
        else:
            print("  无需更新")

        empty = con.execute(
            "SELECT COUNT(*) FROM questions "
            "WHERE paper_source IS NULL OR paper_source = ''"
        ).fetchone()[0]
        print(f"[4/4] 验证：空 paper_source = {empty}")

        sources = con.execute(
            "SELECT paper_source, COUNT(*) FROM questions "
            "WHERE paper_source IS NOT NULL AND paper_source != '' "
            "GROUP BY paper_source ORDER BY paper_source"
        ).fetchall()
        print(f"  共 {len(sources)} 个卷源")
        for src, cnt in sources[:8]:
            print(f"    {src}: {cnt}")
        if len(sources) > 8:
            print(f"    ... 还有 {len(sources) - 8} 个")
    finally:
        con.close()


if __name__ == "__main__":
    main()
