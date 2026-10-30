"""实习僧全量在招实习列表索引：抓 1..N 页，收集 (cname, uuid)，用于发现漏网公司。

不按关键词搜，而是按「全国 + intern」浏览全量列表，再按公司名归属匹配目标池。
用途：关键词搜索只能命中「岗位标题里带公司名」的岗位，会漏掉大量只写岗位名的公司。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobradar.nuxt import eval_returning  # noqa: E402

BASE = "https://www.shixiseng.com/interns"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
OUT = Path("work/sxs_index.jsonl")
STATE = Path("work/sxs_index_page.txt")


def jobs_of(sec: dict) -> list[dict]:
    j = sec.get("interns")
    j = (j.get("data") if isinstance(j, dict) else j) or []
    return [x for x in j if isinstance(x, dict)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=1000)
    ap.add_argument("--gap", type=float, default=1.0)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    start = 1
    if STATE.exists():
        try:
            start = int(STATE.read_text(encoding="utf-8").strip() or 1)
        except ValueError:
            start = 1
    seen: set[str] = set()
    if args.out.exists():
        for line in args.out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    seen.add(json.loads(line)["uuid"])
                except (ValueError, KeyError):
                    pass

    empty = 0
    with httpx.Client(timeout=25, headers={"User-Agent": UA}, follow_redirects=True) as c, \
            args.out.open("a", encoding="utf-8") as fh:
        for page in range(start, args.pages + 1):
            try:
                r = c.get(BASE, params={"city": "全国", "type": "intern", "page": page})
                d = eval_returning(r.text)
                sec = (d.get("data") or [{}])[0]
                jobs = jobs_of(sec)
            except Exception as exc:  # noqa: BLE001
                print(f"page {page} ERR {type(exc).__name__}", flush=True)
                time.sleep(max(args.gap, 3.0))
                continue
            if not jobs:
                empty += 1
                print(f"page {page} empty({empty})", flush=True)
                if empty >= 2:
                    break
            else:
                empty = 0
                for j in jobs:
                    u = j.get("uuid")
                    if not u or u in seen:
                        continue
                    seen.add(u)
                    fh.write(json.dumps({"uuid": u, "cname": j.get("cname"), "name": j.get("name"),
                                         "city": j.get("city"), "page": page}, ensure_ascii=False) + "\n")
            if page % 25 == 0:
                fh.flush()
                STATE.write_text(str(page + 1), encoding="utf-8")
                print(f"progress {page} rows={len(seen)}", flush=True)
            time.sleep(args.gap)
    STATE.write_text(str(args.pages + 1), encoding="utf-8")
    print(f"done rows={len(seen)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
