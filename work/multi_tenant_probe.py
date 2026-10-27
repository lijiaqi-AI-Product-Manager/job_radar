"""多平台租户探测：把公司名展开成「常见租户命名」，在 3 个平台并行验证，产出可收录的源。

沿用 beisen_tenant_sweep.py 的候选生成（拼音/首字母/品牌英文名），但把验证扩展到
三个可枚举的平台：

  1. 北森新门户 `{tenant}.zhiye.com` —— POST 列表接口，`Count>0` 即命中（岗位数直接可读）；
  2. 大易 `{brand}.hotjob.cn` —— GET 首页，跳转到 `/wt/{tenant}/web/...` 即命中；
  3. 飞书 ATSX `{slug}.jobs.feishu.cn` —— POST `/api/v1/csrf/token`，拿到 `data.token` 即命中。

红线（与 CLAUDE.md 一致）：
  - 每个主机 ≤1 rps：同一 host 上两次请求间隔 ≥1.05s（全局节流表）；
  - 只读公开列表/首页，不登录、不翻页、不抓 JD；
  - 只探测**目标公司清单里**的公司，不扫无关域名。

用法：
    python3 work/multi_tenant_probe.py --names /tmp/names.txt --out /tmp/probe.jsonl
    python3 work/multi_tenant_probe.py ... --limit 60 --workers 4   # 小批试跑
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "work"))

from beisen_tenant_sweep import TENANT_DENY, candidates  # noqa: E402

from jobradar.adapters.base import USER_AGENT  # noqa: E402

BEISEN_LIST = "https://{t}.zhiye.com/api/Jobad/GetJobAdPageList"
BEISEN_BODY = {
    "PageIndex": 0, "PageSize": 20, "KeyWords": "", "SpecialType": 0, "PortalId": "",
    "DisplayFields": ["Category", "LocId", "PostDate", "LocNames"],
}
HOTJOB = "https://{t}.hotjob.cn/"
FEISHU = "https://{t}.jobs.feishu.cn/api/v1/csrf/token"
UA = {"User-Agent": USER_AGENT}

_lock = threading.Lock()
_last: dict[str, float] = {}
# 全局请求节奏：3 个平台 × 若干并发，仍保持对同一 CDN 的克制（≤6 rps 聚合）。
_global_last = [0.0]
GLOBAL_GAP = 0.16


def _throttle(host: str) -> None:
    while True:
        with _lock:
            now = time.time()
            wait = max(_last.get(host, 0.0) + 1.05 - now, _global_last[0] + GLOBAL_GAP - now)
            if wait <= 0:
                _last[host] = now
                _global_last[0] = now
                return
        time.sleep(min(wait, 0.5))


def probe_beisen(cli: httpx.Client, slug: str) -> dict:
    _throttle(f"zhiye:{slug}")
    try:
        r = cli.post(BEISEN_LIST.format(t=slug), json=BEISEN_BODY, timeout=10.0)
        if r.status_code != 200 or not r.text.strip().startswith("{"):
            return {"ok": False, "err": f"http{r.status_code}"}
        d = r.json()
        if d.get("Code") != 200:
            return {"ok": False, "err": f"code{d.get('Code')}"}
        items = d.get("Data") or []
        count = max(int(d.get("Count") or 0), len(items))
        return {"ok": count > 0, "count": count,
                "sample": [str(i.get("JobAdName") or "") for i in items[:5]],
                "codes": [str(i.get("PostCode") or "") for i in items[:5] if i.get("PostCode")]}
    except httpx.HTTPError as e:
        return {"ok": False, "err": type(e).__name__}


def probe_hotjob(cli: httpx.Client, slug: str) -> dict:
    _throttle(f"hotjob:{slug}")
    try:
        r = cli.get(HOTJOB.format(t=slug), timeout=10.0)
        url = str(r.url)
        if r.status_code == 200 and "wecruit" in url + r.text[:4000]:
            return {"ok": True, "final_url": url}
        return {"ok": False, "err": f"http{r.status_code}"}
    except httpx.HTTPError as e:
        return {"ok": False, "err": type(e).__name__}


def probe_feishu(cli: httpx.Client, slug: str) -> dict:
    _throttle(f"feishu:{slug}")
    try:
        r = cli.post(FEISHU.format(t=slug), json={"portal_entrance": 1},
                     headers={**UA, "Accept": "application/json"}, timeout=10.0)
        if r.status_code != 200:
            return {"ok": False, "err": f"http{r.status_code}"}
        d = r.json()
        tok = (d.get("data") or {}).get("token") or ""
        return {"ok": bool(tok), "token_len": len(tok)}
    except (httpx.HTTPError, ValueError) as e:
        return {"ok": False, "err": type(e).__name__}


def probe_one(name: str, slugs: list[str]) -> dict:
    out = {"company": name, "tried": [], "hits": []}
    with httpx.Client(headers=UA, follow_redirects=True, timeout=10.0) as cli:
        for slug in slugs:
            if slug in TENANT_DENY:
                continue
            out["tried"].append(slug)
            for kind, fn in (("beisen", probe_beisen), ("hotjob", probe_hotjob),
                             ("feishu", probe_feishu)):
                res = fn(cli, slug)
                if res.get("ok"):
                    out["hits"].append({"kind": kind, "slug": slug, **res})
                    break  # 同一租户名在一个平台命中就够了
            if out["hits"]:
                break  # 公司已找到门户，不再试后面的命名法
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--candidates", type=int, default=6)
    ap.add_argument("--pinyin", default=str(ROOT / "work" / "pinyin_single.json"))
    a = ap.parse_args()

    names = [ln.strip() for ln in Path(a.names).read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    out = Path(a.out)
    done: set[str] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(ln)["company"])
            except Exception:  # noqa: BLE001
                pass
    todo = [n for n in names if n not in done]
    if a.limit:
        todo = todo[: a.limit]
    py = json.loads(Path(a.pinyin).read_text(encoding="utf-8")) if Path(a.pinyin).exists() else {}
    random.Random(20261027).shuffle(todo)
    print(f"待查 {len(todo)} 家，拼音表 {len(py)} 字，并发 {a.workers}", flush=True)

    hits = 0
    t0 = time.time()
    lock = threading.Lock()
    with out.open("a", encoding="utf-8") as f, ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(probe_one, n, candidates(n, py)[: a.candidates]): n for n in todo}
        for i, fut in enumerate(futs, 1):
            try:
                rec = fut.result()
            except Exception as e:  # noqa: BLE001
                rec = {"company": futs[fut], "tried": [], "hits": [], "err": type(e).__name__}
            with lock:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                if rec["hits"]:
                    hits += 1
                    h = rec["hits"][0]
                    print(f"HIT {rec['company']:16s} {h['kind']:7s} {h['slug']:22s} {h.get('count', '')}", flush=True)
                if i % 50 == 0:
                    el = time.time() - t0
                    print(f"... {i}/{len(todo)} {el:.0f}s 命中 {hits} ({el / i:.2f}s/家)", flush=True)
    print(f"完成 {len(todo)}，命中 {hits}，用时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
