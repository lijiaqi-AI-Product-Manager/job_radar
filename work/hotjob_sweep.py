"""把 known-but-unsourced 的 hotjob（大易云）门户批量探活。

为什么单独做：`companies.jsonl` 里有 34 家 `ats=dayee` 的公司，其实全是大易云的两个入口——
老版 `www.hotjob.cn/wt/{TENANT}/...`（hotjob_legacy）与新版 `wecruit.hotjob.cn/SU.../`
（hotjob）。它们已经在公司池里但没有 source，是「零猜测、可验证」的增量。
另外把 Common Crawl / 被动 DNS 捞到的 hotjob 主机也一起试。

复用已注册的适配器本体做探活（不另写请求逻辑），失败即跳过；
输出 work/hotjob_candidates.jsonl：{company, host, tenant, kind, count, title, src}
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

from jobradar.adapters.base import load_all, make_client  # noqa: E402
from jobradar.models import Compliance, SourceConfig  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
SU_RE = re.compile(r"/(SU[0-9a-f]{20,})/")
WT_RE = re.compile(r"/wt/([A-Za-z0-9_\-]+)/")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def title_of(client: httpx.Client, url: str) -> str:
    try:
        r = client.get(url, timeout=15.0, follow_redirects=True)
        m = TITLE_RE.search(r.text)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()[:60]
    except httpx.HTTPError:
        pass
    return ""


def candidates() -> list[dict]:
    out: list[dict] = []
    rows = [json.loads(ln) for ln in open(ROOT / "companies.jsonl", encoding="utf-8") if ln.strip()]
    for r in rows:
        if r.get("ats") != "dayee":
            continue
        url, host = r.get("careers_url") or "", r.get("host") or ""
        m = WT_RE.search(url)
        if m:
            out.append({"company": r["company"], "host": host or "www.hotjob.cn",
                        "tenant": m.group(1), "kind": "hotjob_legacy", "src": "companies.dayee"})
            continue
        m = SU_RE.search(url)
        if m:
            out.append({"company": r["company"], "host": host or "wecruit.hotjob.cn",
                        "tenant": m.group(1), "kind": "hotjob", "src": "companies.dayee"})
    # 主机清单：CC + 被动 DNS 捞到的 hotjob 主机
    for path, src in ((WORK / "cc_hosts.tsv", "cc"),):
        if not path.exists():
            continue
        for ln in path.read_text(encoding="utf-8").splitlines():
            parts = ln.split("\t")
            if len(parts) >= 2 and parts[0] == "hotjob":
                out.append({"company": "", "host": parts[1], "tenant": parts[1].split(".")[0],
                            "kind": "hotjob_legacy", "src": src})
    return out


def probe(c: dict) -> dict | None:
    adapters = load_all()
    cls = adapters.get(c["kind"])
    if cls is None:
        return None
    params = {"tenant": c["tenant"], "host": c["host"], "max_pages": 1, "page_size": 20}
    comp = Compliance(checked_on=date(2026, 10, 28), robots="none",
                      terms="大易云招聘门户公开 JSON，匿名 GET", notes="probe")
    src = SourceConfig(id=f"{c['kind']}-{c['tenant'].lower()}", company=c["company"] or "待定",
                       adapter=c["kind"], params=params, recruit_types=["campus", "social"],
                       enabled=False, rate_limit_rps=1.0, compliance=comp)
    n = 0
    try:
        with make_client() as client:
            ad = cls(src, client)
            for _ in ad.fetch_all():
                n += 1
                if n >= 30:
                    break
            title = title_of(client, f"https://{c['host']}" + (f"/wt/{c['tenant']}/web/index" if c["kind"] == "hotjob_legacy" else "/"))
    except Exception:  # noqa: BLE001 - 任何异常都当探活失败
        return None
    if n <= 0:
        return None
    return {**c, "count": n, "title": title}


def main() -> None:
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    existing = load_sources(ROOT / "sources")
    have = {(s.adapter, str(s.params.get("tenant", "")).lower()) for s in existing}
    have |= {(s.adapter, str(s.params.get("tenant", ""))) for s in existing}
    todo = [c for c in candidates() if (c["kind"], c["tenant"].lower()) not in have]
    uniq: dict[tuple[str, str], dict] = {}
    for c in todo:
        uniq[(c["kind"], c["tenant"].lower())] = c
    todo = list(uniq.values())
    print(f"候选 {len(todo)}（已入库的已剔除）", flush=True)
    out = WORK / "hotjob_candidates.jsonl"
    t0 = time.time()
    with open(out, "w", encoding="utf-8") as fh, ThreadPoolExecutor(workers) as ex:
        for i, rec in enumerate(ex.map(probe, todo), 1):
            if rec:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                print(f"[{i}/{len(todo)}] {rec['kind']:<14} {rec['tenant'][:22]:<22} {rec['count']:>3}  {rec['title'][:34]}", flush=True)
    print(f"完成，用时 {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
