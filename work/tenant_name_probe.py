"""按命名规律探测 hotjob / feishu 租户（不再重扫北森，北森那条已证实是残差）。

背景：`work/multi_tenant_probe.py` 首轮 40 家 × 5 候选 × 3 平台命中 0，原因是「已有源的公司」
在上一轮已经用同一套拼音扫过，`tmp_unsourced.json` 里剩下的是猜不中的残差。
但 hotjob 的判定当时要求正文含 `wecruit`，伊利这类 200 跳 `/wt/<corp>/` 的会被漏掉；
feishu 的判定只看 csrf token，成本极低。这里把两者重跑一遍并修掉 hotjob 判定。

输出：work/tenant_probe2.jsonl（每行 {company, platform, slug, title, url}，只记命中）、
      work/tenant_probe2_done.txt（已完成公司，断点续跑）
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
sys.path.insert(0, str(WORK))

import beisen_tenant_sweep as bb  # noqa: E402  (复用候选生成与拼音表)

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
GENERIC = {"职位列表", "招聘", "招聘职位", "校园招聘", "社会招聘", "职位搜索", "首页", "首页-职位列表"}

_lock = threading.Lock()
_last = [0.0]
MIN_GAP = 0.08  # 全局约 12 req/s


def _gap() -> None:
    with _lock:
        now = time.time()
        wait = _last[0] + MIN_GAP - now
        if wait > 0:
            time.sleep(wait)
            now = time.time()
        _last[0] = now


def _get(url: str, timeout: float = 9.0) -> tuple[int, str, str]:
    _gap()
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 已知 https 站点
            raw = resp.read(200_000)
            return resp.status, resp.geturl(), raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, url, ""
    except Exception:  # noqa: BLE001 - DNS/超时/重置都当不可用
        return 0, url, ""


def _post(url: str, timeout: float = 9.0) -> str:
    _gap()
    data = json.dumps({"portal_entrance": 1}).encode()
    req = urllib.request.Request(
        url, data=data, headers={**UA, "Accept": "application/json",
                                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read(50_000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def title_of(html: str) -> str:
    m = TITLE_RE.search(html)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:80] if m else ""


def probe_hotjob(slug: str) -> dict | None:
    status, final, html = _get(f"https://{slug}.hotjob.cn/")
    if status != 200 or len(html) < 2000:
        return None
    if not ("/wt/" in html or "wecruit" in html or "hotjob" in final):
        return None
    title = title_of(html)
    if title in GENERIC:
        return None
    return {"platform": "hotjob", "slug": slug, "title": title, "url": final}


def probe_feishu(slug: str) -> dict | None:
    body = _post(f"https://{slug}.jobs.feishu.cn/api/v1/csrf/token")
    if not body:
        return None
    try:
        d = json.loads(body)
    except ValueError:
        return None
    if not ((d.get("data") or {}).get("token")):
        return None
    status, final, html = _get(f"https://{slug}.jobs.feishu.cn/")
    return {"platform": "feishu", "slug": slug, "title": title_of(html) if status == 200 else "",
            "url": f"https://{slug}.jobs.feishu.cn/"}


def slugs_for(name: str) -> list[str]:
    try:
        cands = bb.candidates(name, bb.load_pinyin())
    except Exception:  # noqa: BLE001 - 候选生成失败就退回纯小写
        return [re.sub(r"[^a-z0-9]", "", name.lower())]
    out: list[str] = []
    for c in cands:
        c = c.strip().lower()
        if not c or c in out or c in getattr(bb, "TENANT_DENY", set()):
            continue
        if not re.fullmatch(r"[a-z0-9][a-z0-9\-]{1,38}", c):
            continue
        out.append(c)
    return out[:4]


def main() -> None:
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    only = sys.argv[2] if len(sys.argv) > 2 else ""
    companies = [x["company"] if isinstance(x, dict) else x
                 for x in json.loads((ROOT / "tmp_unsourced.json").read_text(encoding="utf-8"))]
    done_path = WORK / "tenant_probe2_done.txt"
    done = set(done_path.read_text(encoding="utf-8").split()) if done_path.exists() else set()
    out_path = WORK / "tenant_probe2.jsonl"
    todo = [c for c in companies if c not in done]
    print(f"待探测 {len(todo)} 家（已完成 {len(done)}），并发 {workers}", flush=True)

    counters = {"hotjob": 0, "feishu": 0}
    t0 = time.time()
    with ThreadPoolExecutor(workers) as ex, \
            open(out_path, "a", encoding="utf-8") as fout, \
            open(done_path, "a", encoding="utf-8") as fdone:
        futs = {}
        for company in todo:
            for slug in slugs_for(company):
                for fn, tag in ((probe_hotjob, "hotjob"), (probe_feishu, "feishu")):
                    if only and only != tag:
                        continue
                    futs[ex.submit(fn, slug)] = (company, tag)
        for i, fut in enumerate(futs, 1):
            company, tag = futs[fut]
            rec = fut.result()
            if not rec:
                continue
            rec["company_guess"] = company
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fout.flush()
            counters[tag] += 1
            print(f"[{i}/{len(futs)}] {tag:7s} {rec['slug']:22s} {rec['title'][:28]} "
                  f"(from {company})", flush=True)
            if i % 400 == 0:
                print(f"... {i}/{len(futs)} {time.time() - t0:.0f}s hit={counters}", flush=True)
        for company in todo:
            fdone.write(company + "\n")
        fdone.flush()
    print(f"完成：{counters}，用时 {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
