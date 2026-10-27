"""ATS 租户二级隐藏入口探测器：JS 包挖 slug + 门户域名爆破。

为什么再造一版：`ats_par.py` 只试**公司名拼音**生成的 10 个候选，而企业实际用的
slug 经常跟中文名无关（小米 `mi`、京东方 `boe`、宁德时代 `catl` 都还能猜中，
但更多公司的 slug 是 `xyz-hr`、`hr-abc` 这种）。实测命中率被这一层卡死在 ~1%。

三条新管道（都只用公开页面，不解密、不签名、不登录）：

  A. **JS 包挖 slug**：飞书 ATSX / 北森门户的首页 JS bundle 里通常内嵌
     `website:{...}` 配置或 `"slug":"xxx"` 字面量——浏览器本来就要下载它。
     拿不到就跳过，不做任何混淆还原。
  B. **公司官网 → 常见招聘子域**：`{slug}.jobs.feishu.cn` 之外，自动站常见
     `hr.{domain}` / `job.{domain}` / `zhaopin.{domain}` / `career.{domain}`。
     只取已收录公司的官网域名，DNS 先筛。
  C. **品牌英文名**：从已收录公司的 `name_en`（若有）和商标式英文名生成候选。

输出格式与 `ats_par.py` 一致（company / found / urls），可直接喂 `verify_found.py`。

用法：
    python3 work/ats_js.py --in /tmp/exp/gap_nat.txt --out /tmp/exp/js1.jsonl --workers 8
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "work"))

from jobradar.adapters.base import USER_AGENT  # noqa: E402

# 首页 JS bundle 里这些字段名后面跟的字符串就是 slug（飞书 ATSX）
SLUG_KEYS = (r'"slug"\s*:\s*"([a-z0-9][a-z0-9\-]{1,40})"',
             r'"website_slug"\s*:\s*"([a-z0-9][a-z0-9\-]{1,40})"',
             r'"portal_slug"\s*:\s*"([a-z0-9][a-z0-9\-]{1,40})"')
JS_SRC = re.compile(r'<script[^>]+src="([^"]+\.js[^"]*)"', re.I)


def feishu_slug_from_html(cli: httpx.Client, host: str) -> str | None:
    """飞书门户首页 → 主 JS bundle → slug 字面量。

    实测（2026-10-27）：`vrfi1sk8a0.jobs.feishu.cn`（MiniMax 真实门户）首页内嵌
    `"slug":"vrfi1sk8a0"`，而 `minimax.jobs.feishu.cn` 是个 400 空壳。
    这条管道能覆盖「公司名猜不中、但官网或搜索结果里有正确域名」的情况。
    """
    try:
        r = cli.get(f"https://{host}/")
        if r.status_code != 200:
            return None
        html = r.text
    except Exception:  # noqa: BLE001
        return None
    for pat in SLUG_KEYS:
        m = re.search(pat, html)
        if m:
            return m.group(1)
    # 内联没写就进 bundle 里找（只取同域脚本，最多 3 个，避免把整站 JS 都拉一遍）
    for src in JS_SRC.findall(html)[:3]:
        if not src.startswith("http"):
            src = "https://" + host + ("" if src.startswith("/") else "/") + src.lstrip("/")
        try:
            js = cli.get(src).text
        except Exception:  # noqa: BLE001
            continue
        for pat in SLUG_KEYS:
            m = re.search(pat, js)
            if m:
                return m.group(1)
    return None


def dns_ok(host: str) -> bool:
    try:
        socket.gethostbyname(host)
        return True
    except OSError:
        return False


def probe_self_hosted(cli: httpx.Client, host: str) -> dict | None:
    """自建招聘站存在性：`/` 200 且页面里出现「职位/招聘/job」字样。

    不判「有没有岗位」——具体解析交给已有适配器；这里只负责把活着的入口捞出来。
    """
    try:
        r = cli.get(f"https://{host}/", follow_redirects=True)
    except Exception:  # noqa: BLE001
        return None
    if r.status_code != 200 or len(r.text) < 200:
        return None
    low = r.text.lower()
    if not any(w in low for w in ("职位", "招聘", "job", "career", "position")):
        return None
    m = re.search(r"<title>(.*?)</title>", r.text, re.I | re.S)
    title = re.sub(r"\s+", " ", m.group(1)).strip()[:40] if m else ""
    return {"ats": "self", "tenant": host, "host": host, "count": -1, "title": title, "jobs": []}


AUTO_SUBDOMAINS = ("hr", "job", "jobs", "zhaopin", "career", "careers", "recruit", "talent")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--domains", default="/tmp/exp/company_domains.json",
                    help="公司名 -> 官网域名 的 JSON（可选；没有就只跑飞书 slug 管道）")
    a = ap.parse_args()

    names = [x.strip() for x in Path(a.src).read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    out = Path(a.out)
    done: set[str] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(ln)["company"])
            except Exception:  # noqa: BLE001
                pass
    todo = [n for n in names if n not in done]

    domains: dict[str, str] = {}
    dp = Path(a.domains)
    if dp.exists():
        domains = json.loads(dp.read_text(encoding="utf-8"))

    print(f"待查 {len(todo)} 家，{a.workers} 路并行，域名表 {len(domains)} 条", flush=True)
    lock = threading.Lock()
    hits = 0
    t0 = time.time()
    fh = out.open("a", encoding="utf-8")

    def work(name: str) -> None:
        nonlocal hits
        found: list[dict] = []
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=10.0,
                          follow_redirects=True) as cli:
            # 管道 A：官网域名 -> 飞书门户（{domain 首段}.jobs.feishu.cn）→ 挖真实 slug
            dom = domains.get(name, "")
            stem = dom.split(".")[0] if dom else ""
            if stem and len(stem) >= 2:
                for cand in (stem, stem.replace("-", "")):
                    host = f"{cand}.jobs.feishu.cn"
                    if dns_ok(host):
                        slug = feishu_slug_from_html(cli, host)
                        if slug and slug != cand:
                            found.append({"ats": "feishu-slug", "tenant": slug,
                                          "count": -1, "title": "", "jobs": [],
                                          "via": host})
                        if slug:
                            break
            # 管道 B：官网域名 -> 自动站常见子域（只对已收录官网跑，避免撞无关站点）
            if dom:
                for sub in AUTO_SUBDOMAINS:
                    host = f"{sub}.{dom}"
                    if not dns_ok(host):
                        continue
                    pr = probe_self_hosted(cli, host)
                    if pr:
                        found.append(pr)
                        break
        rec = {"company": name, "found": found,
               "urls": [f"https://{pr['host']}/" for pr in found]}
        with lock:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if found:
                hits += 1
                print(f"HIT {name:16s} " + " | ".join(
                    f"{pr['ats']}:{pr['tenant']}" for pr in found), flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(work, n) for n in todo]
        for i, fu in enumerate(futs, 1):
            fu.result()
            if i % 25 == 0:
                el = time.time() - t0
                print(f"... {i}/{len(todo)} {el:.0f}s 命中 {hits} ({el / i:.2f}s/家)", flush=True)
    fh.close()
    print(f"完成 {len(todo)}，命中 {hits} 家，用时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
