"""枚举「云就业 / 工作啦」这类高校就业 SaaS 平台下的学校站点，并探测其公开列表。

`api.subdomain.center/?domain=<域>` 免费返回真实子域（前面枚举 zhiye/hotjob 用的同一个源）。
拿到子域后逐个探活，找「招聘公告列表」是否服务端渲染。

输出 work/saas_hosts.json 与 work/saas_probe.txt
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT_HOSTS = ROOT / "work" / "saas_hosts.json"
OUT_PROBE = ROOT / "work" / "saas_probe.txt"

DOMAINS = ["bysjy.com.cn", "goworkla.cn", "yunjiuye.com", "jiuye.com"]
H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def fetch_hosts(domain: str) -> list[str]:
    try:
        r = httpx.get("https://api.subdomain.center/", params={"domain": domain}, timeout=60.0,
                      headers={"User-Agent": H["User-Agent"]}, follow_redirects=True)
        data = r.json()
        return [h for h in data if isinstance(h, str)] if isinstance(data, list) else []
    except Exception as exc:  # noqa: BLE001
        print(f"{domain}: {type(exc).__name__}: {exc}", flush=True)
        return []


def probe(host: str) -> dict:
    rec: dict = {"host": host}
    url = f"https://{host}/"
    try:
        r = httpx.get(url, timeout=15.0, headers=H, follow_redirects=True, verify=False)
        body = r.text
        rec["status"] = r.status_code
        rec["bytes"] = len(body)
        rec["title"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", (
            re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I) or [None, ""])[1])).strip()[:60]
        rec["n_campus_links"] = len(re.findall(r"/campus/view/|/detail/|/jobfair", body))
        rec["n_job_words"] = len(re.findall(r"招聘", body))
    except Exception as exc:  # noqa: BLE001
        rec["error"] = type(exc).__name__
    return rec


def main() -> int:
    all_hosts: dict[str, list[str]] = {}
    for d in DOMAINS:
        hosts = fetch_hosts(d)
        all_hosts[d] = hosts
        print(f"{d}: {len(hosts)} hosts", flush=True)
        time.sleep(1.0)
    OUT_HOSTS.write_text(json.dumps(all_hosts, ensure_ascii=False, indent=1), encoding="utf-8")

    flat = sorted({h for hs in all_hosts.values() for h in hs if h.endswith((".cn", ".com"))})
    print(f"uniq hosts={len(flat)}", flush=True)
    rows = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for rec in pool.map(probe, flat[:400]):
            rows.append(rec)
    rows.sort(key=lambda r: (-r.get("n_campus_links", 0), r.get("host", "")))
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    OUT_PROBE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok = [r for r in rows if r.get("n_campus_links", 0) >= 5]
    print(f"probed={len(rows)} with_campus_links={len(ok)}")
    for r in ok[:15]:
        print(r["host"], r.get("n_campus_links"), r.get("title", "")[:30])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
