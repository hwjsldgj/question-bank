# -*- coding: utf-8 -*-
"""题库 LaTeX 公式规范化脚本（幂等、可重放）。

用法：
    python scripts/normalize_latex.py                # dry-run，只报告
    python scripts/normalize_latex.py --apply        # 实际修改（自动备份 db）
    python scripts/normalize_latex.py --pattern in   # 只修某类模式

修复项（只在 $...$ 块内生效）：
    1. 函数名补反斜杠：in / angle / Gamma / ln / cos / sin / tan /
       arcsin / arctan / sqrt / triangle（词边界精确匹配，不误伤 min/sinc）
    2. Unicode 符号转 LaTeX：≠ / ≤ / ≥ / ± / × / π
    3. degree -> ^\\circ
    4. 多数字下标 _NN -> _{NN}
    5. 数值单位 cm/dm/km/kg/mm -> \\,\\text{unit}

不处理（需人工核对）：
    - sqrt(...) 的括号分组形式（保留，MathJax 可渲染）
    - in/angle 之后可能还有 OCR 缺字符的情况（仅加反斜杠）

幂等：已规范化的文本不会再次被改动。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_DEFAULT = ROOT / "question_bank.db"

MATH_BLOCK = re.compile(r"\$\$[^$]+\$\$|\$[^$]+\$")

# 函数名列表（arcsin 在 sin 之前，避免部分匹配）
FUNCS = ["arcsin", "arctan", "sin", "cos", "tan", "ln",
         "angle", "triangle", "Gamma", "sqrt", "in"]

UNICODE_MAP = {
    "≠": r"\neq",
    "≤": r"\leq",
    "≥": r"\geq",
    "±": r"\pm",
    "×": r"\times",
    "π": r"\pi",
    "·": r"\cdot",
    "°": r"^\circ",
}

UNITS = ["cm", "dm", "km", "mm", "kg"]


def fix_math_block(block: str, patterns: set[str]) -> tuple[str, Counter]:
    """对单个 $...$ 块做替换，返回 (新文本, 命中计数)。"""
    hits = Counter()
    s = block

    if "func" in patterns:
        for fn in FUNCS:
            pat = r"(?<![a-zA-Z_\\])" + fn + r"(?![a-zA-Z])"
            new = re.sub(pat, lambda m, f=fn: "\\" + f, s)
            if new != s:
                hits["func:" + fn] += len(re.findall(pat, s))
                s = new

    if "unicode" in patterns:
        for ch, repl in UNICODE_MAP.items():
            if ch in s:
                hits["unicode:" + ch] += s.count(ch)
                s = s.replace(ch, repl)

    if "degree" in patterns:
        new = re.sub(r"(\d)\s*degree\b", r"\1^\\circ", s)
        if new != s:
            hits["degree"] += 1
            s = new

    if "sub" in patterns:
        new = re.sub(r"(?<!\\)_(\d{2,})(?![\d}])", r"_{\1}", s)
        if new != s:
            hits["sub"] += len(re.findall(r"(?<!\\)_(\d{2,})(?![\d}])", s))
            s = new

    if "unit" in patterns:
        for unit in UNITS:
            pat = r"(\d)\s*" + unit + r"\b"
            new = re.sub(pat, r"\1\,\\text{" + unit + "}", s)
            if new != s:
                hits["unit:" + unit] += len(re.findall(pat, s))
                s = new

    return s, hits


def fix_text(text: str, patterns: set[str]) -> tuple[str, Counter]:
    """对任意文本做块内替换。"""
    if not text:
        return text, Counter()
    total = Counter()
    out_parts = []
    last = 0
    for m in MATH_BLOCK.finditer(text):
        out_parts.append(text[last:m.start()])
        fixed, hits = fix_math_block(m.group(0), patterns)
        out_parts.append(fixed)
        total.update(hits)
        last = m.end()
    out_parts.append(text[last:])
    return "".join(out_parts), total


def fix_options(raw: str, patterns: set[str]) -> tuple[str, Counter]:
    total = Counter()
    try:
        data = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return raw, total
    if not isinstance(data, list):
        return raw, total
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            fixed, hits = fix_text(item["text"], patterns)
            item["text"] = fixed
            total.update(hits)
    return json.dumps(data, ensure_ascii=False), total


def fix_answer(raw: str, patterns: set[str]) -> tuple[str, Counter]:
    total = Counter()
    try:
        data = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return raw, total
    if not isinstance(data, list):
        return raw, total
    for i, item in enumerate(data):
        if isinstance(item, str):
            fixed, hits = fix_text(item, patterns)
            data[i] = fixed
            total.update(hits)
    return json.dumps(data, ensure_ascii=False), total


def backup_db(db_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = db_path.with_name(db_path.stem + "_backup_" + stamp + db_path.suffix)
    shutil.copy2(str(db_path), str(bak))
    return bak


def main():
    parser = argparse.ArgumentParser(description="LaTeX 公式规范化")
    parser.add_argument("--db", default=str(DB_DEFAULT))
    parser.add_argument("--apply", action="store_true", help="实际修改数据库")
    parser.add_argument("--pattern", default="all",
                        help="all / func / unicode / degree / sub / unit（逗号分隔）")
    args = parser.parse_args()

    if args.pattern == "all":
        patterns = {"func", "unicode", "degree", "sub", "unit"}
    else:
        patterns = set(args.pattern.split(","))

    db_path = Path(args.db)
    if not db_path.exists():
        print("[失败] 数据库不存在：%s" % db_path, file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = list(conn.execute(
            "SELECT id, stem, options, answer, solution FROM questions "
            "WHERE quality_flag != 'low'"
        ))
        print("扫描 %d 题，修复模式：%s" % (len(rows), sorted(patterns)))

        total_hits = Counter()
        changed_ids = []
        examples = {}
        updates = []

        for row in rows:
            hits_row = Counter()
            new_stem, h1 = fix_text(row["stem"] or "", patterns)
            new_options, h2 = fix_options(row["options"] or "[]", patterns)
            new_answer, h3 = fix_answer(row["answer"] or "[]", patterns)
            new_solution, h4 = fix_text(row["solution"] or "", patterns)
            hits_row.update(h1)
            hits_row.update(h2)
            hits_row.update(h3)
            hits_row.update(h4)

            if hits_row:
                changed_ids.append(row["id"])
                total_hits.update(hits_row)
                for key in hits_row:
                    if key not in examples:
                        examples[key] = row["id"]
                if (new_stem != (row["stem"] or "")
                    or new_options != (row["options"] or "[]")
                    or new_answer != (row["answer"] or "[]")
                    or new_solution != (row["solution"] or "")):
                    updates.append((
                        new_stem, new_options, new_answer, new_solution, row["id"]
                    ))

        print()
        print("=" * 70)
        print("%-28s %8s   %s" % ("模式", "次数", "首次示例"))
        print("=" * 70)
        for key, n in sorted(total_hits.items(), key=lambda x: -x[1]):
            print("%-28s %8d   %s" % (key, n, examples.get(key, "")))
        print("=" * 70)
        print()
        print("受影响题目数：%d" % len(changed_ids))
        print("实际需更新题目数：%d" % len(updates))

        if not updates:
            print()
            print("无需修复")
            return 0

        if not args.apply:
            print()
            print("[dry-run] 未修改数据库；加 --apply 执行")
            return 0

        bak = backup_db(db_path)
        print()
        print("[备份] %s" % bak)

        with conn:
            for stem, options, answer, solution, qid in updates:
                conn.execute(
                    "UPDATE questions SET stem=?, options=?, answer=?, solution=?, "
                    "updated_at=datetime('now') WHERE id=?",
                    (stem, options, answer, solution, qid),
                )
        print("已更新 %d 题" % len(updates))

        print()
        print("=== 修复后复扫 ===")
        re_rows = list(conn.execute(
            "SELECT id, stem, options, answer, solution FROM questions "
            "WHERE quality_flag != 'low'"
        ))
        remain = Counter()
        for row in re_rows:
            _, h1 = fix_text(row["stem"] or "", patterns)
            _, h2 = fix_options(row["options"] or "[]", patterns)
            _, h3 = fix_answer(row["answer"] or "[]", patterns)
            _, h4 = fix_text(row["solution"] or "", patterns)
            remain.update(h1)
            remain.update(h2)
            remain.update(h3)
            remain.update(h4)
        if not remain:
            print("全部修复完成，0 残留")
            return 0
        print("仍有 %d 处残留：" % sum(remain.values()))
        for key, n in sorted(remain.items(), key=lambda x: -x[1]):
            print("  %s: %d" % (key, n))
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())