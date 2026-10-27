"""subdomain.center 枚举出的招聘平台子域 → 逐个探活（零猜测、可验证）。

2026-10-28 实测：`https://api.subdomain.center/?domain=zhiye.com` 一次返回 500 条子域，
hotjob.cn 320 条，jobs.feishu.cn 103 条 —— 这是目前唯一还能规模化拿到**真实存在**的
租户名/主机的渠道（crt.sh 只有通配符，搜索引擎全部限流）。

探活口径：
- beisen：打公开列表接口，`Code==200 且 Count>0`；再取门户 `<title>` 定归属，
  标题里出现「多品牌/共享门户/集团门户」或没有中文的一律不收。
- hotjob：主页里找 `SU[0-9a-f]{20,}`（大易新版租户 id），再走 hotjob 适配器拿列表；
  没有 SU 的再试老版 `/wt/{前缀}/web/json/position/list`。
- feishu：主页 `<title>` 即公司名，另打 csrf token 确认租户活着。

输出 work/sd_hits.jsonl：{platform, slug, company, count, title, host}
"""
from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(WORK))

import beisen_tenant_sweep as sweep  # noqa: E402

from jobradar.adapters.base import load_all, make_client  # noqa: E402
from jobradar.models import Compliance, SourceConfig  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
SU_RE = re.compile(r"(SU[0-9a-f]{20,})")
BAD_SLUG = re.compile(r"^(www|m|api|admin|test|demo|dev|stage|stg|uat|pre|cdn|static|img|mail|mailer|smtp|vpn|ns\d?|app|h5|wap|job|jobs)$")
CJK = re.compile(r"[\u4e00-\u9fa5]")
NAME_TAIL = re.compile(
    r"(校园招聘|社会招聘|招聘官网|招聘门户网|招聘门户|招聘微|社招|校招|招聘|官网|股份有限公司|有限责任公司"
    r"|有限公司|集团|控股|公司)+$"
)


def title_of(client: httpx.Client, url: str) -> str:
    try:
        r = client.get(url, timeout=15.0, follow_redirects=True)
        m = TITLE_RE.search(r.text)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()[:60]
    except httpx.HTTPError:
        pass
    return ""


def clean_company(title: str) -> str:
    name = re.split(r"[-－|｜_]", title)[0].strip()
    name = re.sub(r"^欢迎来到", "", name)
    name = re.sub(r"^加入", "", name)
    for _ in range(3):
        name = NAME_TAIL.sub("", name).strip()
    return name


def probe_beisen(tenant: str) -> dict | None:
    if BAD_SLUG.match(tenant) or tenant in sweep.TENANT_DENY:
        return None
    with httpx.Client(headers=UA, timeout=15.0, follow_redirects=True) as c:
        res = sweep.probe(c, tenant)
        count = int(res.get("count") or 0)
        if count <= 0:
            return None
        title = title_of(c, f"https://{tenant}.zhiye.com/")
        if not title or not CJK.search(title) or any(h in title for h in sweep.SHARED_PORTAL_HINT):
            return None
        company = clean_company(title)
        if len(company) < 2 or not CJK.search(company):
            return None
        return {"platform": "beisen", "slug": tenant, "company": company, "count": count,
                "title": title, "host": f"{tenant}.zhiye.com"}


def probe_hotjob(host: str) -> dict | None:
    if not host.endswith(".hotjob.cn") or host.count(".") != 2:
        return None
    prefix = host.split(".")[0]
    if BAD_SLUG.match(prefix) or len(prefix) < 2:
        return None
    with httpx.Client(headers=UA, timeout=15.0, follow_redirects=True) as c:
        try:
            r = c.get(f"https://{host}/")
        except httpx.HTTPError:
            return None
        title = ""
        m = TITLE_RE.search(r.text)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()[:60]
        su = SU_RE.search(r.text) or SU_RE.search(str(r.url))
        tenant = su.group(1) if su else prefix
        kind = "hotjob" if su else "hotjob_legacy"
        params = {"tenant": tenant, "host": host, "max_pages": 1, "page_size": 10}
        comp = Compliance(checked_on=date(2026, 10, 28), robots="none",
                          terms="大易云招聘门户公开 JSON，匿名 GET", notes="probe")
        src = SourceConfig(id=f"x-{prefix}", company=title or prefix, adapter=kind, params=params,
                           recruit_types=["campus"], enabled=False, rate_limit_rps=1.0, compliance=comp)
        n = 0
        try:
            with make_client() as cl:
                ad = load_all()[kind](src, cl)
                for _ in ad.fetch_all():
                    n += 1
                    if n >= 20:
                        break
        except Exception:  # noqa: BLE001
            return None
    if n <= 0:
        return None
    company = clean_company(title) if title and CJK.search(title) else prefix
    return {"platform": kind, "slug": tenant, "company": company, "count": n,
            "title": title, "host": host}


def probe_feishu(host: str) -> dict | None:
    if not host.endswith(".jobs.feishu.cn"):
        return None
    slug = host.split(".")[0]
    if BAD_SLUG.match(slug):
        return None
    with httpx.Client(headers=UA, timeout=15.0, follow_redirects=True) as c:
        title = title_of(c, f"https://{host}/")
        if not title or not CJK.search(title) or "404" in title or "页面不存在" in title:
            return None
        try:
            t = c.post(f"https://{host}/api/v1/csrf/token", json={"portal_entrance": 1},
                       headers={**UA, "Accept": "application/json"}, timeout=15.0)
            tok = (t.json().get("data") or {}).get("token")
        except Exception:  # noqa: BLE001
            tok = None
        if not tok:
            return None
    return {"platform": "feishu_atsx", "slug": slug, "company": clean_company(title),
            "count": 0, "title": title, "host": host}


def main() -> None:
    data = json.loads((WORK / "sd_center.json").read_text(encoding="utf-8"))
    existing = load_sources(ROOT / "sources")
    have_b = {str(s.params.get("tenant", "")).lower() for s in existing}
    have_h = set()
    for s in existing:
        for key in ("host", "base_url"):
            v = str(s.params.get(key, "")).lower()
            if v:
                have_h.add(v.removeprefix("https://").removeprefix("http://").strip("/"))
    tasks: list[tuple[str, str]] = []
    for h in data.get("zhiye.com", []):
        t = h.split(".")[0]
        if t not in have_b:
            tasks.append(("beisen", t))
    for h in data.get("hotjob.cn", []):
        if h not in have_h:
            tasks.append(("hotjob", h))
    for h in data.get("jobs.feishu.cn", []):
        if h not in have_h:
            tasks.append(("feishu", h))
    print(f"任务 {len(tasks)}（beisen/hotjob/feishu）", flush=True)

    fn = {"beisen": probe_beisen, "hotjob": probe_hotjob, "feishu": probe_feishu}
    out = WORK / "sd_hits.jsonl"
    t0 = time.time()
    ok = 0
    with open(out, "w", encoding="utf-8") as fh, ThreadPoolExecutor(10) as ex:
        for i, rec in enumerate(ex.map(lambda x: fn[x[0]](x[1]), tasks), 1):
            if rec:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                ok += 1
                print(f"[{i}/{len(tasks)}] {rec['platform']:<11} {rec['slug'][:20]:<20} {rec['count']:>4} {rec['company'][:18]}", flush=True)
            if i % 100 == 0:
                print(f"... {i}/{len(tasks)} {time.time() - t0:.0f}s 命中 {ok}", flush=True)
    print(f"完成：命中 {ok}，用时 {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
