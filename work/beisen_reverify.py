"""对 beisen 候选做深度解析：根页可能是 JS 跳转壳，真实租户在其跳转目标或页面脚本里。

规则：
  1. GET 首页（follow_redirects），记录最终 URL —— 若域名/路径里的 tenant 变了就用新的
  2. 从 HTML 里抓 `xxx.zhiye.com` 字面量（跳转壳常见）
  3. 打列表接口，Count 为准；同名核对用站点 title
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")


def core_name(n: str) -> str:
    for cut in ("（", "(", "）", ")", "集团", "股份", "控股", "有限公司", "中国区", "中国"):
        n = n.replace(cut, "")
    return n.strip()


def match(company: str, blob: str) -> bool:
    c = core_name(company)
    if not c:
        return False
    if c in blob:
        return True
    return len(c) >= 2 and c[:2] in blob


def list_count(client: httpx.Client, tenant: str) -> dict | None:
    try:
        d = client.post(f"https://{tenant}.zhiye.com/api/Jobad/GetJobAdPageList",
                        json={"PageIndex": 0, "PageSize": 50, "KeyWords": "",
                              "SpecialType": 0, "PortalId": ""}).json()
    except Exception:  # noqa: BLE001
        return None
    if d.get("Code") != 200:
        return None
    items = d.get("Data") or []
    return {"count": d.get("Count"), "items": items}


def run(row: dict) -> dict:
    company = row["company"]
    url = row.get("careers_url") or ""
    m = re.match(r"https?://([a-z0-9-]+)\.zhiye\.com", url)
    if not m:
        return {"company": company, "ok": False, "err": "not-zhiye"}
    tenant = m.group(1)
    out = {"company": company, "sector": row.get("sector"), "brand": row.get("brand"),
           "url": url, "tenant": tenant}
    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json,text/html"},
                      timeout=20, follow_redirects=True) as c:
        try:
            p = c.get(url)
        except Exception as e:  # noqa: BLE001
            return {**out, "ok": False, "err": type(e).__name__}
        title = ""
        t = re.search(r"<title>(.*?)</title>", p.text, re.S)
        if t:
            title = t.group(1).strip()[:80]
        out["title"] = title
        out["final_url"] = str(p.url)[:120]

        tenants = [tenant]
        # 跳转落在别的租户 / 页面里写死了真实租户
        mt = re.match(r"https?://([a-z0-9-]+)\.zhiye\.com", str(p.url))
        if mt and mt.group(1) != tenant:
            tenants.insert(0, mt.group(1))
        for cand in re.findall(r"https?://([a-z0-9-]+)\.zhiye\.com", p.text)[:5]:
            if cand not in tenants:
                tenants.append(cand)

        for cand in tenants[:3]:
            time.sleep(1.0)
            res = list_count(c, cand)
            if res and res["count"]:
                jobs = [x.get("JobAdName", "") for x in res["items"][:50]]
                blob = title + " " + " ".join(jobs)
                return {**out, "ok": True, "tenant": cand, "count": res["count"],
                        "name_match": match(company, blob),
                        "title_match": match(company, title), "jobs": jobs[:5]}
        return {**out, "ok": False, "err": "no-count"}


def main():
    rows = [json.loads(line) for line in
            (WORK / "ats_findings.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    done = set()
    vpath = WORK / "ats_verified.jsonl"
    for line in vpath.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("ok"):
            done.add(r["company"])
    cand = [r for r in rows if r.get("ats") == "beisen" and r["company"] not in done]
    print(f"重验 beisen {len(cand)} 家", flush=True)
    res = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        for i, r in enumerate(ex.map(run, cand), 1):
            res.append(r)
            if i % 10 == 0:
                print(f"{i}/{len(cand)}", flush=True)
    (WORK / "beisen_reverify.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in res) + "\n", encoding="utf-8")
    ok = [r for r in res if r.get("ok")]
    print(f"有岗 {len(ok)}/{len(res)}")
    for r in ok:
        flag = "OK" if r.get("name_match") else "XX"
        print(f"  {flag} {r['company']:<12}{r['tenant']:<20}{r['count']:>6}  {r.get('title','')[:30]}")


if __name__ == "__main__":
    main()
