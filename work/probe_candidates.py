"""把 brand_check 搜到的结果 URL 批量丢给 `probe_url`，挑出「真能吃」的入口。

为什么需要：`has_portal` 只说明搜索引擎**索引到过**这家公司的招聘标题，
那些 URL 里可能有官网、有第三方站、也有新闻页。真正要的是「能被适配器解析的公司门户」，
所以统一走 `probe_url.probe_url()` 判（跟爬虫同一套代码，探得通就等于抓得下来）。

归属判定沿用 verify_found 的思路：岗位名/部门名/门户标题里要出现公司核心词，
或者命中热招单位的公司字段。没有归属证据的只算「疑似」，不进源清单。

用法：
    python3 work/probe_candidates.py /tmp/exp/brand_split/has_portal.jsonl /tmp/exp/probe_sites.jsonl
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "work"))

from probe_url import probe_url  # noqa: E402

STRIP = ("股份有限公司", "有限责任公司", "有限公司", "集团股份", "控股集团", "集团公司",
         "集团", "股份", "控股", "公司", "中国区", "总公司")


def core(name: str) -> str:
    n = name
    for s in STRIP:
        if n.endswith(s) and len(n) > len(s):
            n = n[: -len(s)]
    return n


def name_hit(name: str, blob: str) -> bool:
    c = core(name)
    if not c or len(c) < 2:
        return False
    return c in blob or c[:2] in blob


def main() -> int:
    src = Path(sys.argv[1])
    out = Path(sys.argv[2])
    rows = [json.loads(ln) for ln in src.read_text(encoding="utf-8").splitlines() if ln.strip()]
    done: set[str] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(ln)["url"])
            except Exception:  # noqa: BLE001
                pass
    # 同一家公司的多个结果 URL 常常指向同一个门户（`/campus`、`/social`、`/`），
    # 按 URL 去重会重复打同一个接口。同一公司最多取 3 条互不相同的主机+路径首段。
    tasks = []
    for r in rows:
        seen_lane: set[str] = set()
        for u in (r.get("urls") or []):
            if u in done:
                continue
            lane = re.sub(r"^(https?://[^/]+/[^/?#]{0,32}).*$", r"\1", u)
            if lane in seen_lane:
                continue
            seen_lane.add(lane)
            tasks.append((r["company"], u))
            if len(seen_lane) >= 3:
                break
    print(f"候选 {len(tasks)} 条 URL（已探 {len(done)}）", flush=True)

    def run(t):
        comp, u = t
        pr = probe_url(u)
        blob = " ".join(pr.get("jobs") or []) + " " + " ".join(pr.get("companies") or [])
        blob += " " + str(pr.get("title") or "")
        pr["company"] = comp
        pr["url"] = u
        pr["name_hit"] = name_hit(comp, blob)
        return pr

    good = 0
    with out.open("a", encoding="utf-8") as f:
        with ThreadPoolExecutor(max_workers=6) as ex:
            for pr in ex.map(run, tasks):
                f.write(json.dumps(pr, ensure_ascii=False) + "\n")
                f.flush()
                if pr.get("count"):
                    tag = "OK " if pr["name_hit"] else "?? "
                    good += pr["name_hit"]
                    print(f"{tag}{pr['kind']:8s} {pr['company'][:12]:12s} {pr.get('count'):6d} "
                          f"{(pr.get('jobs') or [''])[0][:24]}", flush=True)
    print(f"完成，有归属证据 {good}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
