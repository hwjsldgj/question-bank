"""将题目 ID 从 <卷源>_<q|fig>NNNNN 迁移为 <字母><6位数字>。

规则：
- 字母按 (题型, 图片类型) 分配：
  single: 无图A / typst图B / 真实图C
  multiple: 无图D / typst图E / 真实图F
  fill: 无图G / typst图H / 真实图I
  solution: 无图J / typst图K / 真实图L
- 同类字母内按原 id 字符串升序，从 000001 开始编号
- 旧 id 存入 questions.legacy_id 列；完整映射存 scripts/id_mapping.json

用法：python scripts/migrate_question_ids.py
"""
import json
import shutil
import sqlite3
import time
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "question_bank.db"
MAP_FILE = Path(__file__).resolve().parent / "id_mapping.json"

LETTER_MAP = {
    ("single", "none"): "A", ("single", "typst"): "B", ("single", "image"): "C",
    ("multiple", "none"): "D", ("multiple", "typst"): "E", ("multiple", "image"): "F",
    ("fill", "none"): "G", ("fill", "typst"): "H", ("fill", "image"): "I",
    ("solution", "none"): "J", ("solution", "typst"): "K", ("solution", "image"): "L",
}


def main() -> None:
    if not DB.exists():
        print("数据库不存在")
        return

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # 防重入
    cols = [r[1] for r in con.execute("PRAGMA table_info(questions)")]
    if "legacy_id" not in cols:
        con.execute("ALTER TABLE questions ADD COLUMN legacy_id TEXT")
        con.commit()
        print("[1/6] 已加列 legacy_id")
    else:
        already = con.execute(
            "SELECT COUNT(*) FROM questions WHERE legacy_id IS NOT NULL AND legacy_id != ''"
        ).fetchone()[0]
        if already > 0:
            print(f"[!] 发现 {already} 条已迁移记录，中止。请从备份恢复。")
            con.close()
            return
        print("[1/6] legacy_id 列已存在")

    # 生成映射
    print("[2/6] 读取全库生成映射...")
    rows = con.execute(
        "SELECT id, type, typst_source, image_path FROM questions ORDER BY id"
    ).fetchall()

    groups = {}
    for r in rows:
        has_typst = bool(r["typst_source"] and r["typst_source"].strip())
        has_image = bool(r["image_path"] and r["image_path"].strip())
        kind = "typst" if has_typst else ("image" if has_image else "none")
        letter = LETTER_MAP.get((r["type"], kind))
        if not letter:
            print(f"[X] 未定义规则: type={r['type']}, kind={kind}, id={r['id']}")
            return
        groups.setdefault(letter, []).append(r["id"])

    mapping = {}
    for letter, ids in groups.items():
        for seq, old_id in enumerate(ids, start=1):
            mapping[old_id] = f"{letter}{seq:06d}"

    print(f"      共 {len(mapping)} 条映射，{len(groups)} 个字母分组")

    # 保存映射文件
    MAP_FILE.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[3/6] 映射已导出: {MAP_FILE.name}")

    # 执行更新
    print("[4/6] 执行事务更新...")
    con.execute("PRAGMA foreign_keys = OFF")
    try:
        with con:
            updates = [(new, old, old) for old, new in mapping.items()]
            con.executemany(
                "UPDATE questions SET id = ?, legacy_id = ? WHERE id = ?", updates
            )
            con.executemany(
                "UPDATE question_usage SET question_id = ? WHERE question_id = ?",
                [(new, old) for old, new in mapping.items()],
            )
            con.executemany(
                "UPDATE question_operations SET question_id = ? WHERE question_id = ?",
                [(new, old) for old, new in mapping.items()],
            )
    finally:
        con.execute("PRAGMA foreign_keys = ON")

    # 校验
    print("[5/6] 校验完整性...")
    null_legacy = con.execute("SELECT COUNT(*) FROM questions WHERE legacy_id IS NULL OR legacy_id=''").fetchone()[0]
    orphan_usage = con.execute(
        "SELECT COUNT(*) FROM question_usage u WHERE NOT EXISTS "
        "(SELECT 1 FROM questions q WHERE q.id = u.question_id)"
    ).fetchone()[0]
    orphan_ops = con.execute(
        "SELECT COUNT(*) FROM question_operations o WHERE o.question_id != '' AND NOT EXISTS "
        "(SELECT 1 FROM questions q WHERE q.id = o.question_id)"
    ).fetchone()[0]

    print(f"      legacy_id 缺失: {null_legacy}")
    print(f"      usage 孤儿行: {orphan_usage}")
    print(f"      operations 孤儿行: {orphan_ops}")

    if null_legacy == 0 and orphan_usage == 0 and orphan_ops == 0:
        print("[6/6] 迁移成功")
    else:
        print("[!] 校验未通过，请检查或回滚")

    # 抽样打印
    print("\n--- 新旧 id 对照（前 10 条）---")
    for r in con.execute("SELECT id, legacy_id FROM questions ORDER BY legacy_id LIMIT 10"):
        print(f"  {r['legacy_id']:30s} -> {r['id']}")

    con.close()


if __name__ == "__main__":
    main()
