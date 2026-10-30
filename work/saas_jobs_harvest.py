"""「云就业」SaaS 学校站职位列表全量采集。

接口：GET https://<school>.bysjy.com.cn/module/getjobs
  params: start(1-based), count(<=100), k(关键词, 可空)
  返回 {"code":1,"data":[{publish_id, company_name, job_name, city_name, publish_time,
        end_time, salary, degree_require, is_practice, ...}]}

产物 work/saas_jobs.jsonl
用法：python work/saas_jobs_harvest.py --max-pages 5 --count 100 --workers 8
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
OUT = ROOT / "work" / "saas_jobs.jsonl"
PROGRESS = ROOT / "work" / "saas_jobs_progress.txt"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/plain, */*",
}
_lock = threading.Lock()


def _get_json(client: httpx.Client, host: str, params: dict, count: int) -> dict | None:
    """带重试的列表请求：换小页长、再试一次，最后才放弃。

    2026-10-30 实测：有一批学校站 count=100 会 ReadTimeout，但 count=10 正常
    （jzsz.bysjy.com.cn 就是），一轮不回退的采集会把它们整站漏掉。
    """
    url = f"https://{host}/module/getjobs"
    for attempt, cnt in enumerate((count, min(count, 50), min(count, 10))):
        try:
            r = client.get(url, params={**params, "count": cnt}, headers={"Referer": f"https://{host}/module/careers"})
            if r.status_code != 200:
                continue
            d = r.json()
            if isinstance(d, dict) and int(d.get("code") or 0) == 1:
                return d
        except Exception:  # noqa: BLE001
            if attempt >= 2:
                return None
    return None


def fetch_host(client: httpx.Client, host: str, count: int, max_pages: int) -> list[dict]:
    out: list[dict] = []
    for page in range(max_pages):
        params = {"start": page * count + 1, "count": count}
        d = _get_json(client, host, params, count)
        if not d:
            break
        items = d.get("data") or []
        if not isinstance(items, list) or not items:
            break
            break
        items = d.get("data") or []
        if not isinstance(items, list) or not items:
            break
        for it in items:
            if not isinstance(it, dict) or not it.get("publish_id"):
                continue
            out.append(
                {
                    "school_host": host,
                    "publish_id": it.get("publish_id"),
                    "company": it.get("company_name"),
                    "title": it.get("job_name"),
                    "city": it.get("city_name"),
                    "publish_time": it.get("publish_time"),
                    "end_time": it.get("end_time"),
                    "salary": it.get("salary"),
                    "degree": it.get("degree_require"),
                    "major": it.get("about_major"),
                    "practice": it.get("is_practice"),
                    "category": it.get("category"),
                    "industry": it.get("industry_category"),
                }
            )
        if len(items) < count:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--max-pages", type=int, default=5)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--only-idle", action="store_true",
                    help="只补采上一轮 0 条的主机（读 work/saas_jobs.jsonl 判断）")
    args = ap.parse_args()

    raw = json.loads(HOSTS.read_text(encoding="utf-8"))
    hosts: list[str] = []
    for value in raw.values() if isinstance(raw, dict) else [raw]:
        hosts.extend(value if isinstance(value, list) else [])
    seen: set[str] = set()
    hosts = [h for h in hosts if not (h in seen or seen.add(h))]
    if args.only_idle and OUT.exists():
        active = {json.loads(line)["school_host"] for line in OUT.read_text(encoding="utf-8").splitlines() if line.strip()}
        hosts = [h for h in hosts if h not in active]
        print(f"idle hosts: {len(hosts)}")
    if args.limit:
        hosts = hosts[: args.limit]
    print(f"hosts={len(hosts)}", flush=True)

    mode = "a" if args.only_idle else "w"
    done = 0
    with httpx.Client(timeout=25.0, headers=HEADERS, follow_redirects=True, verify=False) as client, \
            ThreadPoolExecutor(max_workers=args.workers) as pool, \
            OUT.open(mode, encoding="utf-8") as fh:
        for rows in pool.map(lambda h: fetch_host(client, h, args.count, args.max_pages), hosts):
            done += 1
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            if done % 25 == 0:
                fh.flush()
                PROGRESS.write_text(f"{done}/{len(hosts)}", encoding="utf-8")
                print(f"{done}/{len(hosts)}", flush=True)
    PROGRESS.write_text(f"{done}/{len(hosts)} done", encoding="utf-8")
    print("done", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
