"""subdomain.center 每次只返回 500 条且会轮换，多打几轮取并集，扩出更多学校子域。

用法：python work/saas_expand_hosts.py --rounds 8
结果合并进 work/saas_hosts.json（保留原结构：域名 -> 子域列表）。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "work" / "saas_hosts.json"
DOMAINS = ["bysjy.com.cn", "goworkla.cn", "jiuye.com", "yunjiuye.com"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--gap", type=float, default=1.0)
    args = ap.parse_args()

    data = json.loads(PATH.read_text(encoding="utf-8"))
    before = {d: len(v) for d, v in data.items()}
    with httpx.Client(timeout=60.0, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, verify=False) as c:
        for i in range(args.rounds):
            for d in DOMAINS:
                try:
                    r = c.get("https://api.subdomain.center/", params={"domain": d})
                    hosts = r.json() if r.status_code == 200 else []
                except Exception:  # noqa: BLE001
                    continue
                if not isinstance(hosts, list):
                    continue
                cur = set(data.get(d) or [])
                new = [h for h in hosts if h not in cur]
                data[d] = sorted(cur | set(hosts))
                print(f"round {i + 1} {d}: +{len(new)} -> {len(data[d])}", flush=True)
                time.sleep(args.gap)
            PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    after = {d: len(v) for d, v in data.items()}
    total = sum(after.values())
    print("before", before, "after", after, "total", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
