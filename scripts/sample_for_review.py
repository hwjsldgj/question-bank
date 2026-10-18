"""抽取 N 道题供人工检验 AI 打标质量（只读）。

用法：
    python scripts/sample_for_review.py
    python scripts/sample_for_review.py --count 20 --seed 42
    python scripts/sample_for_review.py --db other.db --out-dir report

抽样策略：按 (题型, 难度) 分层，每格至少 1 题，剩余按全库随机补齐，
保证单一题型/难度不会占满样本。已隔离的 low 题不参与抽样。

输出：
    - 控制台精简表：ID / 题型 / 难度 / 大类 / 细分考点 / 题干前 40 字
    - <out-dir>/review_sample_YYYYMMDD_HHMMSS.md：逐题完整内容 +
      人工判定列（✓/✗ + 修正值）
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DIFFICULTY_LABELS = {"easy": "易", "medium": "中", "hard": "难", "pending": "待确认"}
TYPE_LABELS = {"single": "单选", "multiple": "多选", "fill": "填空", "solution": "解答"}


def load_rows(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = list(conn.execute(
            "SELECT * FROM questions WHERE quality_flag != 'low'"
        ))
    finally:
        conn.close()
    return rows


def stratified_sample(rows, count, rng):
    """按 (type, difficulty) 分层，每格至少 1 题，剩余随机补齐。"""
    groups = defaultdict(list)
    for row in rows:
        groups[(row["type"], row["difficulty"])].append(row)

    selected = []
    used_ids = set()
    for key in sorted(groups.keys()):
        items = groups[key]
        if items:
            pick = rng.choice(items)
            selected.append(pick)
            used_ids.add(pick["id"])

    remaining = count - len(selected)
    if remaining > 0:
        pool = [r for r in rows if r["id"] not in used_ids]
        rng.shuffle(pool)
        selected.extend(pool[:remaining])

    return selected[:count]


def parse_options(raw):
    try:
        parsed = json.loads(raw or "[]")
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def parse_list(raw):
    text = (raw or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except (ValueError, TypeError):
            pass
    return [p.strip() for p in text.split("、") if p.strip()]


def render_markdown(rows, seed):
    lines = [
        "# 人工检验样本",
        "",
        "> 生成时间：%s ｜ 随机种子：%s ｜ 共 %d 题" % (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"), seed, len(rows)
        ),
        "",
        "检验方法：逐题对照「AI 打标」与「人工判定」，在人工列打 ✓ 或 ✗，",
        "并填写修正值。题目按 (题型, 难度) 分层抽样。",
        "",
        "---",
        "",
    ]

    for idx, row in enumerate(rows, 1):
        options = parse_options(row["options"])
        answer = parse_list(row["answer"])
        kps = parse_list(row["knowledge_points"])

        lines.append("## %d. %s" % (idx, row["id"]))
        lines.append("")
        lines.append("| 字段 | AI 打标 | 人工判定 |")
        lines.append("|---|---|---|")
        lines.append("| 卷源 | %s | |" % (row["paper_source"] or "—"))
        lines.append("| 题型 | %s (%s) | |" % (
            TYPE_LABELS.get(row["type"], row["type"]), row["type"]
        ))
        lines.append("| 难度 | %s (%s) | |" % (
            DIFFICULTY_LABELS.get(row["difficulty"], row["difficulty"]), row["difficulty"]
        ))
        lines.append("| 大类 | %s | |" % (row["section"] or "—"))
        lines.append("| 细分考点 | %s | |" % ("、".join(kps) or "—"))
        lines.append("")
        lines.append("**题干**")
        lines.append("")
        lines.append("```")
        lines.append(row["stem"] or "")
        lines.append("```")
        lines.append("")

        if options:
            lines.append("**选项**")
            lines.append("")
            for opt in options:
                key = opt.get("key", "") if isinstance(opt, dict) else ""
                text = opt.get("text", "") if isinstance(opt, dict) else str(opt)
                lines.append("- %s. %s" % (key, text))
            lines.append("")

        lines.append("**答案**：%s" % ("、".join(answer) or "—"))
        lines.append("")
        solution = (row["solution"] or "").strip()
        if solution:
            lines.append("**解析**")
            lines.append("")
            lines.append("```")
            lines.append(solution[:500] + ("…" if len(solution) > 500 else ""))
            lines.append("```")
            lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def render_console(rows):
    print()
    print("=" * 110)
    print("%-10s %-6s %-6s %-22s %-30s %s" % (
        "ID", "题型", "难度", "大类", "细分考点", "题干(前40字)"
    ))
    print("=" * 110)
    for row in rows:
        kps = parse_list(row["knowledge_points"])
        stem = (row["stem"] or "").replace("\n", " ")[:40]
        print("%-10s %-6s %-6s %-22s %-30s %s" % (
            row["id"],
            TYPE_LABELS.get(row["type"], row["type"]),
            DIFFICULTY_LABELS.get(row["difficulty"], row["difficulty"]),
            (row["section"] or "—")[:20],
            ("、".join(kps))[:28],
            stem,
        ))
    print("=" * 110)


def main():
    parser = argparse.ArgumentParser(description="抽取 N 道题供人工检验")
    parser.add_argument("--db", default=str(ROOT / "question_bank.db"))
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--out-dir", default=str(ROOT / "report"))
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print("[失败] 数据库不存在：%s" % db_path, file=sys.stderr)
        return 2

    seed = args.seed if args.seed is not None else random.randint(0, 999999)
    rng = random.Random(seed)

    rows = load_rows(db_path)
    if not rows:
        print("[失败] 题库为空", file=sys.stderr)
        return 1

    selected = stratified_sample(rows, args.count, rng)
    render_console(selected)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = out_dir / ("review_sample_%s.md" % stamp)
    md_path.write_text(render_markdown(selected, seed), encoding="utf-8")

    print()
    print("详细检验表：%s" % md_path)
    print("随机种子：%d（加 --seed %d 可复现同一样本）" % (seed, seed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())