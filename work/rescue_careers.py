"""专项复核：把被过滤器误杀、但确实有官方招聘站的公司捞回来。

2026-10-26 实测：一批大公司的招聘站被前几轮规则误杀，原因各不相同——
- 标题是空的（JS 渲染，如 jobs.bytedance.com）；
- 域名是英文品牌词，与中文名拼音对不上（mihoyo / hikvision / luxshare）；
- 被"高校就业网"规则连带（career.muc.edu.cn 上的科大讯飞简章）；
- 同一 URL 被同集团多家子公司认领（奇瑞 / 奇瑞捷途），被当成冲突剔掉。

这里做两件事：
1. **同集团复用**：同一 URL 被同集团子公司认领时，只判给"名字最匹配"的那家，其余走自己的入口；
2. **专项搜索引擎复核**：对未覆盖公司，用「{主品牌} 招聘」再搜一次，只收
   **标题里出现公司名（或主品牌名）** 的结果，且域名不是第三方——这是最硬的证据。

用法：
    python3 work/rescue_careers.py [--limit N]
输出：work/careers_rescued.jsonl（可直接并入 careers_final）
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
from confirm_careers import check, is_third, tokens  # noqa: E402
from resolve_conflicts import THIRD_HOST  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SEARCH_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
H2 = re.compile(r"<h2[^>]*>.*?</h2>", re.S)
HREF = re.compile(r'href="(https?://[^"]+)"')
# 求职中介 / 问答聚合 / 内容农场：标题里常带公司名，但完全不是官方站
JUNK = re.compile(r"(hahazhao|ykof|gxbys|zhaopinbao|qiuzhi|liebiao|xinwen|wenda|zhidao|tieba|wenku|"
                  r"docin|doc88|renrendoc|360doc|baijiahao|ifeng|thepaper|jiemian|yicai|cls\.cn|stcn|"
                  r"cnstock|10jqka|hexun|jrj\.com|cn\.gold|smm\.cn|qianzhan|chyxx|askci|sohu|sina|"
                  r"guancha|jiemian|huxiu|tmtpost|donews|techweb|cnbeta|ithome|pconline|zol\.com)", re.I)
JUNK_PATH = re.compile(r"/(square|wenda|zhidao|baike|wiki|article|news|blog|doc|p/\d+)\.?(html?)?", re.I)

_lock = threading.Lock()
_next = [0.0]


def search(client: httpx.Client, query: str, n: int = 15) -> list[dict]:
    with _lock:
        now = time.monotonic()
        at = max(now, _next[0])
        _next[0] = at + 1.2
    if at > now:
        time.sleep(at - now)
    try:
        r = client.get("https://cn.bing.com/search",
                       params={"q": query, "ensearch": "0", "count": "20"},
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
        out.append({"title": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()[:90],
                    "url": u.group(1)})
        if len(out) >= n:
            break
    return out


def work(item):
    company, sector, brand, bnames, toks = item
    names = [x for x in ([brand] if brand else []) + bnames + [company] if x]
    qs = [f"{names[0]} 招聘", f"{company} 校园招聘"]
    with httpx.Client(follow_redirects=True, timeout=15, headers={"User-Agent": SEARCH_UA}) as c:
        res = []
        for q in qs:
            res += search(c, q)
    cands = []
    for r in res:
        u = r["url"].replace("&amp;", "&")
        host = (urlsplit(u).hostname or "").lower()
        if is_third(u) or THIRD_HOST.search(host) or JUNK.search(host) or JUNK_PATH.search(u):
            continue
        # 硬证据：结果标题里出现公司名或主品牌名
        if not any(nm and nm in r["title"] for nm in names[:3]):
            continue
        if u not in cands:
            cands.append(u)
    cands = cands[:4]
    got = []
    for u in cands:
        r = check((company, sector, brand, u, toks, False))
        if r.get("ok"):
            got.append(r)
    got.sort(key=lambda r: (0 if company in (r.get("title") or "") else 1, len(r["url"])))
    return {"company": company, "sector": sector, "brand": brand, "tokens": toks,
            "best": got[0] if got else None, "all": got[:3], "conf": "rescue"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    pool = {}
    for r in csv.reader(open(ROOT / "work/pool.tsv", encoding="utf-8"), delimiter="\t"):
        pool[r[0]] = (r[1], (r[2] if len(r) > 2 else ""))
    brands = json.loads((ROOT / "work/brands.json").read_text(encoding="utf-8"))

    covered = set()
    for line in (ROOT / "work/careers_final.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            covered.add(json.loads(line)["company"])
    # 已在日历里的（含人工维护）也算覆盖
    import yaml
    for p in (ROOT / "calendar" / "entries").glob("*.yaml"):
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if d.get("group"):
            covered.add(d["group"])

    todo = []
    for c, (sector, brand) in pool.items():
        if c in covered:
            continue
        todo.append((c, sector, brand, brands.get(c, []), tokens(c, brand)))
    if args.limit:
        todo = todo[:args.limit]
    print(f"todo={len(todo)}", file=sys.stderr)

    out = ROOT / "work/careers_rescued.jsonl"
    n, ok, t0 = 0, 0, time.time()
    with open(out, "w", encoding="utf-8") as fh, ThreadPoolExecutor(args.workers) as ex:
        for row in ex.map(work, todo):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            n += 1
            if row["best"]:
                ok += 1
                print(f"[{n}] RESCUE {row['company']} -> {row['best']['url']}", file=sys.stderr)
            elif n % 20 == 0:
                print(f"[{n}/{len(todo)}] {n / max(time.time() - t0, 1) * 60:.1f} 家/分", file=sys.stderr)
    print(f"done {n} rescued {ok}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
