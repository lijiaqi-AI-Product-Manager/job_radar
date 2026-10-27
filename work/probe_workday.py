"""探测自定义域名后缀的 Workday 站点（`{tenant}.{wdN}.myworkdayjobs.com` + 站点名）。

为什么单独写：Workday 的 URL 是三段拼出来的，猜对域名只算猜对三分之一——
还得知道 `site`（站点名，如 `NVIDIAExternalCareerSite`），而站点名又只能从首页 HTML 里
`/wday/cxs/{tenant}/{site}/...` 这种请求路径反推。所以流程是「猜域名 → 读首页 → 抠 site →
调公开 cxs 接口 → 看中国岗位数」。

红线：只读首页与公开 cxs 接口，无需登录、无签名；同一主机 ≤1 rps。

用法：
    python3 work/probe_workday.py --in names.txt --out /tmp/exp/wd.jsonl
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
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import USER_AGENT  # noqa: E402

# Workday 的站点名没有统一规律，但绝大多数租户叫这几个之一（大小写敏感）。
SITE_GUESS = ["External", "ExternalCareerSite", "Careers", "ExternalCareers", "Campus",
              "University", "Global_Careers", "External_Careers", "Jobs"]
WD_HOST = re.compile(r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com", re.I)
CXS = re.compile(r"/wday/cxs/([a-z0-9-]+)/([A-Za-z0-9_]+)/", re.I)
_last: dict[str, float] = {}


def throttle(host: str) -> None:
    gap = 1.05 - (time.time() - _last.get(host, 0.0))
    if gap > 0:
        time.sleep(gap)
    _last[host] = time.time()


def probe(tenant: str, wd: str, site: str | None = None) -> dict:
    host = f"{tenant}.{wd}.myworkdayjobs.com"
    out = {"kind": "workday", "tenant": tenant, "wd": wd, "host": host, "site": site,
           "ok": False, "count": 0}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20.0,
                      follow_redirects=True) as cli:
        if not site:
            # 根路径 `/` 对不存在和不存在的租户一律 406 且 0 字节（实测 nvidia 根也 406），
            # 所以必须先打 `/{lang}/{site}` 才会有内容。站点名我们不知道，但 Workday 对
            # 未知站点会给一个**不存在的页面**而不是 406——所以真正可行的是猜常见站点名。
            for site_try in SITE_GUESS[:-1]:
                throttle(host)
                try:
                    r = cli.get(f"https://{host}/en-US/{site_try}")
                except httpx.HTTPError:
                    continue
                if r.status_code != 200 or len(r.text or "") < 2000:
                    continue
                m = re.search(r'canonical" href="https://[^/]+/([A-Za-z0-9_]+)"', r.text or "")
                if not m:
                    continue
                site = m.group(1)
                out.update(tenant=tenant, site=site, guessed=site_try)
                break
            if not site:
                out["err"] = "no-site"
                return out
        # 公开 cxs 列表接口（官网前端用的同一个），limit=20 足够判断有没有中国岗位
        throttle(host)
        try:
            r = cli.post(f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
                         json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""})
            d = r.json()
        except Exception as e:  # noqa: BLE001
            out["err"] = type(e).__name__
            return out
        total = int(d.get("total") or 0)
        posts = d.get("jobPostings") or []
        cn = [p for p in posts if "china" in json.dumps(p.get("locationsText") or "",
                                                        ensure_ascii=False).lower()
              or "中国" in json.dumps(p, ensure_ascii=False)]
        out.update(ok=True, count=total, sample=[p.get("title") for p in posts[:3]],
                   cn_hint=len(cn))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True,
                    help="每行 `tenant` 或 `tenant wd5`；不给 wd 时按 wd1/wd3/wd5/wd103 试")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sites", default="", help="已知 site（可选，给 tenant:site 就跳过首页）")
    a = ap.parse_args()
    lines = [ln.split() for ln in Path(a.src).read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    known = {}
    if a.sites:
        for ln in Path(a.sites).read_text(encoding="utf-8").splitlines():
            if ":" in ln:
                k, v = ln.strip().split(":", 1)
                known[k] = v
    out = Path(a.out)
    done: set[str] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ln)
                done.add(d["tenant"] + "/" + d["wd"])
            except Exception:  # noqa: BLE001
                pass
    hits = 0
    with out.open("a", encoding="utf-8") as f:
        for parts in lines:
            tenant = parts[0].lower()
            wds = [parts[1]] if len(parts) > 1 else ["wd1", "wd3", "wd5", "wd103", "wd12"]
            for wd in wds:
                if tenant + "/" + wd in done:
                    continue
                rec = probe(tenant, wd, known.get(tenant))
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                if rec["ok"]:
                    hits += 1
                    print(f"OK {tenant:18s} {wd:6s} {rec.get('site','')[:34]:34s} "
                          f"{rec['count']:6d} 中国样本 {rec.get('cn_hint')} "
                          f"{(rec.get('sample') or [''])[0][:20]}", flush=True)
                    break
    print(f"命中 {hits}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
