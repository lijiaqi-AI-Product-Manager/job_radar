"""从搜索结果里反推公司主域名，再用主域找招聘入口。

问题（2026-10-26 实测）：直接按公司���拼域名会撞到别人家——歌尔股份 → geer.com（不存在）/ ge.com
（通用电气），广汽集团 → guangqi.com（不存在），鹰角网络 → yingjiaowangluo.com（不存在）。
而搜索引擎对「歌尔股份 校园招聘 官网」也会返回音乐网站（被拆成「歌」）。

更稳的办法：
1. 用「{公司} 官网」搜索，从结果里挑**标题里带公司名**、且不是第三方聚合站的结果；
2. 逐个抓这些站点的首页，确认首页标题/正文含公司名（这一步把「爱企查/汽车之家」过滤掉）；
3. 在这个已确认是公司官网的站点上，找招聘链接（href 带招聘词）或试招聘子域。

红线：只读公开页面；同主机 ≤1 rps；不登录、不破验证码；找不到就判负，不硬凑。

用法：
    python3 work/find_home.py --limit 0
输出：work/home_found.jsonl
"""

import argparse
import csv
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from confirm_careers import (  # noqa: E402
    CAREER_WORD,
    HOST_HINT,
    HREF_RE,
    UA,
    is_third,
    throttle,
    title_of,
    tokens,
)

ROOT = Path(__file__).resolve().parent.parent
SEARCH_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
H2 = re.compile(r"<h2[^>]*>.*?</h2>", re.S)
HREF = re.compile(r'href="(https?://[^"]+)"')
_search_lock = threading.Lock()
_search_next = [0.0]


def search(client: httpx.Client, query: str, n: int = 12) -> list[dict]:
    with _search_lock:
        now = time.monotonic()
        at = max(now, _search_next[0])
        _search_next[0] = at + 1.2
    if at > now:
        time.sleep(at - now)
    try:
        r = client.get(f"https://cn.bing.com/search?q={httpx.QueryParams({'q': query})['q']}"
                       f"&ensearch=0&count=20",
                       headers={"User-Agent": SEARCH_UA, "Accept-Language": "zh-CN,zh;q=0.9"},
                       timeout=15, follow_redirects=True)
    except Exception:
        return []
    if r.status_code != 200:
        return []
    out = []
    for m in H2.finditer(r.text):
        s = m.group(0)
        u = HREF.search(s)
        if not u:
            continue
        out.append({"title": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()[:80],
                    "url": u.group(1)})
        if len(out) >= n:
            break
    return out


def home_ok(item):
    """抓站点首页，判断它是不是这家公司的官网（标题或正文前 3 万字出现公司名）。"""
    company, url, name_tokens = item
    host = (urlsplit(url).hostname or "").lower()
    throttle(host)
    try:
        with httpx.Client(follow_redirects=True, timeout=12,
                          headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.8"}) as c:
            r = c.get(url)
    except Exception:
        return None
    if r.status_code != 200 or len(r.text) < 800:
        return None
    title = title_of(r.text)
    plain = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text[:120000], flags=re.S)
    plain = re.sub(r"<[^>]+>", " ", plain)
    hit = company in title or company in plain
    links = []
    base = str(r.url)
    for href in HREF_RE.findall(r.text[:300000]):
        if CAREER_WORD.search(href):
            u = str(httpx.URL(base).join(href))
            if urlsplit(u).hostname and u not in links:
                links.append(u)
    return {"url": base, "title": title, "hit": hit, "links": links[:6], "size": len(r.content)}


def work(item):
    company, sector, brand, bnames = item
    toks = tokens(company, brand)
    qs = []
    for b in ([brand] if brand else []) + bnames[:2]:
        qs += [f"{b} 招聘官网", f"{b} 校园招聘"]
    qs += [f"{company} 招聘官网"]
    with httpx.Client(follow_redirects=True, timeout=15, headers={"User-Agent": SEARCH_UA}) as c:
        res = []
        for q in qs[:4]:
            res += search(c, q)
    cands = []
    for r in res:
        u = r["url"].replace("&amp;", "&")
        if is_third(u):
            continue
        h = (urlsplit(u).hostname or "").lower()
        if not h or h in ("cn.bing.com",):
            continue
        # 标题里带公司名，或域名里带公司拼音 token
        flat = re.sub(r"[^a-z0-9]", "", h)
        if company in r["title"] or any(t in flat for t in toks):
            root = f"https://{h}/"
            if root not in cands:
                cands.append(root)
    cands = cands[:6]
    checked = []
    with ThreadPoolExecutor(4) as ex:
        for r in ex.map(home_ok, [(company, u, toks) for u in cands]):
            if r:
                checked.append(r)
    good = [r for r in checked if r["hit"]]
    if not good:
        return {"company": company, "sector": sector, "brand": brand, "tokens": toks,
                "home": None, "links": [], "checked": [r["url"] for r in checked]}
    # 优先带招聘链接的官网
    good.sort(key=lambda r: (0 if r["links"] else 1, len(r["url"])))
    best = good[0]
    # 所有「确认是公司官网」的站点上的招聘链接都收；招聘子域（careers./join./campus.）本身也算命中
    links = []
    for r in good:
        for u in r["links"]:
            if u not in links:
                links.append(u)
        if HOST_HINT.search(urlsplit(r["url"]).hostname or ""):
            links.append(r["url"])
    return {"company": company, "sector": sector, "brand": brand, "tokens": toks,
            "home": best["url"], "title": best["title"], "links": links[:8],
            "checked": [r["url"] for r in checked]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default="work/home_found.jsonl")
    ap.add_argument("--only-missing", action="store_true", help="只处理 careers_confirmed 里没确认入口的公司")
    args = ap.parse_args()

    brands = {}
    bf = ROOT / "work/brands.json"
    if bf.exists():
        brands = json.loads(bf.read_text(encoding="utf-8"))
    pool = [(r[0], r[1], (r[2] if len(r) > 2 else ""), brands.get(r[0], [])) for r in
            csv.reader(open(ROOT / "work/pool.tsv", encoding="utf-8"), delimiter="\t")]
    todo = pool
    if args.only_missing:
        conf = ROOT / "work/careers_confirmed.jsonl"
        if conf.exists():
            ok = {json.loads(s)["company"] for s in conf.read_text(encoding="utf-8").splitlines()
                  if s.strip() and json.loads(s).get("best")}
            todo = [p for p in pool if p[0] not in ok]
    outfile = ROOT / args.out
    done = set()
    if outfile.exists():
        done = {json.loads(s)["company"] for s in outfile.read_text(encoding="utf-8").splitlines() if s.strip()}
    todo = [p for p in todo if p[0] not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"todo={len(todo)}", file=sys.stderr)

    n, t0 = 0, time.time()
    with open(outfile, "a", encoding="utf-8") as fh, ThreadPoolExecutor(args.workers) as ex:
        for row in ex.map(work, todo):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            n += 1
            if n % 10 == 0:
                print(f"[{n}/{len(todo)}] {n / max(time.time() - t0, 1) * 60:.1f} 家/分", file=sys.stderr)
    print(f"done {n} in {time.time() - t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
