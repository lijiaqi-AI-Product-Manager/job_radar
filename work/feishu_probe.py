"""验证「飞书招聘 ATSX」候选门户能不能直接抓（匿名 csrf + 公开职位列表 JSON）。

为什么值得单独跑：`feishu_atsx` 适配器已经成熟（蔚来/小鹏/Momenta 在跑），
其它用飞书的公司只是 `base_url` 不同。实测一次 csrf + 一次列表就知道能不能收，
不需要为每家写新代码。搜索反查一轮能捞出十几家（MiniMax、中科创达、亚信安全、
元气森林、去哪儿、国民技术、小马智行…），这是目前性价比最高的一批增量。

红线：只读门户公开接口（跟浏览器同顺序：先取 csrf token，再带 token 请求列表）；
token 只在内存里，不落盘；同一主机 ≤1 rps。

用法：
    python3 work/feishu_probe.py --in /tmp/exp/feishu.txt --out /tmp/exp/feishu_ok.jsonl
    # --in 每行 `公司名 base_url`（空格分隔）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import USER_AGENT  # noqa: E402

_last: dict[str, float] = {}


def throttle(host: str) -> None:
    gap = 1.05 - (time.time() - _last.get(host, 0.0))
    if gap > 0:
        time.sleep(gap)
    _last[host] = time.time()


def probe(cli: httpx.Client, base: str, path: str = "campus") -> dict:
    base = base.rstrip("/")
    host = base.split("//")[-1].split("/")[0]
    out = {"base_url": base, "website_path": path, "ok": False, "count": 0, "jobs": [], "err": ""}
    for p in (path, "index", "campus"):
        throttle(host)
        try:
            t = cli.post(f"{base}/api/v1/csrf/token", json={"portal_entrance": 1})
            tok = ((t.json() or {}).get("data") or {}).get("token") or ""
        except Exception:  # noqa: BLE001
            tok = ""
        if not tok:
            out["err"] = "no_csrf"
            continue
        hdr = {"x-csrf-token": tok, "accept": "application/json, text/plain, */*",
               "portal-channel": p, "portal-platform": "pc", "website-path": p,
               "origin": base, "referer": f"{base}/{p}", "content-type": "application/json"}
        throttle(host)
        try:
            # **必须 POST + 完整 body**：GET 掉回 SPA 首页 HTML（实测中科创达），
            # 只有 POST 才返回 JSON。这个坑写在这里，免得下次又用 GET 试一遍。
            body = {"keyword": "", "limit": 50, "offset": 0, "job_category_id_list": [],
                    "tag_id_list": [], "location_code_list": [], "subject_id_list": [],
                    "recruitment_id_list": [], "portal_type": 3, "job_function_id_list": [],
                    "storefront_id_list": [], "portal_entrance": 1}
            r = cli.post(f"{base}/api/v1/search/job/posts",
                         params={"portal_type": 3, "limit": 50, "offset": 0, "portal_entrance": 1},
                         json=body, headers=hdr)
            d = r.json()
        except Exception as e:  # noqa: BLE001
            out["err"] = type(e).__name__
            continue
        data = d.get("data") or {}
        posts = data.get("job_post_list") or []
        cnt = int(data.get("count") or len(posts))
        if cnt:
            out.update(ok=True, count=cnt, website_path=p,
                       jobs=[str(x.get("title") or "")[:36] for x in posts[:6]],
                       cities=[str(x.get("city_info") or x.get("city_list") or "")[:20]
                               for x in posts[:3]])
            return out
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    items: list[tuple[str, str]] = []
    for ln in Path(a.src).read_text(encoding="utf-8-sig").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split()
        if len(parts) >= 2:
            items.append((parts[0], parts[1]))
    print(f"待验 {len(items)} 个飞书门户", flush=True)
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20.0,
                      follow_redirects=True) as cli, open(a.out, "a", encoding="utf-8") as f:
        for comp, base in items:
            r = probe(cli, base)
            r["company"] = comp
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            print(("OK  " if r["ok"] else "--  ") + f"{comp:12s} {base[:46]:46s} "
                  f"{r['count']:5d} {(r['jobs'] or [''])[0][:26]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
