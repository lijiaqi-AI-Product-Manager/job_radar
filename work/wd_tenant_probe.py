"""Workday 租户穷举：`{词}.wdN.myworkdayjobs.com` 是**可枚举**的，跟北森租户一个道理。

为什么改走这条路（v1/v2/v3 全失败的实证都记在 docs/recon/workday.md）：
  - `{公司} myworkdayjobs` 搜 → 0 命中，必应把站点名当噪声词；
  - `{公司} 招聘 site:myworkdayjobs.com` → 从数据中心 IP 发出的查询里 `site:` 被完全忽略；
  - `myworkdayjobs {词}` → 必应只返回**同一批 9~10 个高权重站点**（workday/jll/abb/jd/
    accenture/mgmchina…），换任何限定词都一样，说明这个 IP 的结果集被严重裁剪。
所以搜索引擎最多给我 ~10 个租户，剩下只能自己枚举。

枚举空间怎么收窄（这是能跑的关键）：
  1. 词表 = **待覆盖的 735 家公司**（`targets/mega_companies.yaml` 里还没覆盖的）
           + 全部已覆盖公司/品牌的英文名（`BRAND_EN`，比亚迪→byd、隆力奇→longliqi…）
           + 每家公司的拼音全拼 / 首字母缩写（复用 `beisen_tenant_sweep.candidates`）。
     外资巨头在中国区用 Workday 的比例最高，它们的租户名几乎都是**英文品牌名**，
     所以 BRAND_EN 是主力；国企央企基本不用 Workday，不必浪费请求。
  2. `wdN` 的 N ∈ 1/3/5/12/103/501 —— 实测这几档覆盖了绝大多数客户（ABB wd3、
     京东 wd103、埃森哲 wd103、JLL wd1、洲际 wd5）。
  3. 路径 `/zh-CN/{site}` 里的 site 名字猜不到，但 **`/zh-CN/` 根路径会 302 到真实 site**，
     跟着跳转一次就拿到了。

红线：只打 `*.myworkdayjobs.com`，**同一主机 ≤1 rps**（不同租户是不同主机，可并行）；
只读 302 跳转 + cxs 公开接口第一页，不登录、不签名。
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
sys.path.insert(0, str(ROOT / "work"))
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import USER_AGENT  # noqa: E402

WDS = ("wd1", "wd3", "wd5", "wd12", "wd103", "wd501")
LOC = re.compile(r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_\-]+)", re.I)

_lock = threading.Lock()
_host_last: dict[str, float] = {}


def throttle(host: str) -> None:
    with _lock:
        gap = 1.05 - (time.time() - _host_last.get(host, 0.0))
        if gap > 0:
            time.sleep(gap)
        _host_last[host] = time.time()


def robots_sites(cli: httpx.Client, host: str) -> list[str]:
    """从 robots.txt 的 Sitemap 行里取 site 名（Workday 的公开约定）。"""
    throttle(host)
    try:
        r = cli.get(f"https://{host}/robots.txt")
    except httpx.HTTPError:
        return []
    if r.status_code != 200:
        return []
    out: list[str] = []
    for m in re.finditer(r"/([A-Za-z0-9_\-]+)/siteMap\.xml", r.text or ""):
        s = m.group(1)
        if s not in out and s.lower() not in ("login", "error"):
            out.append(s)
    if not out:
        # 有的客户 robots.txt 不给 Sitemap，只给 `Disallow: /{Site}/`（ABB 就是这样）。
        # 这类行里的 site 名同样是公开的，照收。
        for m in re.finditer(r"^Disallow:\s*/([A-Za-z0-9_\-]+)/\s*$", r.text or "", re.M):
            s = m.group(1)
            if s not in out and s.lower() not in ("refreshfacet", "login", "error"):
                out.append(s)
    return out


def probe(cli: httpx.Client, tenant: str, wd: str) -> dict | None:
    """探一个 `{tenant}.{wd}`；命中返回 {'site','count','jobs'}，否则 None。"""
    host = f"{tenant}.{wd}.myworkdayjobs.com"
    throttle(host)
    try:
        r = cli.get(f"https://{host}/")
    except httpx.HTTPError:
        return None
    # 存在性判定：真实租户根路径一律 406（Workday 要求带语言/站点段），
    # 不存在的租户给 404 + body 里跳 community.workday.com/invalid-url。这条是实测结论。
    if r.status_code == 404:
        return None
    if "invalid-url" in (r.text or "")[:600]:
        return None
    # 判定「这个租户存在」用 302：不存在的租户根路径一律 404（body 里跳
    # `community.workday.com/invalid-url`），存在的租户会 302 到 `/{lang}/{site}`。
    # **但 site 名不从跳转拿**——`/zh-CN/` 这种语言前缀路径实测也 404（ABB 就是）。
    # 最稳的公开线索是 `robots.txt`：Workday 会列出
    # `Sitemap: https://{host}/{Site}/siteMap.xml`，site 名一个不差
    # （京东就有 `Careers_at_JD` 与 `Campus_Career_Site` 两个）。
    sites = robots_sites(cli, host)
    if not sites:
        loc = r.headers.get("location") or ""
        if not loc.startswith("http"):
            loc = f"https://{host}/{loc.lstrip('/')}"
        m = LOC.search(loc)
        if m and m.group(1).lower() == tenant:
            sites = [m.group(3)]
    if not sites:
        return None
    site = sites[0]
    cxs = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    throttle(host)
    try:
        d = cli.post(cxs, json={"appliedFacets": {}, "limit": 20, "offset": 0,
                                "searchText": ""}).json()
    except Exception:  # noqa: BLE001
        return None
    total = int(d.get("total") or 0)
    posts = d.get("jobPostings") or []
    return {"tenant": tenant, "wd": wd, "site": site, "sites": sites, "host": host,
            "url": f"https://{host}/zh-CN/{site}", "count": total,
            "jobs": [str(p.get("title") or "")[:40] for p in posts[:6]],
            "locs": sorted({str(p.get("locationsText") or "")[:30] for p in posts[:20]})[:5]}


def build_words(names: list[str]) -> list[str]:
    """待试租户名：品牌英文名 + 拼音 + 首字母。"""
    import beisen_tenant_sweep as bb
    py = bb.load_pinyin()
    words: list[str] = []
    seen: set[str] = set()

    def add(x: str) -> None:
        x = re.sub(r"[^a-z0-9]", "", (x or "").lower())
        if 2 <= len(x) <= 24 and x not in seen:
            seen.add(x)
            words.append(x)

    for n in names:
        # ① 品牌英文名（最长匹配，跟 beisen_tenant_sweep 一致）
        base = bb.TAIL.sub("", n.strip())
        best = ""
        for k in bb.BRAND_EN:
            if (k == base or (len(k) >= 2 and k in n)) and len(k) > len(best):
                best = k
        if best:
            for v in bb.BRAND_EN[best]:
                add(v)
        # ② 名字里本来就有的英文段
        aw = re.findall(r"[A-Za-z][A-Za-z0-9]+", n)
        if aw:
            add("".join(aw))
            add(aw[0])
        # ③ 拼音全拼 / 首字母
        cn = re.sub(r"[0-9A-Za-z]", "", base)
        full = "".join(py.get(c, "") for c in cn)
        ini = "".join(py.get(c, "")[:1] for c in cn if py.get(c))
        add(full)
        if len(ini) >= 3:
            add(ini)
    return words


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True, help="公司名单，一行一家")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--wds", default=",".join(WDS))
    a = ap.parse_args()
    names = [x.strip() for x in Path(a.src).read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    words = build_words(names)
    if a.limit:
        words = words[: a.limit]
    wds = a.wds.split(",")
    out = Path(a.out)
    done: set[str] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ln)
                done.add(f"{d['tenant']}@{d['wd']}")
            except Exception:  # noqa: BLE001
                pass
    print(f"词表 {len(words)} 条 × wd {len(wds)} 档 = {len(words) * len(wds)} 次探测，"
          f"{a.workers} 路并行", flush=True)

    pairs = [(w, d) for w in words for d in wds if f"{w}@{d}" not in done]
    t0 = time.time()
    hits = 0
    fh = out.open("a", encoding="utf-8")

    def work(pair: tuple[str, str]) -> dict | None:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=12.0,
                          follow_redirects=False) as cli:
            return probe(cli, pair[0], pair[1])

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for i, res in enumerate(ex.map(work, pairs), 1):
            if res:
                with _lock:
                    fh.write(json.dumps(res, ensure_ascii=False) + "\n")
                    fh.flush()
                    hits += 1
                    print(f"HIT {res['host']:52s} {res['count']:6d} "
                          f"{(res['jobs'] or [''])[0][:28]}", flush=True)
            if i % 200 == 0:
                el = time.time() - t0
                print(f"... {i}/{len(pairs)} {el:.0f}s 命中 {hits} "
                      f"({el / i * 1000:.0f}ms/次)", flush=True)
    fh.close()
    print(f"完成 {len(pairs)}，命中 {hits}，用时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
