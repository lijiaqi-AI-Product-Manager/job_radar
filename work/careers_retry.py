"""给「被冲突/第三方过滤掉的目标企业」做第二轮定点补捞。

背景：resolve_conflicts 剔掉了 154 家 targets 500 里的公司，其中 47 家只找到高校就业网、
82 家连 best 都没有。这些公司绝大多数是**大企业（中国银行、中国石油、国家电网级）**，
它们一定有自家招聘站，只是第一轮用全名搜索（「中国铝业股份有限公司 招聘官网」）
被搜索引擎拆词或导向了转载页。

做法：
1. 用品牌短名（brand_names.py 生成的 brands.json）拼更少的词去搜，命中率明显更高；
2. 候选链接必须满足**域名/路径里出现品牌拼音或英文 token**，否则一律不收
   —— 这一条是防张冠李戴的硬闸，宁缺毋滥；
3. 抓一次页面确认 200 且不是登录墙；
4. 输出 work/careers_retry.jsonl，字段与 careers_confirmed 对齐，可直接进 merge_entries。

用法：
    python3 work/careers_retry.py --limit 40
"""

import argparse
import html as htmllib
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent

SEARCH_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
FETCH_UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
            "polite crawler; contact via GitHub issues)")

GAP = 1.0
_lock = threading.Lock()
_host_at: dict[str, float] = {}

ATS = ("zhiye.com", "hotjob.cn", "mokahr.com", "myworkdayjobs.com", "feishu.cn",
       "mioffice.cn", "italent.cn", "hcmcloud.cn", "beisen.com", "knx.com.cn",
       "career.site", "163.com", "liepin.com.cn")

# 明确不能当官方入口的域（转载 / 平台 / UGC / 百科）
BAD_HOST = re.compile(
    r"(\.edu\.cn|gxrc|gaoxiaojob|chinajob|offcn|gwy\.com|aiqicha|baike\.|zhuanlan\.|"
    r"sohu\.com|163\.com$|news\.|zhihu|weibo|douban|toutiao|csdn|jianshu|wiki|eastmoney|"
    r"zhaopin\.com|51job|liepin\.com$|zhipin\.com|nowcoder|kanzhun|yingjiesheng|shixiseng|jobui|dajie|"
    r"xujc\.com|xidian|nankai|sjtu|hdu\.edu)", re.I)

BLOCK_MARK = re.compile(r"验证码|安全验证|人机验证|captcha|请先登录|访问受限", re.I)


def throttle(host: str) -> None:
    with _lock:
        now = time.monotonic()
        at = max(now, _host_at.get(host, 0.0) + GAP)
        _host_at[host] = at
    if at > now:
        time.sleep(at - now)


def bing(q: str, count: int = 20) -> list[tuple[str, str]]:
    out = []
    throttle("cn.bing.com")
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": SEARCH_UA}, follow_redirects=True) as c:
            r = c.get("https://cn.bing.com/search",
                      params={"q": q, "ensearch": "0", "count": str(count)})
    except Exception:
        return out
    if r.status_code != 200:
        return out
    for m in re.finditer(r"<h2[^>]*>(.*?)</h2>", r.text, re.S):
        blk = m.group(1)
        hm = re.search(r'href="(https?://[^"]+)"', blk)
        if not hm:
            continue
        title = htmllib.unescape(re.sub(r"<[^>]+>", "", blk)).strip()
        out.append((hm.group(1), title))
    return out


def bare(url: str) -> str:
    u = urlsplit(url)
    return urlunsplit((u.scheme, u.netloc, u.path, "", ""))


def check(url: str) -> dict | None:
    h = (urlsplit(url).hostname or "").lower()
    if not h:
        return None
    throttle(h)
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": FETCH_UA}, follow_redirects=True) as c:
            r = c.get(url)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    text = r.text[:4000]
    if BLOCK_MARK.search(text):
        return {"url": str(r.url), "status": 200, "blocked": True, "title": ""}
    m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S | re.I)
    title = htmllib.unescape(m.group(1)).strip() if m else ""
    return {"url": str(r.url), "status": 200, "blocked": False, "title": title,
            "size": len(r.content)}


def brands_for(name: str, brands: dict) -> list[str]:
    """brands.json 形如 {公司全名: [品牌变体, ...]}。"""
    b = brands.get(name) or []
    if isinstance(b, dict):
        b = b.get("variants") or b.get("brands") or []
    out = [name] + list(b)
    seen, res = set(), []
    for x in out:
        x = str(x).strip()
        if x and x not in seen and 2 <= len(x) <= 20:
            seen.add(x)
            res.append(x)
    return res[:5]


