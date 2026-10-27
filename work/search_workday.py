"""用「公司名 myworkdayjobs」搜出 Workday 站点全路径（含真实的 site 名）。

为什么不能像北森那样穷举：Workday 的地址是 `{tenant}.{wdN}.myworkdayjobs.com/en-US/{site}`，
`site` 是客户自起的名字（`NVIDIAExternalCareerSite`、`SchneiderElectricCareers`），
猜不到；而任何猜错的路径都返回 404，唯一的 `200` 是真实站点。所以只能靠索引反查。

红线：只读搜索结果页，同一个搜索主机 ≤1 rps，每公司 1 条查询；
命中的 URL 只当**候选**，仍然要过 `probe_url`/cxs 接口的有效性检查。

用法：
    python3 work/search_workday.py --in names.txt --out /tmp/exp/wdsearch.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "work"))

from search_ats import USER_AGENT, search  # noqa: E402

WD = re.compile(r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:([a-z]{2}-[A-Z]{2})/)?([A-Za-z0-9_]+)", re.I)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    names = [ln.strip() for ln in Path(a.src).read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    out = Path(a.out)
    done: set[str] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(ln)["company"])
            except Exception:  # noqa: BLE001
                pass
    todo = [n for n in names if n not in done]
    print(f"待搜 {len(todo)}", flush=True)
    hit = 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20.0,
                      follow_redirects=True) as cli, out.open("a", encoding="utf-8") as f:
        for i, n in enumerate(todo, 1):
            sites = []
            for q in (f"{n} myworkdayjobs", f"{n} careers myworkdayjobs"):
                for u in search(cli, q):
                    m = WD.search(u)
                    if m:
                        rec = (m.group(1).lower(), m.group(2).lower(), m.group(4))
                        if rec not in sites:
                            sites.append(rec)
                time.sleep(0.5)
                if sites:
                    break
            f.write(json.dumps({"company": n, "sites": sites}, ensure_ascii=False) + "\n")
            f.flush()
            if sites:
                hit += 1
                print(f"HIT {n[:12]:12s} {sites[:2]}", flush=True)
            time.sleep(1.05)
            if i % 30 == 0:
                print(f"... {i}/{len(todo)} 命中 {hit}", flush=True)
    print(f"完成，命中 {hit}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
