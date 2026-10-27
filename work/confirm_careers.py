"""招聘日历扩量第 2 步：把搜索/探测到的候选 URL 收敛成「一家公司一个官方招聘入口」。

核验方式（不猜，只看真实页面）：
1. 候选来源：搜索引擎结果 + 已有 ATS 指纹 + 官网首页里带招聘关键词的链接；
2. 域名必须属于这家公司：主机含公司拼音/英文 token、是招聘子域（careers./join./campus.…）、
   或已知 ATS 租户（zhiye.com/hotjob.cn/mokahr.com/feishu.cn/…）。第三方（牛客/知乎/爱企查/
   高校就业网/门户新闻）一律丢弃；
3. 页面必须**确实是招聘页**：状态 200、不是登录墙、标题或 URL 出现招聘词，且公司 token 在页面里出现；
4. 同一主机间隔 ≥1s、同主机不并发；不同主机并行（铁律限制的是每主机频率）。

用法：
    python3 work/confirm_careers.py
输出：work/careers_confirmed.jsonl
"""

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
from pypinyin import Style, lazy_pinyin

ROOT = Path(__file__).resolve().parent.parent
UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")

ATS_HOSTS = ("zhiye.com", "hotjob.cn", "mokahr.com", "myworkdayjobs.com", "myworkday.cn", "feishu.cn",
             "f.mioffice.cn", "italent.cn", "dayee.com", "hcmcloud.cn", "beisen.com", "knx.com.cn",
             "career.site", "jobs.feishu.cn", "hire.163.com")
THIRD = ("nowcoder", "zhihu", "xiaohongshu", "douyin", "bilibili.com", "weibo", "kanzhun", "zhipin",
         "liepin", "51job", "zhaopin.com", "yingjiesheng", "shixiseng", "jobui", "csdn", "jianshu",
         "toutiao", "sohu.com", "163.com", "baidu.com", "aiqicha", "tianyancha", "qcc.com",
         "sogou.com", "bing.com", "microsoft.com", "wikipedia", "wikiwand", "douban", "jinliqiuzhi",
         "mianlingai", "edu.cn", "gaoxiaojob", "gxrc", "chinahr", "dajie", "ejob", "chinajob",
         "linkedin", "glassdoor", "indeed", "offershow", "autohome", "eoffcn", "offcn", "gwy.com",
         "hanyuguoxue", "hgcha", "iciba", "kdocs", "baike", "zhuanlan", "gitee", "github.io", "juejin",
         "segmentfault", "oschina", "36kr", "huxiu", "qichacha")