def tokens_for(name: str, brands: dict) -> list[str]:
    """公司名 → 英文/拼音 token（用于硬闸：域名必须含 token）。

    只要长度 ≥4 的 token，避免 `yx`/`sy`/`dr` 这种两个字母在任意域名里都能命中。
    变体里「只剩行业词」的（如「中国银行」→「银行」）直接丢掉，否则会把
    `bank-of-anything.com` 都算成命中。
    """
    from pypinyin import Style, lazy_pinyin
    GENERIC = re.compile(r"^(银行|石油|石化|集团|科技|技术|电子|汽车|药业|医药|证券|保险|"
                         r"地产|置业|食品|饮料|电器|通信|能源|电力|钢铁|建筑|物流|传媒)$")
    toks = set()
    for b in brands_for(name, brands):
        b = GENERIC.sub("", b) or b
        if len(b) < 2:
            continue
        # 纯英文品牌（ABB / IBM / GE）：短也认，因为它们是唯一标识
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9\-&\. ]{0,20}", b.strip()):
            toks.add(re.sub(r"[^a-z0-9]", "", b.lower()))
            continue
        for m in re.finditer(r"[A-Za-z][A-Za-z0-9]{2,}", b):
            toks.add(m.group(0).lower())
        cs = [c for c in b if "\u4e00" <= c <= "\u9fa5"]
        if cs:
            toks.add("".join(lazy_pinyin(cs, style=Style.NORMAL)))
            # 去掉地域前缀后的拼音（中国石油→shiyou、北京银行→yinhang 会被 GENERIC 挡掉）
            rest = re.sub(r"^(中国|中华|北京|上海|广州|深圳|天津|重庆|浙江|江苏|山东|广东)", "", b)
            if rest and len(rest) >= 2 and not GENERIC.match(rest):
                toks.add("".join(lazy_pinyin([c for c in rest if "\u4e00" <= c <= "\u9fa5"],
                                             style=Style.NORMAL)))
    # 拼音 token 要求 ≥4 字母（防 `yx`/`sy` 到处命中）；纯英文品牌 ≥2 字母
    return sorted({t for t in toks if (all(ch.isascii() for ch in t) and len(t) >= 2)
                   or len(t) >= 4}, key=len, reverse=True)


def work(item: dict, brands: dict) -> dict:
    company = item["company"]
    sector = item.get("sector", "")
    toks = tokens_for(company, brands)
    alts = brands_for(company, brands)
    cands: dict[str, str] = {}
    queries = []
    for b in alts[:3]:
        queries.append(f"{b} 招聘官网")
        queries.append(f"{b} 校园招聘")
    seen_q = set()
    for q in queries:
        if q in seen_q:
            continue
        seen_q.add(q)
        for url, title in bing(q):
            h = (urlsplit(url).hostname or "").lower()
            if BAD_HOST.search(h):
                continue
            flat_host = re.sub(r"[^a-z0-9]", "", h)
            flat_path = re.sub(r"[^a-z0-9]", "", (urlsplit(url).path or "").lower())
            # 硬闸：域名或路径必须含本案公司的 token，否则不收
            if not any(t in flat_host or t in flat_path for t in toks):
                continue
            u = bare(url)
            if u not in cands:
                cands[u] = title
        if len(cands) >= 4:
            break

    best = None
    for u in list(cands)[:6]:
        r = check(u)
        if not r or r.get("blocked"):
            continue
        # 再次确认落地域名仍含 token（防跳转到别家）
        fh = re.sub(r"[^a-z0-9]", "", (urlsplit(r["url"]).hostname or "").lower())
        if not any(t in fh for t in toks):
            continue
        is_ats = any((urlsplit(r["url"]).hostname or "").endswith(a) for a in ATS)
        scored = (2 if is_ats else 1, r.get("size", 0))
        if best is None or scored > best[0]:
            best = (scored, r, u)

    if not best:
        return {"company": company, "sector": sector, "best": None, "retry": True,
                "reason": "no_own_domain_candidate", "tokens": toks, "alts": alts}
    _s, r, u = best
    return {"company": company, "sector": sector, "tokens": toks, "alts": alts, "retry": True,
            "best": {"url": r["url"], "title": r.get("title", ""), "size": r.get("size", 0),
                     "status": 200},
            "reason": "retry_ok"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default="work/careers_retry.jsonl")
    args = ap.parse_args()

    brands_p = ROOT / "work/brands.json"
    brands = json.loads(brands_p.read_text(encoding="utf-8")) if brands_p.exists() else {}
    if isinstance(brands, list):
        brands = {b["name"]: b for b in brands}

    t = yaml.safe_load((ROOT / "targets/top_companies.yaml").read_text(encoding="utf-8"))
    targets = []
    for sec, lst in (t.get("sectors") or {}).items():
        for c in lst:
            targets.append({"company": c, "sector": sec})
    # 已经被「可用池」覆盖的公司不用再补；只补真正缺的
    have: set[str] = set()
    for f in ("work/entry_usable.jsonl", "work/entry_pool.jsonl"):
        p = ROOT / f
        if p.exists():
            for s in p.read_text(encoding="utf-8").splitlines():
                if s.strip():
                    have.add(json.loads(s)["company"])
    todo = [x for x in targets if x["company"] not in have]

    out = ROOT / args.out
    done = set()
    if out.exists():
        done = {json.loads(s)["company"] for s in out.read_text(encoding="utf-8").splitlines() if s.strip()}
    todo = [x for x in todo if x["company"] not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"targets={len(targets)} missing={len(targets)-len(have)} todo={len(todo)}", file=sys.stderr)

    n, ok, t0 = 0, 0, time.time()
    with open(out, "a", encoding="utf-8") as fh, ThreadPoolExecutor(args.workers) as ex:
        for rec in ex.map(lambda x: work(x, brands), todo):
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            n += 1
            ok += 1 if rec.get("best") else 0
            if n % 10 == 0:
                print(f"[{n}/{len(todo)}] ok={ok} {n/max(time.time()-t0,1)*60:.1f}/min", file=sys.stderr)
    print(f"done {n} ok={ok} in {time.time()-t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
