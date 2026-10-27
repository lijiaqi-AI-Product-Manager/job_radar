"""用门户页 `<title>` 核对 hotjob 租户到底是谁家公司。

为什么必须核：列表接口里 `company` 是「用人部门/子公司」级字段（例如中汽院那个租户里
写的是「中汽院凯瑞检测认证（重庆）有限公司」），不是集团名。搜索结果里 host 和 tenant
配错一次就会把 A 公司的岗位记到 B 公司名下——比没有数据更糟。

做法：GET `https://{host}/{tenant}/` 取门户首页 `<title>`；自定义域名（`longi.hotjob.cn`）
的域名本身也是证据，一并留着给人工/规则判定。
同一 host 的多租户串行、间隔 1.05s，符合「每主机 ≤1 rps」。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import USER_AGENT  # noqa: E402

TITLE = re.compile(r"<title>(.*?)</title>", re.I | re.S)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    recs = []
    for ln in Path(args.src).read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        if d.get("count"):
            recs.append(d)
    recs.sort(key=lambda d: d["host"])

    outp = Path(args.out)
    done: set[str] = set()
    if outp.exists():
        for ln in outp.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(ln)["tenant"])
            except Exception:  # noqa: BLE001
                pass

    last_host: dict[str, float] = {}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20.0,
                      follow_redirects=True) as cli, outp.open("a", encoding="utf-8") as f:
        for d in recs:
            if d["tenant"] in done:
                continue
            h = d["host"]
            gap = time.time() - last_host.get(h, 0.0)
            if gap < 1.05:
                time.sleep(1.05 - gap)
            title = ""
            # `/{tenant}/` 是 404（那不是合法门户路径）；能出标题的是校园门户页和自定义域名的根
            for path in (f"/{d['tenant']}/pb/school.html", f"/{d['tenant']}/social.html", "/"):
                try:
                    r = cli.get(f"https://{h}{path}")
                    m = TITLE.search(r.text or "")
                    if m and m.group(1).strip() not in ("405", "404 Not Found"):
                        title = re.sub(r"\s+", " ", m.group(1)).strip()[:60]
                        break
                except Exception:  # noqa: BLE001
                    pass
                last_host[h] = time.time()
            last_host[h] = time.time()
            rec = {**d, "title": title}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{h[:28]:28s} {d['tenant']} {d['count']:5d}  {title}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
