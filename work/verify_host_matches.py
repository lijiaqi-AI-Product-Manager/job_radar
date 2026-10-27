"""验证 host_matches.jsonl 里的候选：门户是否活着、岗位数、标题归属、是否与已有源重复。

输出 work/host_verified.jsonl，字段：company / origin / kind / slug / count / title / dup / ok。
dup 表示「这家公司疑似已经有源」，只做提示，最终由人决定。
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.sources import load_sources  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0"}
CORP_TAIL = re.compile(
    r"(股份有限公司|有限责任公司|有限公司|集团有限公司|集团|控股|中国|股份|总公司|公司|"
    r"（中国）|\(中国\))$"
)
TITLE_NOISE = re.compile(r"[-—|｜(（]?\s*(校园招聘|社会招聘|社会招聘官网|招聘官网|招聘|加入我们|人才招聘).*$")


def core(name: str) -> str:
    name = name.strip()
    for _ in range(2):
        name = CORP_TAIL.sub("", name).strip()
    return name


def page_title(cli: httpx.Client, url: str) -> str:
    try:
        r = cli.get(url)
        if r.status_code != 200:
            return ""
        m = re.search(r"<title>(.*?)</title>", r.text, re.S | re.I)
        if not m:
            return ""
        title = re.sub(r"\s+", " ", m.group(1)).strip()
        title = TITLE_NOISE.sub("", title).strip(" -—|｜")
        return title[:60]
    except Exception:
        return ""


def beisen(cli: httpx.Client, slug: str) -> tuple[int, str]:
    api = f"https://{slug}.zhiye.com/api/Jobad/GetJobAdPageList"
    payload = {
        "PageIndex": 1,
        "PageSize": 10,
        "DisplayFields": ["Category", "LocId", "PostDate", "LocNames"],
        "KeyWords": "",
    }
    try:
        r = cli.post(api, json=payload)
        data = r.json()
        if data.get("Code") == 200:
            return int(data.get("Count") or 0), page_title(cli, f"https://{slug}.zhiye.com/")
    except Exception:
        pass
    return -2, ""


def hotjob(cli: httpx.Client, slug: str) -> tuple[int, str]:
    host = f"{slug}.hotjob.cn"
    try:
        r = cli.get(f"https://{host}/")
        if r.status_code != 200:
            return -2, ""
        title = page_title(cli, f"https://{host}/")
        m = re.search(r"SU[0-9a-f]{20,}", r.text)
        if not m:
            return -1, title
        tenant = m.group(0)
        api = f"https://{host}/wecruit/positionInfo/listPosition/{tenant}"
        params = {
            "iSaJAx": "isAjax",
            "request_locale": "zh_CN",
            "isFrompb": "true",
            "recruitType": "1",
            "pageSize": "10",
            "pageIndex": "1",
        }
        headers = {"X-Requested-With": "XMLHttpRequest", "Referer": f"https://{host}/", **UA}
        j = cli.get(api, params=params, headers=headers)
        data = j.json()
        body = data.get("data") or data
        total = body.get("total") or body.get("Total") or body.get("count")
        if total is None:
            rows = body.get("list") or body.get("rows") or []
            total = len(rows)
        return int(total), title
    except Exception:
        return -2, ""


def main() -> int:
    rows = [json.loads(line) for line in (ROOT / "work" / "host_matches.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    existing = [core(s.company) for s in load_sources(ROOT / "sources")]
    existing_set = set(existing)

    def job(row: dict) -> dict:
        with httpx.Client(timeout=20, headers=UA, verify=False, follow_redirects=True) as cli:
            count, title = beisen(cli, row["slug"]) if row["kind"] == "beisen" else hotjob(cli, row["slug"])
        name = core(row["company"])
        dup = any(name and other and (name in other or other in name) for other in existing_set if len(other) >= 2)
        return {**row, "count": count, "title": title, "dup": dup}

    with ThreadPoolExecutor(max_workers=8) as ex:
        out = list(ex.map(job, rows))

    path = ROOT / "work" / "host_verified.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
    live = [r for r in out if r["count"] > 0]
    print(f"候选 {len(out)}：活着且有岗 {len(live)}，其中疑似重复 {sum(1 for r in live if r['dup'])}")
    for r in sorted(live, key=lambda r: -r["count"])[:40]:
        flag = "DUP" if r["dup"] else ""
        print(f"  {r['count']:>6}  {r['kind']:<7} {r['slug']:<24} {r['company']} / {r['title']} {flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
