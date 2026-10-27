"""对 ATS 指纹扫描里的 hotjob 命中做租户级验证（v2）。

v1 失败原因：`{slug}.hotjob.cn` 根页是前端 JS 跳转壳，tenant 藏在
`POST /wecruit/common/getSLD` 的 `linkData.link` 里。这里先解析出 tenant 与站点标题，
再打列表接口确认岗位数，并对标题做同名核对。
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


def resolve(client: httpx.Client, host: str) -> dict:
    """根页 getSLD -> 真实门户链接 + 站点标题 + tenant。"""
    r = client.post(f"https://{host}/wecruit/common/getSLD", data={"sld": host},
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
    if r.status_code != 200:
        return {"err": f"getSLD:{r.status_code}"}
    try:
        d = r.json()
    except Exception:  # noqa: BLE001
        return {"err": "getSLD-json"}
    link_data = (d.get("data") or {}).get("linkData") or {}
    link = link_data.get("link") or ""
    title = link_data.get("title") or ""
    m = re.search(r"/(SU[0-9a-f]{20,})/", link)
    return {"link": link, "title": title, "tenant": m.group(1) if m else None}


def list_jobs(client: httpx.Client, host: str, tenant: str, code: str) -> dict | None:
    api = f"https://{host}/wecruit/positionInfo/listPosition/{tenant}"
    r = client.get(api, params={"iSaJAx": "isAjax", "request_locale": "zh_CN", "isFrompb": "true",
                                "recruitType": code, "pageSize": "50", "currentPage": "1"},
                   headers={"Referer": f"https://{host}/{tenant}/pb/social.html"})
    if r.status_code != 200:
        return None
    try:
        d = r.json()
    except Exception:  # noqa: BLE001
        return None
    form = (d.get("data") or {}).get("pageForm") or {}
    return {"total": form.get("total") or form.get("totalCount") or len(form.get("pageData") or []),
            "items": form.get("pageData") or []}


def run(row: dict) -> dict:
    company, url = row["company"], row.get("careers_url") or ""
    host = re.sub(r"^https?://", "", url).split("/")[0]
    out = {"company": company, "sector": row.get("sector"), "brand": row.get("brand"),
           "host": host, "url": url}
    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"},
                      timeout=20, follow_redirects=True) as c:
        try:
            info = resolve(c, host)
        except Exception as e:  # noqa: BLE001
            return {**out, "ok": False, "err": type(e).__name__}
        if not info.get("tenant"):
            return {**out, "ok": False, "title": info.get("title"), "link": info.get("link"),
                    "err": info.get("err") or "no-tenant"}
        out.update(tenant=info["tenant"], title=info["title"], link=info["link"])
        best = None
        for code, name in (("1", "campus"), ("2", "social")):
            time.sleep(1.0)
            res = list_jobs(c, host, info["tenant"], code)
            if res and (best is None or res["total"] > best[1]["total"]):
                best = (name, res)
        if best is None:
            return {**out, "ok": False, "err": "list-empty"}
        rtype, res = best
        jobs = [x.get("postName") or x.get("positionName") or "" for x in res["items"][:50]]
        # 岗位名不带公司名很常见，所以同名核对只认站点标题
        blob = info["title"] + " " + " ".join(jobs)
        return {**out, "ok": res["total"] > 0, "recruit_type": rtype, "count": res["total"],
                "name_match": match(company, blob), "title_match": match(company, info["title"] or ""),
                "jobs": jobs[:5]}


def main():
    rows = [json.loads(line) for line in
            (WORK / "ats_findings.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    cand = [r for r in rows if r.get("ats") == "hotjob"]
    print(f"待验证 hotjob {len(cand)} 家", flush=True)
    res = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        for i, r in enumerate(ex.map(run, cand), 1):
            res.append(r)
            if i % 10 == 0:
                print(f"{i}/{len(cand)}", flush=True)
    (WORK / "hotjob_verified.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in res) + "\n", encoding="utf-8")
    ok = [r for r in res if r.get("ok") and r.get("name_match")]
    bad = [r for r in res if r.get("ok") and not r.get("name_match")]
    print(f"通过 {len(ok)} / 丢弃 {len(bad)} / 失败 {len(res) - len(ok) - len(bad)}")
    for r in ok:
        print(f"  OK {r['company']:<12}{r.get('tenant',''):<26}{r['count']:>5}  {r.get('title','')[:28]}")
    for b in bad:
        print(f"  XX {b['company']:<12}{b.get('host','')[:26]:<28}{str(b.get('count')):>5}  {b.get('title','')[:28]}")


if __name__ == "__main__":
    main()