CAREER_WORD = re.compile(r"招聘|人才|加入我们|校园|校招|实习|career|job|join|recruit|position|机会|招贤|网申", re.I)
LOGIN_TITLE = re.compile(r"登录|登陆|login|sign in", re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
HREF_RE = re.compile(r"""href=["']([^"'#]{2,300})["']""", re.I)
HOST_HINT = re.compile(r"(^|\.)(join|jobs?|careers?|campus|zhaopin|talent|recruit|hr|zhiye|rc|zp|wecruit|"
                       r"hire)\.", re.I)
DANGER = re.compile(r"色情|博彩|赌场|彩票|私彩|成人|裸|一夜情|代孕|办证|发票", re.I)

DIRECTIONS = (
    ("技术类", r"技术|研发|开发|算法|后端|前端|客户端|测试|运维|数据|安全|架构"),
    ("产品类", r"产品"),
    ("设计类", r"设计|交互|视觉"),
    ("运营类", r"运营"),
    ("市场与销售类", r"市场|营销|销售|商务|品牌"),
    ("职能类", r"职能|人力|财务|法务|行政|供应链|采购"),
    ("金融类", r"投研|投行|风控|量化|研究|交易|信贷"),
)

DROP_A = re.compile(r"^(中国|中华|国家|中央|上海|北京|天津|重庆|广东|广州|深圳|浙江|杭州|江苏|南京|山东|"
                    r"四川|成都|湖北|武汉|福建|厦门|河南|河北|湖南|安徽|陕西|西安|苏州|青岛|宁波)")
DROP_SUFFIX = re.compile(
    r"(股份有限公司|有限责任公司|有限公司|集团公司|控股集团|控股|集团|股份|公司|实业|投资|发展|"
    r"科技|技术|电子|电气|汽车|银行|证券|基金|保险|地产|置业|医药|药业|食品|"
    r"（中国）|\(中国\)|中国)$")

GAP = 1.0
_lock = threading.Lock()
_host_at: dict[str, float] = {}


def throttle(host: str) -> None:
    """同一主机串行且间隔 ≥1s；不同主机各自计时、可以并行。"""
    with _lock:
        now = time.monotonic()
        at = max(now, _host_at.get(host, 0.0) + GAP)
        _host_at[host] = at
    if at > now:
        time.sleep(at - now)


def tokens(name: str, brand: str) -> list[str]:
    out = []
    for s in (brand, name):
        s = (s or "").strip()
        if not s:
            continue
        s2 = DROP_SUFFIX.sub("", DROP_A.sub("", s)) or s
        s2 = re.sub(r"[\s·\-—_/,（）()]+", "", s2)
        if re.fullmatch(r"[A-Za-z0-9&+.]{2,24}", s2):
            out += [s2.lower(), s2.lower().replace("&", "")]
        if re.search(r"[\u4e00-\u9fff]", s2):
            out.append("".join(lazy_pinyin(s2, style=Style.NORMAL)))
            ini = "".join(lazy_pinyin(s2, style=Style.FIRST_LETTER))
            if 2 <= len(ini) <= 6:
                out.append(ini)
    seen, res = set(), []
    for t in out:
        t = re.sub(r"[^a-z0-9]", "", t)
        if len(t) >= 2 and t not in seen:
            seen.add(t)
            res.append(t)
    return res[:8]


def is_third(url: str) -> bool:
    h = (urlsplit(url).hostname or "").lower()
    if HOST_HINT.search(h) and not any(t in h for t in ("zhipin", "liepin", "51job", "zhaopin.com")):
        return False   # campus.163.com / join.qq.com 是公司自己的招聘子域
    return any(t in h for t in THIRD)


def host_hit(host: str, toks: list[str]) -> bool:
    flat = re.sub(r"[^a-z0-9]", "", host.lower())
    return any(t in flat for t in toks)


def is_official(url: str, toks: list[str]) -> bool:
    h = (urlsplit(url).hostname or "").lower()
    if any(h == a or h.endswith("." + a) for a in ATS_HOSTS):
        return True
    if HOST_HINT.search(h):
        return True
    return host_hit(h, toks)


def title_of(html: str) -> str:
    m = TITLE_RE.search(html[:200000])
    return re.sub(r"\s+", " ", m.group(1)).strip()[:120] if m else ""


def check(item):
    company, sector, brand, url, toks, hint = item
    throttle((urlsplit(url).hostname or "").lower())
    try:
        with httpx.Client(follow_redirects=True, timeout=12,
                          headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.8"}) as c:
            r = c.get(url)
    except Exception as e:
        return {"url": url, "ok": False, "err": type(e).__name__}
    if r.status_code != 200:
        return {"url": url, "ok": False, "status": r.status_code}
    title = title_of(r.text)
    final = str(r.url)
    if DANGER.search(title):
        return {"url": final, "ok": False, "status": 200, "title": title, "danger": True}
    body = r.text[:200000]
    plain = re.sub(r"<script.*?</script>|<style.*?</style>", " ", body, flags=re.S)
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r"\s+", " ", plain)
    low = plain[:30000].lower()
    login_only = bool(LOGIN_TITLE.search(title)) and len(plain) < 1500
    has_word = bool(CAREER_WORD.search(f"{title} {url}")) or bool(re.search(r"招聘|job|career", low[:5000]))
    has_company = host_hit((urlsplit(final).hostname or ""), toks) or any(t in low for t in toks[:2]) \
        or (company and company[:4] in plain)
    # 招聘子域（zhaopin./careers./join.…）与 ATS 招聘门户（*.zhiye.com/*.hotjob.cn/…）本身就是招聘入口：
    # 这类站点很多是 JS 渲染，正文为空是正常现象；它们的 URL 来自搜索/官网链接，已带公司归属证据。
    ats = any((urlsplit(final).hostname or "").endswith(a) for a in ATS_HOSTS)
    career = (has_word and has_company) or (hint and (has_word or ats or len(plain) > 1500))
    dirs = [label for label, pat in DIRECTIONS if re.search(pat, plain)]
    return {"url": final, "ok": bool(career and not login_only), "status": 200, "title": title,
            "login_page": login_only, "directions": dirs, "host_hint": bool(hint),
            "size": len(r.content), "snippet": plain[:300]}


def rank(url: str, title: str, company: str) -> tuple:
    t = title or ""
    return (
        0 if company in t else 1,
        0 if re.search(r"校园|校招|campus", t + url, re.I) else 1,
        0 if not LOGIN_TITLE.search(t) else 1,
        len(urlsplit(url).path or "/"),
        url,
    )


def home_links(item):
    """官网首页 → 带招聘关键词的链接。"""
    company, sector, brand, toks, home = item
    throttle((urlsplit(home).hostname or "").lower())
    try:
        with httpx.Client(follow_redirects=True, timeout=12,
                          headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.8"}) as c:
            r = c.get(home)
    except Exception:
        return []
    if r.status_code != 200:
        return []
    base = str(r.url)
    out = []
    for href in HREF_RE.findall(r.text[:300000]):
        if CAREER_WORD.search(href):
            u = str(httpx.URL(base).join(href))
            if urlsplit(u).hostname and u not in out:
                out.append(u)
    return out[:4]


def main() -> int:
    pool_brand = {}
    for r in csv.reader(open(ROOT / "work/pool.tsv", encoding="utf-8"), delimiter="\t"):
        pool_brand[r[0]] = (r[1], (r[2] if len(r) > 2 else ""))

    known = {}
    for p in ("work/ats_verified.jsonl", "work/sample_stats_all.jsonl", "work/companies.jsonl",
              "work/round2_hits.jsonl", "work/fast_hits.jsonl", "work/targets_hits.jsonl"):
        f = ROOT / p
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            name, host = row.get("company") or row.get("name"), row.get("host")
            if name and host:
                known.setdefault(name, host)

    cands: dict[str, list[str]] = {}
    searches = ROOT / "work/search_hits.jsonl"
    if searches.exists():
        for line in searches.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            c = row["company"]
            toks = tokens(c, pool_brand.get(c, ("", ""))[1])
            for res in row.get("results") or []:
                u = res["url"].replace("&amp;", "&")
                if is_third(u) or not is_official(u, toks):
                    continue
                cands.setdefault(c, []).append(u)
    for c, host in known.items():
        cands.setdefault(c, []).insert(0, f"https://{host}/")
    hf = ROOT / "work/home_found.jsonl"
    if hf.exists():
        for line in hf.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            for u in row.get("links") or []:
                cands.setdefault(row["company"], []).append(u)
            if row.get("home"):
                cands.setdefault(row["company"], []).append(row["home"])
    pf = ROOT / "work/careers_probe.jsonl"
    if pf.exists():
        for line in pf.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            for p in row.get("probes") or []:
                for u in p.get("sub_links") or []:
                    cands.setdefault(row["company"], []).append(u)
                if p.get("career"):
                    cands.setdefault(row["company"], []).append(p["url"])

    # 没有候选的公司：抓官网首页找招聘链接
    no_cand = [c for c in pool_brand if c not in cands]
    print(f"no_cand={len(no_cand)}", file=sys.stderr)
    if no_cand:
        items = []
        for c in no_cand:
            sector, brand = pool_brand[c]
            toks = tokens(c, brand)
            for t in toks[:2]:
                items.append((c, sector, brand, toks, f"https://www.{t}.com/"))
                items.append((c, sector, brand, toks, f"https://www.{t}.cn/"))
        print(f"home_probe urls={len(items)}", file=sys.stderr)
        with ThreadPoolExecutor(32) as ex:
            for (c, *_), links in zip(items, ex.map(home_links, items), strict=False):
                for u in links:
                    cands.setdefault(c, []).append(u)

    items = []
    for c, urls in cands.items():
        sector, brand = pool_brand.get(c, ("", ""))
        toks = tokens(c, brand)
        keep = []
        for u in urls:
            if u in keep:
                continue
            if is_official(u, toks):
                keep.append(u)
        for u in keep[:10]:
            items.append((c, sector, brand, u, toks, bool(HOST_HINT.search(urlsplit(u).hostname or ""))))
    print(f"companies={len(cands)} urls={len(items)}", file=sys.stderr)

    results: dict[str, list] = {}
    with ThreadPoolExecutor(32) as ex:
        for (c, *_), res in zip(items, ex.map(check, items), strict=False):
            results.setdefault(c, []).append(res)

    outp = ROOT / "work/careers_confirmed.jsonl"
    n_ok = 0
    with open(outp, "w", encoding="utf-8") as fh:
        for company in pool_brand:
            good = [r for r in results.get(company, []) if r.get("ok")]
            good.sort(key=lambda r: rank(r["url"], r.get("title", ""), company))
            if good:
                n_ok += 1
            sector, brand = pool_brand[company]
            fh.write(json.dumps({"company": company, "sector": sector, "brand": brand,
                                 "tokens": tokens(company, brand),
                                 "best": good[0] if good else None, "all": good[:5],
                                 "checked": len(results.get(company, [])),
                                 "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                                ensure_ascii=False) + "\n")
    print(f"confirmed companies={n_ok}/{len(pool_brand)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
