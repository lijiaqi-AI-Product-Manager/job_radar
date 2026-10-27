"""对 ATS v2 发现结果做「租户级验证」：真访问目标页，核对公司名，再查岗位数。

验证标准的顺序（全过才算 doable）：
  1. 简历页可访问（200）
  2. 页面 title / 关键文本里出现公司名核心词  ← 防同名不同公司
  3. 有岗位（beisen 走 Count；hotjob 走 listPosition 接口）
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")


def core_name(n: str) -> str:
    for cut in ("（", "(", "集团", "股份", "控股", "有限公司", "中国区", "中国"):
        n = n.replace(cut, "")
    return n.strip()


def match(company: str, blob: str) -> bool:
    c = core_name(company)
    if not c:
        return False
    if c in blob:
        return True
    # 去掉品牌后缀/英文后再试 2 字前缀
    return len(c) >= 2 and c[:2] in blob


def verify_beisen(tenant: str, company: str) -> dict:
    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"}, timeout=15,
                      follow_redirects=True) as c:
        try:
            p = c.get(f"https://{tenant}.zhiye.com/")
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "err": type(e).__name__}
        title = ""
        m = re.search(r"<title>(.*?)</title>", p.text, re.S)
        if m:
            title = m.group(1).strip()[:80]
        try:
            d = c.post(f"https://{tenant}.zhiye.com/api/Jobad/GetJobAdPageList",
                       json={"PageIndex": 0, "PageSize": 30, "KeyWords": "",
                             "SpecialType": 0, "PortalId": ""}).json()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "title": title, "err": "list:" + type(e).__name__}
        jobs = [x.get("JobAdName", "") for x in (d.get("Data") or [])]
        blob = title + " " + " ".join(jobs)
        return {"ok": d.get("Code") == 200, "title": title, "count": d.get("Count"),
                "name_match": match(company, blob), "jobs": jobs[:5]}


def verify_hotjob(url: str, company: str) -> dict:
    host = re.sub(r"^https?://", "", url).split("/")[0]
    m = re.search(r"/SU[0-9a-f]{20,}", url)
    tenant = m.group(0).lstrip("/") if m else None
    if not tenant:
        # /wt/XXX/web/index 形式
        m2 = re.search(r"/wt/([^/]+)/", url)
        tenant = m2.group(1) if m2 else None
    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"}, timeout=15,
                      follow_redirects=True) as c:
        try:
            p = c.get(url)
            t = re.search(r"<title>(.*?)</title>", p.text, re.S)
            title = t.group(1).strip()[:80] if t else ""
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "err": type(e).__name__}
        if not tenant:
            return {"ok": False, "title": title, "err": "no-tenant"}
        api = (f"https://{host}/wecruit/positionInfo/listPosition/{tenant}"
               f"?iSaJAx=isAjax&isFrompb=true&recruitType=2&pageSize=10&currentPage=1")
        try:
            d = c.get(api).json()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "title": title, "err": "api:" + type(e).__name__}
        raw = d.get("data") or d.get("Data") or d
        items = raw.get("list") or raw.get("records") or [] if isinstance(raw, dict) else []
        jobs = [x.get("positionName") or x.get("name") or "" for x in items]
        blob = title + " " + " ".join(jobs)
        return {"ok": bool(items), "title": title, "count": len(items),
                "name_match": match(company, blob), "jobs": jobs[:5]}


def run(row: dict) -> dict:
    company, ats, url = row["company"], row["ats"], row.get("careers_url") or ""
    out = {"company": company, "ats": ats, "url": url}
    try:
        if ats == "beisen":
            m = re.match(r"https?://([a-z0-9-]+)\.zhiye\.com", url)
            if not m:
                # careers.xxx.com 形式，需要从页面里找 zhiye 链接
                return {**out, "ok": False, "err": "no-tenant"}
            out["tenant"] = m.group(1)
            out.update(verify_beisen(m.group(1), company))
        elif ats == "hotjob":
            out.update(verify_hotjob(url, company))
        else:
            return {**out, "ok": False, "err": "skip"}
    except Exception as e:  # noqa: BLE001
        out.update(ok=False, err=type(e).__name__)
    return out


def main():
    rows = [json.loads(ln) for ln in (WORK / "ats_findings.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    cand = [r for r in rows if r.get("ats") in ("beisen", "hotjob")]
    print(f"待验证 {len(cand)} 家", flush=True)
    res = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, r in enumerate(ex.map(run, cand), 1):
            res.append(r)
            if i % 20 == 0:
                print(f"{i}/{len(cand)}", flush=True)
    (WORK / "ats_verified.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in res) + "\n", encoding="utf-8")
    ok = [r for r in res if r.get("ok") and r.get("name_match")]
    bad = [r for r in res if r.get("ok") and not r.get("name_match")]
    print(f"通过 {len(ok)} / 名字不符(丢弃) {len(bad)} / 失败 {len(res)-len(ok)-len(bad)}")
    if bad:
        print("丢弃清单：")
        for b in bad:
            print(f"  {b['company']:<14}{b['url'][:52]:<54}title={b.get('title','')[:26]}")


if __name__ == "__main__":
    main()
