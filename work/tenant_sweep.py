"""对候选公司批量做「平台租户穷举」：北森 zhiye / 大易 hotjob / 北森旧版。

与 work/probe_beisen.py 的区别：
  - slug 组合更穷（品牌、拼音、拼音+hr/1/2、拼音首字母、品牌+hr）
  - 同时测三套平台，命中任一即停（省请求）
  - 全程串行 + 1 rps，同一 host 不并发（红线）

输入：work/candidates_clean.tsv（name\tsector\tbrand）
输出：work/tenants_found.jsonl
"""

import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")

try:
    from pypinyin import Style, lazy_pinyin
except ImportError:  # pragma: no cover
    print("需要 pypinyin：pip3 install pypinyin")
    raise SystemExit(1) from None

HOST_LAST = {}
MIN_GAP = 1.0


def throttle(host: str) -> None:
    last = HOST_LAST.get(host)
    if last is not None:
        wait = last + MIN_GAP - time.time()
        if wait > 0:
            time.sleep(wait)
    HOST_LAST[host] = time.time()


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
    add(py + "2")
    ini = "".join(lazy_pinyin(name, style=Style.FIRST_LETTER))
    add(ini)
    add(ini + "hr")
    return out[:8]


def core(n: str) -> str:
    for cut in ("（", "(", "）", ")", "集团", "股份", "控股", "有限公司", "中国区", "中国"):
        n = n.replace(cut, "")
    return n.strip()


def named(company: str, blob: str) -> bool:
    c = core(company)
    if not c:
        return False
    return c in blob or (len(c) >= 2 and c[:2] in blob)


def try_beisen(c: httpx.Client, slug: str, company: str) -> dict | None:
    host = f"{slug}.zhiye.com"
    throttle(host)
    try:
        p = c.get(f"https://{host}/")
    except Exception:  # noqa: BLE001
        return None
    if p.status_code != 200:
        return None
    m = re.search(r"<title>(.*?)</title>", p.text, re.S)
    title = m.group(1).strip()[:80] if m else ""
    if "NotFound" in title or "404" in title:
        return None
    throttle(host)
    try:
        d = c.post(f"https://{host}/api/Jobad/GetJobAdPageList",
                   json={"PageIndex": 0, "PageSize": 30, "KeyWords": "",
                         "SpecialType": 0, "PortalId": ""}).json()
    except Exception:  # noqa: BLE001
        return None
    if d.get("Code") != 200:
        return None
    jobs = [x.get("JobAdName", "") for x in (d.get("Data") or [])]
    return {"ats": "beisen", "tenant": slug, "host": host, "title": title,
            "count": d.get("Count"), "name_match": named(company, title + " " + " ".join(jobs)),
            "jobs": jobs[:3]}


def try_hotjob(c: httpx.Client, slug: str, company: str) -> dict | None:
    host = f"{slug}.hotjob.cn"
    throttle(host)
    try:
        r = c.post(f"https://{host}/wecruit/common/getSLD", data={"sld": host},
                   headers={"Content-Type": "application/x-www-form-urlencoded"})
        if r.status_code != 200:
            return None
        d = r.json()
    except Exception:  # noqa: BLE001
        return None
    ld = (d.get("data") or {}).get("linkData") or {}
    link, title = ld.get("link") or "", ld.get("title") or ""
    m = re.search(r"/(SU[0-9a-f]{20,})/", link)
    if not m:
        return None
    tenant = m.group(1)
    throttle(host)
    try:
        lst = c.get(f"https://{host}/wecruit/positionInfo/listPosition/{tenant}",
                    params={"iSaJAx": "isAjax", "request_locale": "zh_CN", "isFrompb": "true",
                            "recruitType": "1", "pageSize": "50", "currentPage": "1"}).json()
    except Exception:  # noqa: BLE001
        return None
    form = (lst.get("data") or {}).get("pageForm") or {}
    items = form.get("pageData") or []
    return {"ats": "hotjob", "tenant": tenant, "host": host, "title": title,
            "count": form.get("total") or len(items),
            "name_match": named(company, title), "jobs": []}


def main() -> None:
    rows = []
    for line in (WORK / "candidates_clean.tsv").read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            rows.append((parts[0], parts[1], parts[2]))
    done = set()
    for f in ("probe_all.jsonl", "ats_findings.jsonl"):
        for line in (WORK / f).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("matched") or r.get("ats"):
                    done.add(r["company"])
    todo = [r for r in rows if r[0] not in done]
    print(f"候选 {len(rows)}，已确认 ATS {len(done)}，本轮探测 {len(todo)}", flush=True)

    out = []
    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json,text/html"},
                      timeout=12, follow_redirects=True) as c:
        for i, (name, sector, brand) in enumerate(todo, 1):
            hit = None
            tried = []
            for s in slugs(name, brand):
                tried.append(s)
                hit = try_beisen(c, s, name)
                if hit:
                    break
                hit = try_hotjob(c, s, name)
                if hit:
                    break
            if hit:
                out.append({"company": name, "sector": sector, "brand": brand,
                            "tried": tried, **hit})
                flag = "OK" if hit["name_match"] else "??"
                print(f"[{i}] {flag} {name:<14}{hit['ats']:<8}{hit['tenant']:<24}"
                      f"{hit['count']:>6}  {hit['title'][:26]}", flush=True)
            if i % 50 == 0:
                print(f"... {i}/{len(todo)}  命中 {len(out)}", flush=True)
                (WORK / "tenants_found.jsonl").write_text(
                    "\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n",
                    encoding="utf-8")
    (WORK / "tenants_found.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n", encoding="utf-8")
    print(f"完成：命中 {len(out)} / 探测 {len(todo)}")


if __name__ == "__main__":
    sys.exit(main())
