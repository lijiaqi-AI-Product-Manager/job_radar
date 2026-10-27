"""扫 Tupu360 平台租户：`careersite.tupu360.com/{tenant}/position/positionTotal`。

租户清单来自平台首页（`GET https://careersite.tupu360.com` 的 `/<tenant>` 链接），
不是猜的。逐个问「校招/社招各有多少岗」，0 岗的不收。
限速：同主机 1 rps（300 个租户约 5 分钟）。

用法：python3 work/tupu_scan.py --out /tmp/exp/tupu_scan.json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

UA = "jobradar/0.1 (+https://github.com/jobradar/job_radar)"
BASE = "https://careersite.tupu360.com"
_last = 0.0


def wait() -> None:
    global _last
    gap = time.time() - _last
    if gap < 1.0:
        time.sleep(1.0 - gap)
    _last = time.time()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/exp/tupu_scan.json")
    a = ap.parse_args()
    with httpx.Client(headers={"User-Agent": UA}, timeout=25.0, follow_redirects=True) as c:
        wait()
        home = c.get(BASE)
        links = sorted({u.strip("/") for u in __import__("re").findall(r'href="(/[^"/]+)"', home.text)})
        print(f"首页 {len(links)} 个租户", flush=True)
        out = []
        for t in links:
            row = {"tenant": t, "campus": None, "social": None, "name": ""}
            for key, rt in (("campus", "CAMPUSRECRUITMENT"), ("social", "SOCIALRECRUITMENT")):
                wait()
                try:
                    r = c.get(f"{BASE}/{t}/position/positionTotal", params={"recruitmentType": rt})
                    row[key] = int(r.json().get("positionTotal") or 0)
                except Exception:  # noqa: BLE001
                    row[key] = None
            if row["campus"] or row["social"]:
                wait()
                try:
                    r = c.get(f"{BASE}/{t}/position/index")
                    m = __import__("re").search(r"<title>\s*(.*?)\s*</title>", r.text, 16)
                    row["name"] = m.group(1) if m else ""
                except Exception:  # noqa: BLE001
                    pass
            out.append(row)
            print(f"{row['campus']!s:>5} {row['social']!s:>5}  {t:24s} {row['name'][:40]}", flush=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"写 {a.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
