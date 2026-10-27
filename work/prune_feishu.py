"""清掉「门户活着但只放社招」的飞书源，并把证据写进 blocked.jsonl。

为什么删源而不是留着：飞书接口能拿到岗位总数，但适配器只收校招/实习
（`recruit_type_of()` 对社招返回 None，走 SkipRecord）。留着一个永远吐 0 条的源，
覆盖率统计会把它算成「已建源」，实际每天白跑一次请求。删掉 + 记 blocked，
下次再有人搜到这个门户时能直接看到「只有社招」，不会重复劳动。

用法：
    .venv\\Scripts\\python.exe work/prune_feishu.py [--dry-run]

输入：work/feishu_yield.json（逐源实测产出，[[id, 岗数], ...]）
输出：删掉的 YAML 清单、blocked.jsonl 追加行、companies.jsonl 状态修正
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.sources import load_sources  # noqa: E402

SOURCES = ROOT / "sources"
YIELD = ROOT / "work" / "feishu_yield.json"
BLOCKED = ROOT / "blocked.jsonl"
COMPANIES = ROOT / "companies.jsonl"
TODAY = "2026-10-28"


def load_yield() -> list[tuple[str, int]]:
    return [(sid, int(n)) for sid, n in json.loads(YIELD.read_text(encoding="utf-8"))]


def files_by_id() -> dict[str, Path]:
    """source id → 所在 YAML 文件。feishu 源都是一家一个文件，但先确认再删。"""
    out: dict[str, Path] = {}
    for path in sorted(SOURCES.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        for sid in re.findall(r"^\s*(?:-\s*)?id:\s*([A-Za-z0-9_-]+)\s*$", text, re.M):
            out.setdefault(sid, path)
        for sid in re.findall(r"-\s*\{id:\s*([A-Za-z0-9_-]+)", text):
            out.setdefault(sid, path)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    by_id = files_by_id()
    zeros = [sid for sid, n in load_yield() if n <= 0]
    srcs = {s.id: s for s in load_sources(SOURCES)}
    other = {}
    for s in srcs.values():
        other.setdefault(s.company, []).append(s.id)

    blocked_lines: list[str] = []
    removed: list[tuple[str, str, str]] = []
    for sid in zeros:
        s = srcs.get(sid)
        path = by_id.get(sid)
        if not s or not path:
            print(f"[skip] {sid}: 找不到源文件（可能已删）")
            continue
        text = path.read_text(encoding="utf-8")
        ids_in_file = re.findall(r"^\s*(?:-\s*)?id:\s*([A-Za-z0-9_-]+)\s*$", text, re.M)
        ids_in_file += re.findall(r"-\s*\{id:\s*([A-Za-z0-9_-]+)", text)
        if len(ids_in_file) != 1:
            print(f"[keep] {sid}: {path.name} 里有 {len(ids_in_file)} 个源，跳过")
            continue
        removed.append((sid, s.company, path.name))
        left = [i for i in other.get(s.company, []) if i != sid]
        blocked_lines.append(json.dumps({
            "company": s.company,
            "sector_source": "",
            "brand": "",
            "reason_code": "society_only",
            "evidence": (
                f"飞书 ATS 门户 {s.params.get('base_url', '')} 只有社招岗位，"
                f"校招/实习列表为空（{TODAY} 实测 0 条，接口 job_post_list 非空但类型全是社招）"
            ),
        }, ensure_ascii=False))
        if not args.dry_run:
            path.unlink()
        print(f"[del] {sid} ({s.company}) {path.name}" + ("" if left else "  ← 该公司再无源"))

    if not args.dry_run:
        with BLOCKED.open("a", encoding="utf-8") as f:
            for line in blocked_lines:
                f.write(line + "\n")

    # companies.jsonl：删源后不再有源的，状态改成 blocked，避免「声称官方页却在抓空气」
    pruned = {company for _, company, _ in removed}
    changed = 0
    if COMPANIES.exists() and not args.dry_run:
        rows = []
        for line in COMPANIES.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("company") in pruned:
                remaining = [i for i in other.get(r["company"], []) if i not in {z for z, _, _ in removed}]
                if not remaining and r.get("jd_status") == "official_page":
                    r["jd_status"] = "blocked"
                    r["verified_at"] = TODAY
                    ev = r.setdefault("evidence", {})
                    ev["grade"] = "B"
                    ev["grade_why"] = "门户只有社招，校招源已移除"
                    changed += 1
            rows.append(json.dumps(r, ensure_ascii=False))
        COMPANIES.write_text("\n".join(rows) + "\n", encoding="utf-8")

    print(f"\n删除 {len(removed)} 个源，追加 blocked {len(blocked_lines)} 行，companies 改状态 {changed} 行")
    if args.dry_run:
        print("（dry-run，未写盘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
