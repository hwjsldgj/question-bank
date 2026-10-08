# -*- coding: utf-8 -*-
"""修复数据库中「选项含【图】但 typst_source 为空或不匹配」的题。

背景：早期导入脚本对 _q 路径从不提取 typst_source，导致部分含选项图的题
（如 2026_上海春季卷_q00013）图渲染不出来。本脚本从原始 gaokao/*.typ
重新提取 #let 定义 + #figure 调用，写回数据库。

用法：python scripts/repair_missing_typst_source.py [--dry-run]
"""
import argparse
import datetime
import re
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAOKAO = Path(r"C:\Users\90579\Desktop\Documents\school\miscSchool\gaokao")
DB = ROOT / "question_bank.db"


def extract_balanced_from(text, start):
    i = start
    n = len(text)
    while i < n and text[i] not in "({[":
        i += 1
    if i >= n:
        return None, None
    open_c = text[i]
    close_c = {"(": ")", "{": "}", "[": "]"}[open_c]
    depth = 0
    while i < n:
        c = text[i]
        if c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return start, i + 1
        i += 1
    return None, None


def extract_let_full(text, name):
    m = re.search(r"#let\s+" + re.escape(name) + r"\b", text)
    if not m:
        return None
    eq = text.find("=", m.end())
    if eq < 0:
        return None
    s, e = extract_balanced_from(text, eq + 1)
    return text[m.start():e] if s is not None else None


def extract_import(text):
    m = re.search(r'#import\s+"/src/lib\.typ"\s*:\s*\([^)]*\)', text, re.S)
    return m.group(0) if m else None


def locate_typ(qid):
    m = re.match(r"^(\d{4})_(.+?)_(?:q|fig)\d+$", qid)
    if not m:
        return None
    year, paper = m.group(1), m.group(2)
    year_dir = GAOKAO / year
    if not year_dir.is_dir():
        return None
    for f in year_dir.glob("*.typ"):
        s = f.stem
        if paper == s or paper == s + "卷" or paper.rstrip("卷") == s.rstrip("卷"):
            return f
    for f in year_dir.glob("*.typ"):
        if paper in f.stem or f.stem in paper:
            return f
    return None


def extract_question_block(text, keyword):
    positions = [m.start() for m in re.finditer(r"#question\s*\(", text)]
    positions.append(len(text))
    for i in range(len(positions) - 1):
        s = positions[i]
        if keyword in text[s:positions[i + 1]]:
            _, e = extract_balanced_from(text, s + len("#question"))
            return text[s:e]
    return None


def extract_figure_refs(block):
    return [(m.group(1), int(m.group(2)))
            for m in re.finditer(r"#([a-zA-Z_][\w\-]*)\s*\(\s*(\d+)\s*\)", block)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    cur.execute("""
        SELECT id, stem, options, typst_source
        FROM questions WHERE options LIKE '%【图】%' ORDER BY id
    """)
    targets = []
    for qid, stem, opts, src in cur.fetchall():
        n_opt = (opts or "").count("【图】")
        n_fig = (src or "").count("#figure")
        if n_opt > 0 and (not src or n_opt > n_fig):
            targets.append((qid, stem, n_opt, n_fig))

    print(f"需要修复: {len(targets)} 道")
    for qid, _, n_opt, n_fig in targets:
        print(f"  {qid}  选项图={n_opt} 现有#figure={n_fig}")

    if args.dry_run or not targets:
        con.close()
        return

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy(DB, DB.with_name(f"question_bank_backup_{ts}.db"))
    print(f"数据库已备份: question_bank_backup_{ts}.db")

    fixed = 0
    for qid, stem, _, _ in targets:
        typ_file = locate_typ(qid)
        if not typ_file:
            print(f"  [SKIP] {qid}: 找不到 .typ")
            continue
        src = typ_file.read_text(encoding="utf-8")
        kw = "平移对称法" if "平移对称" in (stem or "") else None
        if not kw:
            m = re.search(r"[\u4e00-\u9fff]{4,12}", stem or "")
            kw = m.group(0) if m else None
        block = extract_question_block(src, kw) if kw else None
        if not block:
            print(f"  [SKIP] {qid}: 定位题目块失败")
            continue
        refs = extract_figure_refs(block)
        if not refs:
            print(f"  [SKIP] {qid}: 题目块里无 #xxx-figure(N)")
            continue
        imp = extract_import(src)
        seen = set()
        lets = []
        for fn, _ in refs:
            if fn in seen:
                continue
            seen.add(fn)
            d = extract_let_full(src, fn)
            if d:
                lets.append(d)
        parts = [imp, ""] + lets + [
            "", "#set page(width: auto, height: auto, margin: 8pt)",
            "#set align(center)", "",
        ]
        for fn, n in refs:
            parts.append(f"#figure({fn}({n}))")
        new_src = "\n".join(parts) + "\n"
        cur.execute("UPDATE questions SET typst_source=? WHERE id=?", (new_src, qid))
        print(f"  [OK] {qid}: {len(new_src.splitlines())} 行, #figure×{new_src.count('#figure')}")
        fixed += 1

    con.commit()
    con.close()
    print(f"\n修复完成: {fixed}/{len(targets)}")


if __name__ == "__main__":
    main()