"""列出所有已知 hotjob 租户的 `recruitType` 岗数（1=校招 2=社招 3=实习）。

为什么需要：`sources/hotjob.yaml` 里有 8 个源写了 `max_pages: 5~10`，而
`/wecruit/positionInfo/listPosition` 的响应里有 `positonNum`（总岗数）——
一个校招 173 页的租户只抓 10 页，等于漏掉 80% 的岗位。而且**大部分源只配了
`recruit_types: [campus]`，社招那半边从来没抓过**（实测一汽 `recruitType=2`
有 1113 岗，抓到库里只有 500 条）。

本脚本只读第一页拿 `positonNum`，用于把 `max_pages` 按真实页数配足；
它不下发任何抓取，产出是给人看的表。

用法：`python3 work/hotjob_audit.py --out /tmp/exp/hj_audit.jsonl`
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import USER_AGENT  # noqa: E402

_last: dict[str, float] = {}


def throttle(host: str) -> None:
    gap = 1.05 - (time.time() - _last.get(host, 0.0))
    if gap > 0:
        time.sleep(gap)
    _last[host] = time.time()


def count(cli: httpx.Client, host: str, tenant: str, rtype: str) -> int:
    throttle(host)
    try:
        r = cli.get(f"https://{host}/wecruit/positionInfo/listPosition/{tenant}",
                    params={"iSaJAx": "isAjax", "request_locale": "zh_CN", "isFrompb": "true",
                            "recruitType": rtype, "pageSize": "10", "currentPage": "1"})
        d = r.json()
    except Exception:  # noqa: BLE001
        return -1
    body = d.get("data") if isinstance(d.get("data"), dict) else {}
    try:
        return int(body.get("positonNum") or 0)
    except (TypeError, ValueError):
        return -1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    srcs: list[dict] = []
    for p in glob.glob(str(ROOT / "sources" / "hotjob*.yaml")):
        d = yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {}
        for s in d.get("sources") or []:
            srcs.append(s)
    print(f"{len(srcs)} 个 hotjob 源", flush=True)
    out = Path(a.out)
    done: set[str] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(ln)["id"])
            except Exception:  # noqa: BLE001
                pass
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20.0,
                      follow_redirects=True) as cli, out.open("a", encoding="utf-8") as f:
        for s in srcs:
            if s["id"] in done:
                continue
            pr = s.get("params") or {}
            host, ten = pr.get("host", "wecruit.hotjob.cn"), pr.get("tenant")
            if not ten:
                continue
            c1, c2, c3 = (count(cli, host, ten, x) for x in ("1", "2", "3"))
            rec = {"id": s["id"], "company": s.get("company"), "host": host, "tenant": ten,
                   "campus": c1, "social": c2, "intern": c3,
                   "max_pages": pr.get("max_pages"),
                   "recruit_types": s.get("recruit_types")}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{s['id'][:26]:26s} 校招{c1:5d} 社招{c2:5d} 实习{c3:5d} "
                  f"max_pages={pr.get('max_pages')} types={s.get('recruit_types')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
