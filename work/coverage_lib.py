"""覆盖率口径统一：把「源定义」和「有岗位数据的源」放在同一个盘子里数。

为什么需要：库里 467 家公司，源定义只覆盖 460 家里的一部分——`sources/alibaba.yaml`
这种单文件单公司的源，`sources:` 列表里没有 `company` 字段（公司名写在文件顶层），
之前的统计脚本只数 `sources[].company`，于是腾讯、阿里、字节、美团、京东、百度
这些**全都在库里有几万条岗位**的大厂被算成「未覆盖」。

本模块只做统计口径，不改数据。
"""
from __future__ import annotations

import glob
import json
import sqlite3
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SKIP_FILES = {"_example.yaml"}


def source_companies() -> dict[str, list[str]]:
    """返回 {公司名: [源 id, ...]}，同时认「多源文件的 sources 列表」和「单源文件顶层」。"""
    out: dict[str, list[str]] = {}
    for p in glob.glob(str(ROOT / "sources" / "*.yaml")):
        if Path(p).name in SKIP_FILES:
            continue
        try:
            d = yaml.safe_load(open(p, encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            continue
        if d.get("sources"):
            for s in d["sources"]:
                co = s.get("company")
                if co and s.get("id"):
                    out.setdefault(co, []).append(s["id"])
        elif d.get("company") and d.get("id"):
            out.setdefault(d["company"], []).append(d["id"])
    return out


def db_companies(db_path: str | Path) -> set[str]:
    """库里真正有岗位的公司名。"""
    p = Path(db_path)
    if p.is_dir():
        p = p / "jobs.db"
    if not p.exists():
        return set()
    c = sqlite3.connect(str(p))
    try:
        return {r[0] for r in c.execute(
            "select distinct co.name from job j join company co on co.id = j.company_id")}
    finally:
        c.close()


def coverage(db_path: str | Path | None = None) -> dict:
    sc = source_companies()
    db = db_companies(db_path) if db_path else set()
    covered = set(sc) | db
    tgt = yaml.safe_load((ROOT / "targets/top_companies.yaml").read_text(encoding="utf-8")) or {}
    want: set[str] = set()
    for v in (tgt.get("sectors") or {}).values():
        want.update(v)
    return {
        "sources": sum(len(v) for v in sc.values()),
        "source_companies": len(sc),
        "db_companies": len(db),
        "covered": len(covered),
        "target": len(want),
        "target_covered": len(want & covered),
        "missing": sorted(want - covered),
    }


if __name__ == "__main__":
    import sys
    r = coverage(sys.argv[1] if len(sys.argv) > 1 else "/tmp/fc2/jobs.db")
    print(json.dumps({k: v for k, v in r.items() if k != "missing"}, ensure_ascii=False, indent=2))
    print("missing 前 40:", "、".join(r["missing"][:40]))
