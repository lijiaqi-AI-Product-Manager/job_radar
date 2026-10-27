"""批量验证 hotjob（大易云）租户：从搜索结果里的 `{host}/SUxxxx/...` 里取 host+tenant，直接打列表接口。

为什么需要：`search_ats.py` 只能从搜索结果里看到 `wecruit.hotjob.cn/SU61458d83.../pb/school.html`
这种 URL，host 和 tenant 都在里面，但没有验证过它们是不是真活着、有多少岗、是不是这家公司。
不验证就写进 `sources/hotjob.yaml`，等于把猜测当数据。

红线：每个 host 是独立主机，并行不同 host 不违反「每主机 ≤1 rps」；同一 host 只发 1 次列表请求。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import USER_AGENT  # noqa: E402

URL_RE = re.compile(r"https?://([a-z0-9][a-z0-9.-]*hotjob\.cn)/(SU[0-9a-f]{20,32})", re.I)
LIST = "https://{host}/wecruit/positionInfo/listPosition/{tenant}"


def probe(host: str, tenant: str) -> dict:
    out = {"host": host, "tenant": tenant, "ok": False, "count": 0, "sample": "",
           "with_city": 0, "with_date": 0, "err": ""}
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20.0,
                          follow_redirects=True) as cli:
            r = cli.get(LIST.format(host=host, tenant=tenant),
                        params={"iSaJAx": "isAjax", "request_locale": "zh_CN", "isFrompb": "true",
                                "recruitType": "1", "pageSize": "20", "currentPage": "1"})
            if r.status_code != 200:
                out["err"] = f"http{r.status_code}"
                return out
            try:
                d = r.json()
            except ValueError:
                out["err"] = "notjson"
                return out
            # 大易云外层包一层 {"status":..., "data":{"pageResult":{...}}}
            body = d.get("data") if isinstance(d.get("data"), dict) else d
            # 实测外层是 {"data": {"pageForm": {"totalPage":18, "pageSize":15, "pageData":[...]}}}
            pr = body.get("pageResult") or body.get("pageForm") or body
            items = pr.get("pageData") or pr.get("list") or pr.get("data") or []
            if not isinstance(items, list):
                items = []
            out["ok"] = True
            out["count"] = int(pr.get("total") or pr.get("totalCount") or 0) or (
                int(pr.get("totalPage") or 0) * int(pr.get("pageSize") or 15)) or len(items)
            if items:
                it = items[0]
                out["sample"] = str(it.get("postName") or it.get("positionName") or "")[:40]
                # 公司名不在列表里，但 logo 路径里带英文简称（simcere=先声药业），是核对归属的证据之一
                out["logo"] = str(it.get("orgLogoUrl") or "").split("/oline/")[-1].rsplit("/", 1)[0][:30]
            out["with_city"] = sum(1 for it in items
                                   if it.get("workPlaceStr") or it.get("workPlace"))
            out["with_date"] = sum(1 for it in items if it.get("publishDate") or it.get("postDate"))
    except Exception as e:  # noqa: BLE001
        out["err"] = type(e).__name__
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True, help="search_ats 输出的 JSONL")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    seen: set[tuple[str, str]] = set()
    pairs: list[tuple[str, str]] = []
    for ln in Path(args.src).read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        for u in rec.get("urls") or []:
            m = URL_RE.match(u)
            if m:
                k = (m.group(1).lower(), m.group(2))
                if k not in seen:
                    seen.add(k)
                    pairs.append(k)
    outp = Path(args.out)
    done: set[tuple[str, str]] = set()
    if outp.exists():
        for ln in outp.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ln)
                done.add((d["host"], d["tenant"]))
            except Exception:  # noqa: BLE001
                pass
    todo = [p for p in pairs if p not in done]
    print(f"候选 {len(pairs)}，待探测 {len(todo)}", flush=True)

    t0 = time.time()
    hit = 0
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.workers) as ex, outp.open("a", encoding="utf-8") as f:
        for rec in ex.map(lambda p: probe(*p), todo):
            with lock:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                if rec["ok"] and rec["count"] > 0:
                    hit += 1
                    print(f"HIT {rec['host']:28s} {rec['tenant']} {rec['count']:6d} 岗  {rec['sample']}",
                          flush=True)
    print(f"完成 {len(todo)}，有岗 {hit}，用时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
