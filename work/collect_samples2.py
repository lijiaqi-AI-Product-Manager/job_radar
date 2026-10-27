"""按最终 companies.jsonl 采集脱敏样本（每租户 3 份，单份 ≤50KB）。

适配三种 ATS：
  beisen        列表第 1 页 JSON + 末页 JSON + 详情页 HTML
  beisen_legacy 列表第 1 页 HTML + 详情页 HTML + meta
  hotjob        列表 JSON + 详情 JSON + meta
"""

import json
import re
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
SAMPLES = ROOT / "docs" / "recon" / "samples"
UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
TOKENY = re.compile(r'"(token|cookie|sessionid|csrf|authorization)"\s*:\s*"[^"]*"', re.I)
CAP = 46 * 1024


def scrub(text: str, cap: bool = True) -> str:
    text = EMAIL.sub("<email>", text)
    text = PHONE.sub("<phone>", text)
    text = TOKENY.sub(lambda m: f'"{m.group(1)}":"<redacted>"', text)
    return text[:CAP] if cap else text


def dump(obj) -> str:
    # 先紧凑序列化，再按字节截断：缩进会把样本撑到 50KB 以上
    return scrub(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


def main() -> None:
    rows = [json.loads(line) for line in
            (WORK / "companies.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    SAMPLES.mkdir(parents=True, exist_ok=True)
    n = 0
    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json,text/html"},
                      timeout=25, follow_redirects=True) as c:
        for r in rows:
            t, ats = r["tenant"], r["ats"]
            d = SAMPLES / t
            d.mkdir(parents=True, exist_ok=True)
            meta = {"company": r["company"], "tenant": t, "ats": ats,
                    "url": r["careers_url"], "count": r["jobs_live"],
                    "jd_rate": r["jd_rate"], "fetched_at": r["verified_at"]}
            (d / "meta.json").write_text(dump(meta), encoding="utf-8")
            try:
                if ats == "beisen":
                    api = f"https://{t}.zhiye.com/api/Jobad/GetJobAdPageList"
                    body = {"PageIndex": 0, "PageSize": 10, "KeyWords": "",
                            "SpecialType": 0, "PortalId": ""}
                    p1 = c.post(api, json=body).json()
                    (d / "list_p1.json").write_text(dump(p1), encoding="utf-8")
                    total = p1.get("Count") or 0
                    last = max(0, (total - 1) // 10)
                    if last:
                        time.sleep(1.0)
                        body["PageIndex"] = last
                        (d / "list_last.json").write_text(
                            dump(c.post(api, json=body).json()), encoding="utf-8")
                    items = p1.get("Data") or []
                    if items:
                        jid = items[0].get("Id")
                        time.sleep(1.0)
                        (d / "detail.html").write_text(
                            scrub(c.get(f"https://{t}.zhiye.com/social/detail?jobAdId={jid}").text),
                            encoding="utf-8")
                elif ats == "beisen_legacy":
                    html = c.get(f"https://{t}.zhiye.com/campus", params={"PageIndex": 1, "k": ""})
                    (d / "list_p1.html").write_text(scrub(html.text), encoding="utf-8")
                    m = re.search(r"/job_show\?jobId=(\d+)", html.text) or re.search(
                        r'href="/zpdetail/(\d+)', html.text)
                    if m:
                        time.sleep(1.0)
                        (d / "detail.html").write_text(
                            scrub(c.get(f"https://{t}.zhiye.com/job_show?jobId={m.group(1)}").text),
                            encoding="utf-8")
                else:
                    api = (f"https://{r['host']}/wecruit/positionInfo/listPosition/{t}")
                    q = {"iSaJAx": "isAjax", "request_locale": "zh_CN", "isFrompb": "true",
                         "recruitType": "1", "pageSize": "10", "currentPage": "1"}
                    p1 = c.get(api, params=q).json()
                    (d / "list_p1.json").write_text(dump(p1), encoding="utf-8")
                    items = ((p1.get("data") or {}).get("pageForm") or {}).get("pageData") or []
                    if items:
                        time.sleep(1.0)
                        det = c.get(f"https://{r['host']}/wecruit/positionInfo/listPositionDetail/{t}",
                                    params={**q, "postId": items[0].get("postId")}).json()
                        (d / "detail.json").write_text(dump(det), encoding="utf-8")
                n += 1
                if n % 20 == 0:
                    print(f"{n}/{len(rows)}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"ERR {r['company']} {type(e).__name__}", flush=True)
            time.sleep(1.0)
    sizes = [p.stat().st_size for p in SAMPLES.rglob("*") if p.is_file()]
    files = [p for p in SAMPLES.rglob("*") if p.is_file()]
    over = [p for p in files if p.stat().st_size > 50 * 1024]
    print(f"目录 {len(list(SAMPLES.iterdir()))} 个，文件 {len(files)} 份，最大 {max(sizes)} 字节，超 50KB {len(over)} 份")


if __name__ == "__main__":
    main()
