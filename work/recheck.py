"""对 fast_sweep 命中里「站点标题没写公司名」的做二次核对：用岗位列表里的 company 字段。

hotjob 的岗位项有 `company`（如「柳州五菱汽车工业有限公司」），北森的岗位项没有，
但北森的 `Count` 与岗位名常带品牌词，所以：先看岗位 company，再看岗位名。

输入 work/fast_hits.jsonl → 输出 work/recheck.jsonl
"""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")

MANUAL = {
    "叮咚买菜": ("ddmc", "上海壹佰米网络科技有限公司（叮咚买菜）已被公开资料确认为同一主体"),
    "宁德新能源": ("atl", "ATL 即新能源科技（宁德新能源科技），站点标题「ATL招聘官网」"),
}


def core(n: str) -> str:
    for cut in ("（", "(", "）", ")", "集团", "股份", "控股", "有限公司", "中国区", "中国"):
        n = n.replace(cut, "")
    return n.strip()


def named(company: str, blob: str) -> bool:
    c = core(company)
    return bool(c) and (c in blob or (len(c) >= 2 and c[:2] in blob))


def check(row: dict) -> dict:
    out = dict(row)
    name = row["company"]
    if name in MANUAL:
        out.update(recheck="manual", recheck_note=MANUAL[name][1], name_match=True)
        return out
    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"},
                      timeout=20, follow_redirects=True) as c:
        blob = row.get("title") or ""
        if row["ats"] == "hotjob":
            for code in ("1", "2"):
                try:
                    d = c.get(f"https://{row['host']}/wecruit/positionInfo/listPosition/{row['tenant']}",
                              params={"iSaJAx": "isAjax", "request_locale": "zh_CN",
                                      "isFrompb": "true", "recruitType": code,
                                      "pageSize": "50", "currentPage": "1"}).json()
                except Exception:  # noqa: BLE001
                    continue
                items = ((d.get("data") or {}).get("pageForm") or {}).get("pageData") or []
                blob += " " + " ".join((x.get("company") or "") + " " + (x.get("postName") or "")
                                       for x in items)
                if named(name, blob):
                    break
        elif row["ats"] == "beisen":
            try:
                d = c.post(f"https://{row['host']}/api/Jobad/GetJobAdPageList",
                           json={"PageIndex": 0, "PageSize": 100, "KeyWords": "",
                                 "SpecialType": 0, "PortalId": ""}).json()
                blob += " " + " ".join(x.get("JobAdName", "") + " " + str(x.get("Org") or "")
                                       for x in (d.get("Data") or []))
            except Exception:  # noqa: BLE001
                pass
        out["recheck"] = "blob"
        out["name_match"] = named(name, blob)
    return out


def main() -> None:
    rows = [json.loads(line) for line in
            (WORK / "fast_hits.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    todo = [r for r in rows if not r.get("name_match")]
    print(f"二次核对 {len(todo)} 条", flush=True)
    with ThreadPoolExecutor(max_workers=5) as ex:
        res = list(ex.map(check, todo))
    (WORK / "recheck.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in res) + "\n", encoding="utf-8")
    for r in res:
        print(f"{'OK' if r['name_match'] else 'XX'} {r['company']:<12}{r['ats']:<12}"
              f"{r['tenant']:<24}{r['count']:>6}  {r.get('title', '')[:24]}")
    print(f"改判通过 {sum(1 for r in res if r['name_match'])} / {len(res)}")


if __name__ == "__main__":
    main()
