"""把待收录清单机械写入 `sources/beisen.yaml` / `sources/hotjob.yaml`。

为什么单独成脚本：手写 YAML 容易漏 id、漏去重（上一轮就因为没查重多了 10 条，
`test_all_sources_are_valid_and_unique` 直接报 492 != 484）。这里做三件事：
  1. **写入前再查一次重**（id、tenant 都不能重复）；
  2. 每条带一行注释（岗数 / 城市与日期样本比 / 归属证据），以后排障不用重新跑一遍；
  3. `--dry-run` 先打出来，确认再落盘。

只追加，不改已有行；文件末尾格式沿用现有风格（`  - {id: …, company: …, params: {tenant: …}}`）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

TODAY = "2026-10-27"


def load_existing(path: Path) -> tuple[set[str], set[str]]:
    d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    ids = {s["id"] for s in (d.get("sources") or []) if s.get("id")}
    tens = {(s.get("params") or {}).get("tenant") for s in (d.get("sources") or [])}
    return ids, {t for t in tens if t}


def beisen_line(r: dict) -> str:
    ev = f"title=「{r['title']}」" if r.get("title") else "title 未核到"
    return (f"  - {{id: {r['id']}, company: {r['company']}, "
            f"params: {{tenant: {r['tenant']}}}}}"
            f"  # {TODAY} 搜索反查新增：{r['count']} 岗；城市 {r['city']}、发布日 {r['date']}；{ev}\n")


def hotjob_line(r: dict) -> str:
    params = f"host: {r['host']}, tenant: {r['tenant']}"
    ev = f"岗位代码前缀 {','.join(r['prefix'])}" if r.get("prefix") else "自定义域名归属"
    return (f"  - id: {r['id']}\n"
            f"    company: {r['company']}\n"
            f"    params: {{{params}}}\n"
            f"    # {TODAY} 搜索反查新增：校招 {r['count']} 岗；城市 {r['city']}、发布日 {r['date']}；{ev}\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="/tmp/exp/to_add2.json")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    data = json.loads(Path(args.src).read_text(encoding="utf-8"))
    bp = ROOT / "sources/beisen.yaml"
    hp = ROOT / "sources/hotjob.yaml"
    bids, btens = load_existing(bp)
    hids, htens = load_existing(hp)

    blines: list[str] = []
    seen_b: set[str] = set()
    for r in data["beisen"]:
        if r["id"] in bids or r["tenant"] in btens or r["tenant"] in seen_b:
            print(f"  跳过 beisen 重复: {r['id']} / {r['tenant']}")
            continue
        seen_b.add(r["tenant"])
        blines.append(beisen_line(r))

    hlines: list[str] = []
    seen_h: set[str] = set()
    for r in data["hotjob"]:
        if r["id"] in hids or r["tenant"] in htens or r["tenant"] in seen_h:
            print(f"  跳过 hotjob 重复: {r['id']} / {r['tenant']}")
            continue
        seen_h.add(r["tenant"])
        hlines.append(hotjob_line(r))

    print(f"beisen 追加 {len(blines)} 条，hotjob 追加 {len(hlines)} 条")
    for ln in blines[:5] + hlines[:5]:
        print(ln.rstrip())
    if not args.apply:
        return 0

    for path, lines in ((bp, blines), (hp, hlines)):
        if not lines:
            continue
        txt = path.read_text(encoding="utf-8")
        if not txt.endswith("\n"):
            txt += "\n"
        path.write_text(txt + "".join(lines), encoding="utf-8")
        print(f"写入 {path.name} +{len(lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
