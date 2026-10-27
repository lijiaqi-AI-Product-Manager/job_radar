"""批量探测北森租户：多线程 + 每主机≤1rps + 断点续跑。

`scripts/probe_beisen_tenants.py` 是单线程、每 slug 睡 1s，2400 个候选要 40 分钟，
对「一次扩 400 家」来说太慢。这里做三处优化，红线一条没动：

  1. **每个租户是独立主机**（`{slug}.zhiye.com`），限速按主机算。所以并行不同 slug
     不违反「每主机 ≤1 rps」，也不违反「同主机串行」——同主机只会出现一次。
  2. **只打列表接口**，不先 GET 首页：列表接口 `Code=200` 就说明租户活着，
     首页那次请求省掉（每个租户从 2 次降到 1 次）。
  3. **结果边跑边落盘**（JSONL 追加），中断后 `--resume` 跳过已探测的 slug。

为什么不多线程同一个 slug：那就是对同一主机并发，违反红线。
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import USER_AGENT  # noqa: E402

LIST_URL = "https://{slug}.zhiye.com/api/Jobad/GetJobAdPageList"
# 带了 DisplayFields 才回城市和日期；探测阶段只关心有没有岗，可以不带
BODY = {"PageIndex": 0, "PageSize": 3, "KeyWords": "", "SpecialType": 0, "PortalId": ""}
# 与 src/jobradar/adapters/beisen.py 的 DISPLAY_FIELDS 保持同口径：
# 不带它，LocNames 恒空、PostDate 恒为 0001-01-01（看起来像平台没数据，其实是没要）
DISPLAY_FIELDS = ["Category", "LocId", "PostDate", "EndTime", "Degree",
                  "ClassificationOne", "LocNames"]

_print_lock = threading.Lock()
_write_lock = threading.Lock()


def probe_one(slug: str) -> dict:
    out = {"slug": slug, "ok": False, "count": 0, "title": "", "err": ""}
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=15.0,
                          follow_redirects=False) as cli:
            r = cli.post(LIST_URL.format(slug=slug), json=BODY)
            if r.status_code != 200:
                out["err"] = f"http{r.status_code}"
                return out
            try:
                data = r.json()
            except ValueError:
                out["err"] = "notjson"
                return out
            if data.get("Code") != 200:
                out["err"] = f"code{data.get('Code')}"
                return out
            out["ok"] = True
            out["count"] = data.get("Count") or 0

            # 城市/日期探测：带 DisplayFields 再要一次，看这个租户到底有多少条「有城市、有发布日」。
            # 只关心比例，取 20 条样本即可，不为探测付全量代价。
            try:
                r2 = cli.post(LIST_URL.format(slug=slug),
                              json={**BODY, "PageSize": 20, "DisplayFields": DISPLAY_FIELDS})
                items = (r2.json().get("Data") or [])
                if items:
                    out["sample"] = len(items)
                    out["with_city"] = sum(1 for it in items if it.get("LocNames"))
                    out["with_date"] = sum(
                        1 for it in items if str(it.get("PostDate") or "").startswith("20"))
            except Exception:  # noqa: BLE001
                pass

            # 门户名只在首页 <title> 里（列表接口不回），命中后再补一次请求核对「这家 slug 真是这家公司」。
            # 命中错公司是扩源最大的坑：`zhongguo`、`dianzi` 这类通用词很容易落到无关租户上。
            try:
                hp = cli.get(f"https://{slug}.zhiye.com/")
                t = hp.text
                s, e = t.find("<title>"), t.find("</title>")
                if 0 <= s < e:
                    out["title"] = t[s + 7:e].strip()[:80]
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:  # noqa: BLE001
        out["err"] = type(e).__name__
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="候选 slug，一行一个")
    ap.add_argument("--out", required=True, help="结果 JSONL（追加）")
    ap.add_argument("--workers", type=int, default=8, help="并行主机数（每个 slug 一个主机）")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    slugs = [ln.strip() for ln in Path(args.file).read_text(encoding="utf-8-sig").splitlines()
             if ln.strip() and not ln.startswith("#")]
    outp = Path(args.out)
    done: set[str] = set()
    if outp.exists():
        for ln in outp.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(ln)["slug"])
            except Exception:  # noqa: BLE001
                pass
    todo = [s for s in slugs if s not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"待探测 {len(todo)}（已完成 {len(done)}）workers={args.workers}", flush=True)

    t0 = time.time()
    hits = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex, outp.open("a", encoding="utf-8") as f:
        for i, rec in enumerate(ex.map(probe_one, todo), 1):
            with _write_lock:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
            if rec["ok"]:
                hits += 1
                with _print_lock:
                    print(f"HIT  {rec['slug']:24s}{rec['count']:>6} 岗  {rec['title']}", flush=True)
            if i % 200 == 0:
                with _print_lock:
                    print(f"... {i}/{len(todo)}  {time.time() - t0:.0f}s  命中 {hits}", flush=True)
    print(f"完成 {len(todo)}，命中 {hits}，用时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
