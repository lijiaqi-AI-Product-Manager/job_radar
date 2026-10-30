"""「云就业」SaaS 高校就业网：扫全部学校站的宣讲会/招聘列表，收集公司名。

接口（2026-10-30 实测）：GET https://<school>.bysjy.com.cn/module/getcareers
  params: k/type(inner|outer|mixed)/start_page/start/count/with_counts
  返回 {"code":1,"data":{"list":[{company_name, city_name, meet_day, career_talk_id, ...}],"total":N}}

产物：work/saas_careers.jsonl（每行一个宣讲会条目 + school 字段）
用法：python work/saas_careers_harvest.py --limit 0 --count 100
"""
from __future__ import annotations

import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
HOSTS = ROOT / "work" / "saas_hosts.json"
OUT = ROOT / "work" / "saas_careers.jsonl"
PROGRESS = ROOT / "work" / "saas_careers_progress.txt"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/plain, */*",
}
_lock = threading.Lock()


def fetch_host(client: httpx.Client, host: str, count: int) -> list[dict]:
    params = {
        "k": "", "type": "mixed", "day": "", "panel_name": "", "panel_id": "",
        "professionals": "", "work_city": "", "is_yun_career": "", "status": "", "order": "",
        "start_page": 1, "start": 1, "count": count, "with_counts": 1,
    }
    url = f"https://{host}/module/getcareers"
    try:
        r = client.get(url, params=params, headers={"Referer": f"https://{host}/module/careers"})
        if r.status_code != 200:
            return []
        d = r.json()
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(d, dict) or int(d.get("code") or 0) != 1:
        return []
    data = d.get("data") or {}
    items = data.get("list") or []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append(
            {
                "school_host": host,
                "school_name": it.get("school_name"),
                "company": it.get("company_name"),
                "city": it.get("city_name"),
                "meet_day": it.get("meet_day"),
                "meet_name": it.get("meet_name"),
                "talk_id": it.get("career_talk_id"),
                "company_id": it.get("company_id"),
                "recruit_type": it.get("recruit_type"),
                "industry": it.get("industry_category"),
                "total": data.get("total"),
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 表示全量")
    ap.add_argument("--count", type=int, default=100, help="每站取多少条")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    raw = json.loads(HOSTS.read_text(encoding="utf-8"))
    hosts: list[str] = []
    for value in raw.values() if isinstance(raw, dict) else [raw]:
        hosts.extend(value if isinstance(value, list) else [])
    seen: set[str] = set()
    hosts = [h for h in hosts if not (h in seen or seen.add(h))]
    if args.limit:
        hosts = hosts[: args.limit]
    print(f"hosts={len(hosts)}", flush=True)
    done = 0
    with httpx.Client(timeout=20.0, headers=HEADERS, follow_redirects=True, verify=False) as client, \
            ThreadPoolExecutor(max_workers=args.workers) as pool, \
            OUT.open("w", encoding="utf-8") as fh:
        for rows in pool.map(lambda h: fetch_host(client, h, args.count), hosts):
            done += 1
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            if done % 50 == 0:
                fh.flush()
                PROGRESS.write_text(f"{done}/{len(hosts)}", encoding="utf-8")
                print(f"{done}/{len(hosts)}", flush=True)
    PROGRESS.write_text(f"{done}/{len(hosts)} done", encoding="utf-8")
    print("done", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
