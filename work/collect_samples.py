"""采集脱敏样本 + 生成 recon md 与 fixtures-plan。

样本要求：列表第1页 / 详情1条 / 末页，每份 ≤50KB，脱敏（去 cookie/token/邮箱/手机号）。
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


def scrub(obj):
    s = json.dumps(obj, ensure_ascii=False, indent=1)
    s = EMAIL.sub("<email>", s)
    s = PHONE.sub("<phone>", s)
    s = TOKENY.sub(lambda m: f'"{m.group(1)}":"<redacted>"', s)
    return s


def main():
    rows = [json.loads(ln) for ln in (WORK / "companies.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    doable = [r for r in rows if r["verdict"] == "doable"]
    SAMPLES.mkdir(parents=True, exist_ok=True)

    detail_rows = []
    with httpx.Client(headers={"User-Agent": UA, "Content-Type": "application/json"}, timeout=25) as c:
        for i, r in enumerate(doable, 1):
            t = r["tenant"]
            d = SAMPLES / t
            d.mkdir(exist_ok=True)
            url = f"https://{t}.zhiye.com/api/Jobad/GetJobAdPageList"
            try:
                p1 = c.post(url, json={"PageIndex": 0, "PageSize": 10, "KeyWords": "", "SpecialType": 0, "PortalId": ""}).json()
            except Exception:  # noqa: BLE001
                continue
            (d / "list_p1.json").write_text(scrub(p1)[: 48 * 1024], encoding="utf-8")
            total = p1.get("Count") or 0
            size = 10
            last_page = max(0, (total - 1) // size) if total else 0
            if last_page > 0:
                time.sleep(1)
                try:
                    pl = c.post(url, json={"PageIndex": last_page, "PageSize": size, "KeyWords": "",
                                           "SpecialType": 0, "PortalId": ""}).json()
                    (d / "list_last.json").write_text(scrub(pl)[: 48 * 1024], encoding="utf-8")
                except Exception:  # noqa: BLE001
                    pass
            # 详情：取第一条的 Id
            first = (p1.get("Data") or [{}])[0]
            jid = first.get("Id")
            if jid:
                time.sleep(1)
                detail_rows.append({"tenant": t, "company": r["name"], "job_id": jid,
                                    "title": first.get("JobAdName"), "total": total})
                try:
                    det = c.get(f"https://{t}.zhiye.com/social/detail?jobAdId={jid}").text
                    det = EMAIL.sub("<email>", PHONE.sub("<phone>", det))
                    (d / "detail.html").write_text(det[: 48 * 1024], encoding="utf-8")
                except Exception:  # noqa: BLE001
                    pass
            if i % 10 == 0:
                print(f"样本 {i}/{len(doable)}", flush=True)
    (WORK / "detail_jobs.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in detail_rows) + "\n", encoding="utf-8")
    print(f"样本完成：{len(doable)} 家，详情记录 {len(detail_rows)} 条")


if __name__ == "__main__":
    main()
