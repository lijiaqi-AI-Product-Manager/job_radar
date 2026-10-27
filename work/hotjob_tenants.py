"""从大易门户壳页里抠真实租户号 `SUxxxx`（不猜、不爆破）。

为什么需要：`site_ats` 只能拿到「这家公司用大易」这个事实（`xxx.hotjob.cn` 或
`{tenant}.hotjob.cn` 的域名），但大易适配器要的是 `SU` 开头的 24 位租户号，
它**只出现在门户页 HTML 里**（前端拼接口 URL 时用）。门户页是公开的服务端渲染页面。

用法：
    python3 work/hotjob_tenants.py --in /tmp/exp/site1.jsonl --out /tmp/exp/hotjob2.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobradar.adapters.base import USER_AGENT  # noqa: E402

SU = re.compile(r"(SU[0-9a-f]{20,32})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="/tmp/exp/site1.jsonl")
    ap.add_argument("--out", dest="out", default="/tmp/exp/hotjob2.jsonl")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()

    rows = []
    for ln in Path(a.src).read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        if r.get("ats") == "hotjob":
            rows.append(r)
    out = Path(a.out)
    done: set[str] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            done.add(json.loads(ln)["company"])
    todo = [r for r in rows if r["company"] not in done]
    print(f"大易命中 {len(rows)} 家，待取租户 {len(todo)} 家", flush=True)

    lock = threading.Lock()
    fh = out.open("a", encoding="utf-8")
    t0 = time.time()

    def work(r: dict) -> None:
        host = r["host"]
        found: list[str] = []
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=12.0,
                          follow_redirects=True) as cli:
            for u in (f"https://{host}/", f"https://{host}/wecruit/", f"https://{host}/su"):
                try:
                    rr = cli.get(u)
                except Exception:  # noqa: BLE001
                    continue
                if rr.status_code != 200:
                    continue
                for m in SU.findall(rr.text or ""):
                    if m not in found:
                        found.append(m)
                if found:
                    break
        rec = {"company": r["company"], "host": host, "tenants": found,
               "entry": r.get("entry", ""), "conf": r.get("conf", "")}
        with lock:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            print(("OK  " if found else "MISS") + f" {r['company']:14s} {host:32s} {found[:2]}",
                  flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(work, todo))
    fh.close()
    print(f"完成，用时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
