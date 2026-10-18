"""数据质量 error 级问题修复脚本（可重放，先扫后改）。

用法：
    python scripts/fix_audit_errors.py            # dry-run，只报告
    python scripts/fix_audit_errors.py --apply    # 实际修改

处理范围（error 级）：
    1. EMPTY_ANSWER           解答题 / 填空题 answer 为空列表
    2. CHOICE_OPTIONS_TOO_FEW 选择题选项 < 2

处理策略：标记 quality_flag='low' 隔离（组卷时 PaperComposer 已过滤 low）。
不修改 answer / options / stem 等原始数据，保留可溯源。

幂等：已标记 low 的题会被跳过（WHERE quality_flag != 'low'）。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_DEFAULT = ROOT / "question_bank.db"


def find_errors(conn):
    """返回需要标记为 low 的题目列表 [(id, category, detail)]。"""
    result = []

    rows = conn.execute(
        "SELECT id, type, answer FROM questions "
        "WHERE answer IN ('', '[]') AND quality_flag != 'low'"
    ).fetchall()
    for row in rows:
        result.append((row[0], "EMPTY_ANSWER", "type=%s" % row[1]))

    rows = conn.execute(
        "SELECT id, type, options FROM questions "
        "WHERE type IN ('single', 'multiple') AND quality_flag != 'low'"
    ).fetchall()
    for row in rows:
        import json
        try:
            opts = json.loads(row[2] or "[]")
        except (ValueError, TypeError):
            opts = []
        if len(opts) < 2:
            result.append((
                row[0], "CHOICE_OPTIONS_TOO_FEW",
                "type=%s options=%d" % (row[1], len(opts)),
            ))

    return result


def apply_fix(conn, items):
    """批量标记 quality_flag='low'。"""
    if not items:
        return 0
    ids = [row[0] for row in items]
    placeholders = ", ".join("?" for _ in ids)
    with conn:
        cur = conn.execute(
            "UPDATE questions SET quality_flag = 'low', "
            "updated_at = datetime('now') "
            "WHERE id IN (%s) AND quality_flag != 'low'" % placeholders,
            ids,
        )
        return cur.rowcount


def verify(conn):
    """改后复查：error 级问题应为 0。"""
    remaining = find_errors(conn)
    return remaining


def main():
    parser = argparse.ArgumentParser(description="修复数据质量 error 级问题")
    parser.add_argument("--db", default=str(DB_DEFAULT))
    parser.add_argument("--apply", action="store_true", help="实际执行修改")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print("[失败] 数据库不存在：%s" % db_path, file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        print("=== 修复前扫描 ===")
        items = find_errors(conn)
        if not items:
            print("无需修复的 error 级问题")
            return 0

        print("需修复 %d 条：" % len(items))
        for qid, category, detail in items:
            print("  %-10s %-25s %s" % (qid, category, detail))

        if not args.apply:
            print()
            print("[dry-run] 未执行修改；加 --apply 实际执行")
            return 0

        print()
        print("=== 执行修复 ===")
        updated = apply_fix(conn, items)
        print("已标记 quality_flag='low'：%d 条" % updated)

        print()
        print("=== 修复后复查 ===")
        remaining = verify(conn)
        if not remaining:
            print("error 级问题：0（全部修复）")
            return 0
        else:
            print("剩余 %d 条：" % len(remaining))
            for qid, category, detail in remaining:
                print("  %-10s %-25s %s" % (qid, category, detail))
            return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())