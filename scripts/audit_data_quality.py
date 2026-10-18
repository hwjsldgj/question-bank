"""数据质量全库抽查脚本（只读，不改数据库）。

用法：
    python scripts/audit_data_quality.py
    python scripts/audit_data_quality.py --db path/to/question_bank.db
    python scripts/audit_data_quality.py --out-dir report

输出：
    - 控制台摘要（每类问题计数 + 分布统计）
    - <out-dir>/audit_YYYYMMDD_HHMMSS.csv   逐条问题清单
    - <out-dir>/audit_YYYYMMDD_HHMMSS.json  汇总（供后续程序消费）

检查维度：
    1. 完整性    题干 / 答案 / 解析 / 知识点板块 / 知识点 / 卷源 / 科目
    2. 合法性    type / difficulty / quality_flag / difficulty_source / source
    3. 结构一致性 题型与选项、答案数量
    4. 内容质量  空壳选项、答案 key 不在选项、题干过短
    5. 知识点体系 板块在 13 大类内、知识点在 81 细分内
    6. 重复      题干指纹完全相同的题组
    7. 分布      题型 / 难度 / 质量标记

退出码：
    0  无 error 级问题
    1  存在 error 级问题
    2  数据库不存在
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain.entities.question import stem_fingerprint


VALID_TYPES = {"single", "multiple", "fill", "solution"}
VALID_DIFFICULTY = {"easy", "medium", "hard", "pending"}
VALID_QUALITY = {"normal", "quality", "low"}
VALID_DIFF_SOURCE = {"ai", "manual"}
VALID_SOURCE = {"bank", "ai"}


def parse_list_field(raw):
    """解析以 JSON 数组或分隔符存储的列表字段。"""
    text = (raw or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except (ValueError, TypeError):
            pass
    return [part.strip() for part in re.split(r"[、,，;；\n]", text) if part.strip()]


def parse_options(raw):
    """解析 options 字段（JSON 数组 [{key,text}]），容错返回 []。"""
    text = (raw or "").strip()
    if not text or not text.startswith("["):
        return []
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    result = []
    for item in parsed:
        if isinstance(item, dict):
            result.append({
                "key": str(item.get("key", "")).strip(),
                "text": str(item.get("text", "")).strip(),
            })
    return result


def load_taxonomy():
    """加载知识点体系：13 大类板块 + 81 细分考点。"""
    path = ROOT / "knowledge_sections.json"
    if not path.exists():
        return set(), set()
    with open(path, encoding="utf-8") as f:
        tree = json.load(f).get("数学", {})
    sections = set(tree.keys())
    kps = set()
    for items in tree.values():
        kps.update(items)
    return sections, kps


def audit(db_path, all_sections, all_kps):
    """执行全库检查，返回 (issues, distribution, total)。"""
    issues = []
    distribution = {
        "type": Counter(),
        "difficulty": Counter(),
        "quality_flag": Counter(),
        "difficulty_source": Counter(),
        "source": Counter(),
    }
    fingerprints = defaultdict(list)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = list(conn.execute("SELECT * FROM questions"))
    finally:
        conn.close()

    total = len(rows)
    for row in rows:
        qid = row["id"]
        qtype = (row["type"] or "").strip()
        difficulty = (row["difficulty"] or "").strip()
        quality = (row["quality_flag"] or "").strip()
        diff_src = (row["difficulty_source"] or "").strip()
        source = (row["source"] or "").strip()

        distribution["type"][qtype] += 1
        distribution["difficulty"][difficulty] += 1
        distribution["quality_flag"][quality] += 1
        distribution["difficulty_source"][diff_src] += 1
        distribution["source"][source] += 1

        is_low = quality == "low"

        def add(category, severity, detail):
            # 已标记 low 的题视为「已隔离」，error 降级为 info 避免重复告警
            effective_severity = "info" if (is_low and severity == "error") else severity
            issues.append({
                "question_id": qid,
                "category": category,
                "severity": effective_severity,
                "detail": detail,
                "subject": row["subject"] or "",
                "paper_source": row["paper_source"] or "",
                "type": qtype,
                "difficulty": difficulty,
            })

        stem = (row["stem"] or "").strip()
        solution = (row["solution"] or "").strip()
        section_raw = row["section"] or ""
        kps = parse_list_field(row["knowledge_points"])
        options = parse_options(row["options"])
        answer = parse_list_field(row["answer"])

        # 1. 完整性
        if not stem:
            add("EMPTY_STEM", "error", "题干为空")
        elif len(stem) < 8:
            add("STEM_TOO_SHORT", "warning", "题干仅 %d 字符：%r" % (len(stem), stem))
        if not answer:
            add("EMPTY_ANSWER", "error", "答案为空")
        if not solution:
            add("EMPTY_SOLUTION", "warning", "解析为空")
        if not section_raw.strip():
            add("EMPTY_SECTION", "error", "知识点板块为空")
        if not kps:
            add("EMPTY_KNOWLEDGE_POINTS", "warning", "知识点为空")
        if not (row["paper_source"] or "").strip():
            add("EMPTY_PAPER_SOURCE", "warning", "卷源为空")
        if not (row["subject"] or "").strip():
            add("EMPTY_SUBJECT", "error", "科目为空")

        # 2. 合法性
        if qtype not in VALID_TYPES:
            add("INVALID_TYPE", "error", "非法题型：%r" % qtype)
        if difficulty not in VALID_DIFFICULTY:
            add("INVALID_DIFFICULTY", "error", "非法难度：%r" % difficulty)
        if quality not in VALID_QUALITY:
            add("INVALID_QUALITY_FLAG", "error", "非法质量标记：%r" % quality)
        if diff_src not in VALID_DIFF_SOURCE:
            add("INVALID_DIFFICULTY_SOURCE", "error", "非法难度来源：%r" % diff_src)
        if source not in VALID_SOURCE:
            add("INVALID_SOURCE", "error", "非法题目来源：%r" % source)

        # 3. 结构一致性
        if qtype in ("single", "multiple"):
            if len(options) < 2:
                add("CHOICE_OPTIONS_TOO_FEW", "error",
                    "%s 选项数 %d < 2" % (qtype, len(options)))
            if qtype == "single" and len(answer) > 1:
                add("SINGLE_ANSWER_COUNT", "warning",
                    "单选答案 %d 项：%s" % (len(answer), answer))
        elif qtype in ("fill", "solution"):
            if options:
                add("NON_CHOICE_HAS_OPTIONS", "error",
                    "%s 不应有选项，实际 %d 项" % (qtype, len(options)))

        # 4. 内容质量
        for opt in options:
            if not opt["text"]:
                add("EMPTY_OPTION_TEXT", "error",
                    "选项 %r 正文为空" % opt["key"])
        if qtype in ("single", "multiple") and options:
            option_keys = {opt["key"] for opt in options if opt["key"]}
            for ans in answer:
                if ans and ans not in option_keys:
                    add("ANSWER_KEY_NOT_IN_OPTIONS", "error",
                        "答案 %r 不在选项 %s 中" % (ans, sorted(option_keys)))

        # 5. 知识点体系
        if section_raw.strip():
            # 板块名本身含空格（如「9 解析几何」），不能用 split_sections
            # （该函数把空格也当分隔符）；这里只按顿号拆分
            for sec in [p.strip() for p in section_raw.split("、") if p.strip()]:
                if all_sections and sec not in all_sections and sec != "0 纯图题":
                    add("SECTION_NOT_IN_TAXONOMY", "warning",
                        "知识点板块 %r 不在 13 大类内" % sec)
        for kp in kps:
            if all_kps and kp not in all_kps and kp != "纯图":
                add("KNOWLEDGE_POINT_NOT_IN_TAXONOMY", "warning",
                    "知识点 %r 不在 81 细分内" % kp)

        # 6. 重复候选
        fp = stem_fingerprint(stem)
        if fp:
            fingerprints[fp].append(qid)

    # 6. 重复
    for fp, ids in fingerprints.items():
        if len(ids) > 1:
            for qid in ids:
                others = [x for x in ids if x != qid]
                issues.append({
                    "question_id": qid,
                    "category": "DUPLICATE_STEM",
                    "severity": "warning",
                    "detail": "与 %s 题干指纹相同" % others,
                    "subject": "",
                    "paper_source": "",
                    "type": "",
                    "difficulty": "",
                })

    return issues, distribution, total


def write_csv(path, issues):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "question_id", "category", "severity", "detail",
        "subject", "paper_source", "type", "difficulty",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for issue in issues:
            writer.writerow(issue)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def print_summary(issues, distribution, total, csv_path, json_path):
    print()
    print("=== 数据质量抽查报告 ===")
    print("总题数：%d" % total)
    print()

    by_cat = Counter(i["category"] for i in issues)
    by_sev = Counter(i["severity"] for i in issues)

    print("[问题分类计数]")
    if not by_cat:
        print("  （无问题）")
    else:
        for cat, n in sorted(by_cat.items(), key=lambda x: (-x[1], x[0])):
            print("  %-35s %d" % (cat, n))
    print()

    print("[严重程度汇总]")
    for sev in ("error", "warning", "info"):
        print("  %-10s %d" % (sev, by_sev.get(sev, 0)))
    print()

    print("[分布]")
    for key in ("type", "difficulty", "quality_flag", "difficulty_source", "source"):
        items = distribution[key]
        parts = " / ".join("%s %d" % (k or "(空)", v) for k, v in items.most_common())
        print("  %-18s %s" % (key, parts))
    print()

    print("[明细已写入]")
    print("  CSV : %s" % csv_path)
    print("  JSON: %s" % json_path)
    print()


def main():
    parser = argparse.ArgumentParser(description="数据质量全库抽查（只读）")
    parser.add_argument("--db", default=str(ROOT / "question_bank.db"))
    parser.add_argument("--out-dir", default=str(ROOT / "report"))
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print("[失败] 数据库不存在：%s" % db_path, file=sys.stderr)
        return 2

    all_sections, all_kps = load_taxonomy()
    if not all_sections:
        print("[警告] 未能加载 knowledge_sections.json，跳过知识点体系校验",
              file=sys.stderr)

    issues, distribution, total = audit(db_path, all_sections, all_kps)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir)
    csv_path = out_dir / ("audit_%s.csv" % stamp)
    json_path = out_dir / ("audit_%s.json" % stamp)

    write_csv(csv_path, issues)
    write_json(json_path, {
        "generated_at": stamp,
        "db": str(db_path),
        "total": total,
        "issue_count": len(issues),
        "distribution": {k: dict(v) for k, v in distribution.items()},
        "issues": issues,
    })

    print_summary(issues, distribution, total, csv_path, json_path)

    has_error = any(i["severity"] == "error" for i in issues)
    return 1 if has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())