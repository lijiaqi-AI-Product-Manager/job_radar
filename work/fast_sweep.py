"""fast_sweep：候选公司 → 平台租户的快速穷举（北森新版 / 大易 / 北森旧版）。

提速的关键观察：
  - 不存在的北森租户根页只有 1228 字节且 title 就是 "Not Found"，先做体积/标题剪枝
  - 剪枝可放行后再打列表接口，两次请求都在同一 host 内串行，1 rps

并发边界（红线）：**不同 host 可以并行，同一 host 永不并行**。
  - 北森版：每家公司的每个 slug 都是不同 host（a.zhiye.com / b.zhiye.com ...）
  - 大易版：所有租户共用一个 host（xxx.hotjob.cn 不同主机名，也是独立 host）
  - 因此用「按 host 分组」的调度：globally 10 个 worker，host 级互斥。

输入：candidates.tsv（name\tsector\tbrand）
输出：work/fast_hits.jsonl
"""

import json
import re
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")
WORKERS = 10
MIN_GAP = 1.0

try:
    from pypinyin import Style, lazy_pinyin
except ImportError:  # pragma: no cover
    raise SystemExit("需要 pypinyin：pip3 install pypinyin") from None

_lock = threading.Lock()
_host_last: dict[str, float] = {}


def throttle(host: str) -> None:
    while True:
        with _lock:
            now = time.time()
            last = _host_last.get(host, 0.0)
            if now - last >= MIN_GAP:
                _host_last[host] = now
                return
            wait = last + MIN_GAP - now
        time.sleep(wait)


def slugs(name: str, brand: str) -> list[str]:
    out: list[str] = []

    def add(s: str) -> None:
        s = re.sub(r"[^a-z0-9-]", "", s.lower())
        if s and 2 <= len(s) <= 28 and s not in out:
            out.append(s)

    b = re.sub(r"[^A-Za-z0-9]", "", brand or "").lower()
    if b:
        add(b)
        add(b + "hr")
        add(b + "1")
    py = "".join(lazy_pinyin(name, style=Style.NORMAL))
    add(py)
    add(py + "hr")
    add(py + "1")
    ini = "".join(lazy_pinyin(name, style=Style.FIRST_LETTER))
    add(ini)
    return out[:7]


def core(n: str) -> str:
    for cut in ("（", "(", "）", ")", "集团", "股份", "控股", "有限公司", "中国区", "中国"):
        n = n.replace(cut, "")
    return n.strip()


def named(company: str, blob: str) -> bool:
    c = core(company)
    if not c:
        return False
    return c in blob or (len(c) >= 2 and c[:2] in blob)


def probe_beisen(client: httpx.Client, slug: str, company: str) -> dict | None:
    host = f"{slug}.zhiye.com"
    throttle(host)
    try:
        p = client.get(f"https://{host}/")
    except Exception:  # noqa: BLE001
        return None
    if p.status_code != 200 or len(p.text) < 1500:
        return None
    m = re.search(r"<title>(.*?)</title>", p.text, re.S)
    title = m.group(1).strip()[:80] if m else ""
    if not title or "Not Found" in title:
        return None
    throttle(host)
    try:
        d = client.post(f"https://{host}/api/Jobad/GetJobAdPageList",
                        json={"PageIndex": 0, "PageSize": 30, "KeyWords": "",
                              "SpecialType": 0, "PortalId": ""}).json()
    except Exception:  # noqa: BLE001
        return None
    if d.get("Code") != 200 or not d.get("Count"):
        return None
    jobs = [x.get("JobAdName", "") for x in (d.get("Data") or [])]
    return {"ats": "beisen", "tenant": slug, "host": host, "url": f"https://{host}/",
            "title": title, "count": d.get("Count"),
            "name_match": named(company, title + " " + " ".join(jobs)), "jobs": jobs[:3]}


