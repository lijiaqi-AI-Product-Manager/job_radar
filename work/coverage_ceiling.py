"""覆盖率天花板测算：把未覆盖目标按「证据类型」分类，回答 90% 到底能不能到。

分类：
  moka        招聘页指向 Moka（正文 AES 加密，红线不碰）
  aggregator  只找到智联/前程/猎聘/BOSS 等聚合站（红线不碰）
  platform    找到北森/大易/飞书/Workday/Tupu360 等可接入平台，但还没建成源（可做）
  self        有公司自有招聘页，但没识别出平台（要逐个判断有没有 JSON 接口，可做但慢）
  unknown     没找到任何招聘页线索（不知道去哪抓）

用法：python work/coverage_ceiling.py [--details]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobradar.pipeline.calendar import match_targets, target_names  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

WORK = ROOT / "work"
MOKA = ("mokahr", "moka.")
AGG = ("zhaopin.com", "51job", "liepin", "zhipin.com", "yingjiesheng", "kanzhun",
       "shixiseng", "niuke", "dajie.com", "lagou", "chinahr", "ganji")
PLAT = ("zhiye.com", "hotjob.cn", "jobs.feishu.cn", "myworkdayjobs", "tupu360",
        "gllue.com", "italent", "moka")  # moka 单独判


def blob(rec: dict) -> str:
    parts = [rec.get("url") or "", rec.get("host") or ""]
    for t in rec.get("tried") or []:
        parts.append(t if isinstance(t, str) else json.dumps(t, ensure_ascii=False))
    f = rec.get("found") or {}
    parts += [str(f.get(k) or "") for k in ("slug", "host", "kind", "url")]
    w = rec.get("best") or {}
    parts.append(str(w.get("url") or ""))
    return " ".join(parts).lower()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--details", action="store_true")
    a = ap.parse_args(argv)
    tgt = yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8"))
    companies = {s.company for s in load_sources("sources")}
    matched = match_targets(tgt, companies)
    rows = [(n, sec) for n, sec in target_names(tgt) if not matched.get(n)]
    blocked = set(tgt.get("blocked") or {})

    ev: dict[str, list[str]] = {}
    for fn in ("careers_ats.jsonl", "careers_ats2.jsonl", "ats_findings.jsonl", "careers_confirmed.jsonl"):
        p = WORK / fn
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            ev.setdefault(r.get("company") or "", []).append(blob(r))

    kinds, detail = Counter(), {}
    for name, sec in rows:
        if name in blocked:
            kinds["blocked"] += 1
            continue
        text = " ".join(ev.get(name) or [])
        if "mokahr" in text:
            k = "moka"
        elif any(x in text for x in AGG) and not any(x in text for x in ("zhiye.com", "hotjob.cn", "jobs.feishu.cn")):
            k = "aggregator"
        elif any(x in text for x in ("zhiye.com", "hotjob.cn", "jobs.feishu.cn", "myworkdayjobs", "tupu360", "gllue")):
            k = "platform"
        elif text:
            k = "self"
        else:
            k = "unknown"
        kinds[k] += 1
        detail.setdefault(k, []).append(f"{name}（{sec}）")

    total = len(rows) + sum(1 for n, _ in rows if n in blocked)  # 含 blocked 的口径
    print(f"目标 {len(rows)} 家未覆盖（另 {kinds['blocked']} 家已标 blocked）")
    print("| 类别 | 数量 | 占未覆盖 | 含义 |")
    print("|---|---|---|---|")
    label = {"moka": "只用 Moka，正文加密（不碰）", "aggregator": "只挂聚合站（不碰）",
             "platform": "平台入口已看到、还没建源（可做）", "self": "自有招聘页、平台未识别（可做但慢）",
             "unknown": "没有任何招聘页线索（难）"}
    for k in ("platform", "self", "unknown", "moka", "aggregator"):
        n = kinds[k]
        print(f"| {k} | {n} | {n / total:.0%} | {label[k]} |")
    cover = sum(1 for n, _ in target_names(tgt) if matched.get(n))
    print(f"\n当前覆盖 {cover} / {len(target_names(tgt))}（{cover / len(target_names(tgt)):.0%}）；"
          f"把 platform+self 全部拿下后的天花板 = {(cover + kinds['platform'] + kinds['self']) / len(target_names(tgt)):.0%}")
    if a.details:
        for k in ("platform", "unknown"):
            print(f"\n## {k}（{len(detail.get(k, []))}）")
            print("、".join(detail.get(k, [])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
