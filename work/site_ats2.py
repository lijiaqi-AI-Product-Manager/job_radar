"""从「自建站候选」里再挖一层 ATS：先看招聘入口页本身指向谁，再判技术栈。

为什么还要第二层：`site_ats` 只把**搜索结果里直接出现的**招聘域名认下来，
但很多公司自己的招聘页其实只是**转发壳**——页面上一句「点击进入投递系统」链到
`xxx.zhiye.com` / `xxx.hotjob.cn` / `xxx.jobs.feishu.cn`，或者内嵌 iframe。
这批链接不花一分钱（一次 GET 就能看到），命中即等于白捡一个 ATS 租户。

只处理 `site_ats` 判为 `self` / `nuxt` 的条目（ATS 的已经在第一层拿到了）。
新增判定：
  - 页面里出现 `*.zhiye.com` / `*.hotjob.cn` / `*.jobs.feishu.cn` / `*.mokahr.com` 等 → 归对应适配器；
  - 页面里出现 `webapi/api/connect/token`（深信服那套 Nuxt+WebAPI）→ `nuxt`；
  - 纯静态岗位列表（>=3 条带职位词）→ 保持 `self`，可直接喂 self_hosted 适配器。

用法：
    python3 work/site_ats2.py --in /tmp/exp/site1.jsonl --out /tmp/exp/site2.jsonl
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
sys.path.insert(0, str(ROOT / "work"))

import site_ats as sa  # noqa: E402

from jobradar.adapters.base import USER_AGENT  # noqa: E402

# 页面里出现这些域名 = 它把投递外包给了某家 ATS
EMBED = (
    (r"([a-z0-9\-]+)\.jobs\.feishu\.cn", "feishu_atsx"),
    (r"([a-z0-9\-]+)\.zhiye\.com", "beisen"),
    (r"([a-z0-9\-]+)\.hotjob\.cn", "hotjob"),
    # Moka 白标：公司把自己的域名 CNAME 到 Moka（`zp.hytera.com/apply/hytera/27049/`、
    # `jobs.anta.com/social-recruitment/antahr/146041/`）。页面里只出现 static-ats/sentry-fe
    # 这种公共子域，所以只能按**路径形态**认：`/apply/<org>/<id>` 或 `/<xxx>-recruitment/<org>/<id>`。
    (r"/(?:apply/[a-z0-9\-]+/\d+|(?:social|campus)-recruitment/[a-z0-9\-]+/\d+)/", "moka"),
    (r"([a-z0-9\-]+)\.italent\.cn", "italent"),
    (r"([a-z0-9\-]+)\.myworkdayjobs\.com", "workday"),
)
JOB_WORDS = ("工程师", "经理", "专员", "主管", "设计师", "分析师", "顾问", "实习生", "总监", "运营")


def embedded(html: str) -> tuple[str, str]:
    """页面里嵌了哪家 ATS；返回 (ats, tenant)。"""
    low = html.lower()
    for pat, ats in EMBED:
        m = re.search(pat, low)
        if m:
            return ats, (m.group(1) if m.groups() else "")
    if "webapi/api/connect/token" in low or "_nuxt/" in low:
        return "nuxt", ""
    return "", ""


def count_titles(html: str) -> int:
    """页面里像岗位标题的条目数（判 self 能不能直接解析）。"""
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    rows = re.findall(r"<(?:li|a|h3|h4|div)[^>]*>([^<>]{4,60})</(?:li|a|h3|h4|div)>", text)
    seen = set()
    for r in rows:
        t = re.sub(r"\s+", " ", r).strip()
        if 4 <= len(t) <= 45 and any(w in t for w in JOB_WORDS) and t not in seen:
            seen.add(t)
    return len(seen)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="/tmp/exp/site1.jsonl")
    ap.add_argument("--out", dest="out", default="/tmp/exp/site2.jsonl")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    rows = []
    for ln in Path(a.src).read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        if r.get("ats") in ("self", "nuxt"):
            rows.append(r)

    out = Path(a.out)
    done: set[str] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(ln)["company"])
            except Exception:  # noqa: BLE001
                pass
    todo = [r for r in rows if r["company"] not in done]
    print(f"自建候选 {len(rows)}，待深挖 {len(todo)}", flush=True)

    lock = threading.Lock()
    fh = out.open("a", encoding="utf-8")
    t0 = time.time()
    hits = {"ats": 0, "list": 0}

    def work(r: dict) -> None:
        entry = r.get("entry") or f"https://{r['host']}/"
        rec = {"company": r["company"], "from": r["host"], "ats": r.get("ats", ""),
               "tenant": "", "host": "", "entry": entry, "titles": 0, "conf": ""}
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=10.0,
                          follow_redirects=True) as cli:
            try:
                rr = cli.get(entry)
            except Exception:  # noqa: BLE001
                rr = None
            if rr is not None and rr.status_code == 200:
                ats, tenant = embedded(rr.text)
                if ats:
                    rec.update(ats=ats, tenant=tenant,
                               host=sa.host_of(str(rr.url)) if ats == "self" else
                               f"{tenant}.{ 'jobs.feishu.cn' if ats == 'feishu_atsx' else ('zhiye.com' if ats == 'beisen' else 'hotjob.cn')}")
                n = count_titles(rr.text)
                rec["titles"] = n
                # 入口页自己就是岗位列表页 → 记下来交给 self_hosted
                if not ats and n >= 3:
                    rec["ats"] = "self"
                    rec["host"] = sa.host_of(str(rr.url))
        with lock:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if rec["ats"] and rec["ats"] != "nuxt":
                hits["ats"] += 1
                if rec["ats"] == "self":
                    hits["list"] += 1
                print(f"HIT {rec['company']:14s} {rec['ats']:12s} {rec['tenant']:20s} "
                      f"titles={rec['titles']:<4} {entry[:60]}", flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(work, todo))
    fh.close()
    print(f"完成 {len(todo)}：新识别 ATS {hits['ats']}（其中可直接解析的列表页 {hits['list']}），"
          f"用时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