def probe_hotjob(client: httpx.Client, slug: str, company: str) -> dict | None:
    host = f"{slug}.hotjob.cn"
    throttle(host)
    try:
        r = client.post(f"https://{host}/wecruit/common/getSLD", data={"sld": host},
                        headers={"Content-Type": "application/x-www-form-urlencoded"})
        if r.status_code != 200:
            return None
        d = r.json()
    except Exception:  # noqa: BLE001
        return None
    ld = (d.get("data") or {}).get("linkData") or {}
    title = ld.get("title") or ""
    m = re.search(r"/(SU[0-9a-f]{20,})/", ld.get("link") or "")
    if not m:
        return None
    tenant = m.group(1)
    throttle(host)
    try:
        lst = client.get(f"https://{host}/wecruit/positionInfo/listPosition/{tenant}",
                         params={"iSaJAx": "isAjax", "request_locale": "zh_CN", "isFrompb": "true",
                                 "recruitType": "1", "pageSize": "50", "currentPage": "1"}).json()
    except Exception:  # noqa: BLE001
        return None
    form = (lst.get("data") or {}).get("pageForm") or {}
    items = form.get("pageData") or []
    total = form.get("total") or len(items)
    if not total:
        return None
    return {"ats": "hotjob", "tenant": tenant, "host": host,
            "url": f"https://{host}/{tenant}/pb/index.html", "title": title,
            "count": total, "name_match": named(company, title), "jobs": []}


def probe_beisen_legacy(client: httpx.Client, slug: str, company: str) -> dict | None:
    """旧版列表页是服务端渲染的 <tr>，抓一次 /campus 就能判定。"""
    host = f"{slug}.zhiye.com"
    throttle(host)
    try:
        p = client.get(f"https://{host}/campus", params={"PageIndex": 1, "k": ""})
    except Exception:  # noqa: BLE001
        return None
    if p.status_code != 200:
        return None
    ids = set(re.findall(r"/job_show\?jobId=(\d+)", p.text)) | set(
        re.findall(r'href="/zpdetail/(\d+)', p.text))
    if not ids:
        return None
    m = re.search(r"<title>(.*?)</title>", p.text, re.S)
    title = m.group(1).strip()[:80] if m else ""
    pages = re.search(r"当前第\s*\d+\s*/\s*(\d+)\s*页", p.text)
    per = len(ids)
    est = per * int(pages.group(1)) if pages else per
    return {"ats": "beisen_legacy", "tenant": slug, "host": host,
            "url": f"https://{host}/campus", "title": title, "count": est,
            "name_match": named(company, title), "jobs": []}


def work_item(item: tuple[str, str, str]) -> dict | None:
    name, sector, brand = item
    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json,text/html"},
                      timeout=10, follow_redirects=True) as c:
        tried = []
        for s in slugs(name, brand):
            tried.append(s)
            for fn in (probe_beisen, probe_hotjob, probe_beisen_legacy):
                hit = fn(c, s, name)
                if hit:
                    return {"company": name, "sector": sector, "brand": brand,
                            "tried": tried, **hit}
    return None


def main(items: Iterable[tuple[str, str, str]]) -> list[dict]:
    items = list(items)
    print(f"待探测 {len(items)} 家", flush=True)
    hits: list[dict] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, r in enumerate(ex.map(work_item, items), 1):
            if r:
                hits.append(r)
                flag = "OK" if r["name_match"] else "??"
                print(f"[{i}] {flag} {r['company']:<14}{r['ats']:<14}{r['tenant']:<24}"
                      f"{r['count']:>6}  {r['title'][:26]}", flush=True)
            if i % 100 == 0:
                el = time.time() - t0
                print(f"... {i}/{len(items)}  命中 {len(hits)}  {el:.0f}s "
                      f"({i / el * 60:.0f} 家/分)", flush=True)
                (WORK / "fast_hits.jsonl").write_text(
                    "\n".join(json.dumps(x, ensure_ascii=False) for x in hits) + "\n",
                    encoding="utf-8")
    (WORK / "fast_hits.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in hits) + "\n", encoding="utf-8")
    print(f"完成：命中 {len(hits)} / {len(items)}，耗时 {time.time() - t0:.0f}s")
    return hits


if __name__ == "__main__":
    rows = []
    for line in (WORK / "candidates_clean.tsv").read_text(encoding="utf-8").splitlines():
        p = line.split("\t")
        if len(p) >= 3:
            rows.append((p[0], p[1], p[2]))
    main(rows)
