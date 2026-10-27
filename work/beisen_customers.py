"""北森官网客户案例页 → 客户名单 → 拼音探租户（高先验渠道）。

为什么这条比瞎猜强：`beisen.com/customer/{n}.html` 每篇案例页的正文头部有一行
`<p>客户名</p><p><span>公司行业</span>…`，这就是**已经买了北森招聘系统**的客户名单——
先验概率高，租户名大多是公司拼音，探中的机会比从全网名单里猜大得多。

流程：抓案例页（n=2..N，遇到默认兜底页即止）→ 去重、剔除已入库公司 →
`work/beisen_tenant_sweep.py` 的 `candidates()` 生成租户候选 → 打公开列表接口 →
`<title>` 里出现公司名核心词才算命中。

输出：work/beisen_customers.jsonl（{name, industry, url}）、
      work/beisen_customer_hits.jsonl（{company, tenant, count, title, industry}）
"""
from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(WORK))

from jobradar.sources import load_sources  # noqa: E402

sys.path.insert(0, str(WORK))
import beisen_tenant_sweep as sweep  # noqa: E402

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}
DEFAULT_TITLE = "北森HRSaaS软件-人才测评"
NAME_RE = re.compile(r"<p>\s*([^<>{}]{2,40}?)\s*</p>\s*<p><span>公司行业</span>")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def collect(limit: int) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    miss = 0
    with httpx.Client(headers=UA, timeout=20.0, follow_redirects=True) as c:
        for n in range(2, limit):
            try:
                r = c.get(f"https://www.beisen.com/customer/{n}.html")
            except httpx.HTTPError:
                continue
            m = NAME_RE.search(r.text)
            if not m:
                # 视频/专题页没有客户名，连续 25 个都取不到才认为案例区结束
                miss += 1
                if miss >= 25:
                    print(f"连续 {miss} 页没有客户名，到 {n - 1} 为止", flush=True)
                    break
                time.sleep(0.25)
                continue
            miss = 0
            name = re.sub(r"\s+", "", m.group(1))
            if name in seen or len(name) < 2:
                continue
            seen.add(name)
            ind = re.search(r"公司行业</span>\s*<a[^>]*>([^<]{2,20})</a>", r.text)
            out.append({"name": name, "industry": ind.group(1) if ind else "", "url": f"https://www.beisen.com/customer/{n}.html"})
            if len(out) % 50 == 0:
                print(f"  {len(out)} 家（n={n}）", flush=True)
            time.sleep(0.35)
    return out


def core_of(name: str) -> str:
    return re.sub(r"(股份有限公司|有限责任公司|有限公司|集团|控股|公司)$", "", name.strip())


def probe_one(item: dict) -> dict | None:
    name = item["name"]
    core = core_of(name)
    cands = sweep.candidates(name, sweep.load_pinyin())[:6]
    if not cands:
        return None
    with httpx.Client(headers=UA, timeout=15.0, follow_redirects=True) as c:
        for cand in cands:
            if cand in sweep.TENANT_DENY:
                continue
            res = sweep.probe(c, cand)
            count = int(res.get("count") or 0)
            if count <= 0:
                continue
            try:
                home = c.get(f"https://{cand}.zhiye.com/", timeout=15.0)
                tm = TITLE_RE.search(home.text)
                title = re.sub(r"\s+", " ", tm.group(1)).strip()[:60] if tm else ""
            except httpx.HTTPError:
                title = ""
            if any(hint in title for hint in sweep.SHARED_PORTAL_HINT):
                continue
            if core[:2] not in title and name[:2] not in title:
                continue  # 标题对不上就是别家的门户，不收
            return {"company": name, "tenant": cand, "count": count, "title": title,
                    "industry": item.get("industry", ""), "case_url": item["url"]}
            time.sleep(0.6)
    return None


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 380
    cust_path = WORK / "beisen_customers.jsonl"
    if cust_path.exists() and cust_path.stat().st_size > 1000:
        cust = [json.loads(ln) for ln in cust_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        print(f"复用客户名单 {len(cust)} 家", flush=True)
    else:
        cust = collect(limit)
        with open(cust_path, "w", encoding="utf-8") as fh:
            for row in cust:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"客户名单 {len(cust)} 家", flush=True)

    existing = load_sources(ROOT / "sources")
    have = {re.sub(r"(股份有限公司|有限公司|集团|控股|公司)$", "", s.company) for s in existing}
    todo = [c for c in cust if re.sub(r"(股份有限公司|有限公司|集团|控股|公司)$", "", c["name"]) not in have]
    print(f"未入库客户 {len(todo)} 家，开始探租户", flush=True)

    out = WORK / "beisen_customer_hits.jsonl"
    t0 = time.time()
    hits = 0
    with open(out, "w", encoding="utf-8") as fh, ThreadPoolExecutor(6) as ex:
        for i, rec in enumerate(ex.map(probe_one, todo), 1):
            if rec:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                hits += 1
                print(f"[{i}/{len(todo)}] {rec['company']:<16} {rec['tenant']:<18} {rec['count']:>4}  {rec['title'][:28]}", flush=True)
            if i % 50 == 0:
                print(f"... {i}/{len(todo)} {time.time() - t0:.0f}s 命中 {hits}", flush=True)
    print(f"完成：命中 {hits}，用时 {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
