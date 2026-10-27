"""抓 Tupu360 各租户门户的公司名：`<meta name="description" content="阿斯利康">`。

门户 `<title>` 一律是「职位列表」，只有这个 meta 写公司名，是**归属的唯一可信来源**
（租户 slug 经常是数字或拼音缩写，不能拿 slug 猜公司）。
限速 1 rps；断点续传（已有的不重复请求）。

用法：python3 work/tupu_names.py --in /tmp/exp/tupu_scan.json --out /tmp/exp/tupu_names.json
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import httpx

UA = "jobradar/0.1 (+https://github.com/jobradar/job_radar)"
BASE = "https://careersite.tupu360.com"
META = re.compile(r'<meta name="description" content="([^"]*)"')
_last = 0.0


def wait() -> None:
    global _last
    gap = time.time() - _last
    if gap < 1.0:
        time.sleep(1.0 - gap)
    _last = time.time()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="/tmp/exp/tupu_scan.json")
    ap.add_argument("--out", dest="out", default="/tmp/exp/tupu_names.json")
    ap.add_argument("--min", type=int, default=8, help="只取 ≥N 岗的租户")
    a = ap.parse_args()
    rows = json.loads(Path(a.src).read_text(encoding="utf-8"))
    keep = [r for r in rows if (r["campus"] or 0) + (r["social"] or 0) >= a.min]
    out = {}
    p = Path(a.out)
    if p.exists():
        out = json.loads(p.read_text(encoding="utf-8"))
    with httpx.Client(headers={"User-Agent": UA}, timeout=20.0, follow_redirects=True) as c:
        for r in keep:
            t = r["tenant"]
            if out.get(t):
                continue
            wait()
            try:
                h = c.get(f"{BASE}/{t}/position/index").text
                m = META.search(h)
                out[t] = m.group(1).strip() if m else ""
            except Exception:  # noqa: BLE001
                out[t] = "ERR"
            print(t, "|", out[t][:40], flush=True)
            p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(out)} 条 → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
