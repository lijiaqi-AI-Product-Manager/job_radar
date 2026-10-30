"""招聘日历扩量：为候选池里的每家公司发现「官方招聘入口」（公开、免登录）。

为什么需要这一步：用户 2026-10-26 把验收口径改成**日历条目**（集团/具体公司/届次/项目类型/
方向/网申时间/城市/投递入口/来源/时间戳），JD 有无不是门槛。按「能抓到 JD」只有 122 家，
按「有公开官方招聘入口」则绝大多数知名企业都够格——只是入口在哪个域名需要逐家确认。

红线（docs/DEVELOPMENT.md）：只访问公开免登录页面；UA 用项目固定 UA，不伪装浏览器；全局 ≤1 请求/秒；
同一主机不并发；不猜品牌域名（只从公司名本身的拼音/英文推，推不中就跳过，绝不乱撞别家站点）。

做法（每个候选 URL 一个独立任务，全局节流，跨公司并行）：
1. 已知 ATS 站点（work/ats_verified.jsonl 实测能抓到岗位的）直接当命中；
2. 官网首页 https://www.{slug}.com|cn|com.cn/ → 找 href 带 招聘/人才/加入我们/careers/join/jobs 的链接；
3. 常见招聘子域 join./jobs./hr./careers./campus./zhaopin./talent./recruit./zhiye./rc./zp. + 主域；
4. 北森 {slug}.zhiye.com/、大易 {slug}.hotjob.cn（首页即岗位列表，公开可访问）。

用法：
    python3 work/discover_careers.py --round 1       # 第 1 轮：官网首页 + 已知 ATS
    python3 work/discover_careers.py --round 2       # 第 2 轮：子域 + 北森/大易门户
输出：work/careers_found.jsonl（追加，每行一家公司一行结论）
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
from urllib.parse import urljoin, urlsplit

import httpx
from pypinyin import Style, lazy_pinyin

ROOT = Path(__file__).resolve().parent.parent
UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
HREF_RE = re.compile(r"""href=["']([^"'#]{2,300})["']""", re.I)
CAREER_WORD = re.compile(r"招聘|人才|加入我们|校园|校招|实习|careers?|jobs?|join|zhaopin|campus|recruit", re.I)
CAREER_TITLE = re.compile(r"招聘|人才|加入我们|校园|校招|实习|career|job|join|recruit|position|机会", re.I)

SUBDOMAINS = ("join", "jobs", "careers", "hr", "campus", "zhaopin", "talent", "recruit", "zhiye", "job")
DROP_A = re.compile(r"^(中国|中华|国家|中央|上海|北京|天津|重庆|广东|广州|深圳|浙江|杭州|江苏|南京|山东|四川|成都)")
DROP_B = re.compile(
    r"(股份有限公司|有限责任公司|有限公司|集团公司|控股集团|控股|集团|股份|公司|"
    r"实业|投资|发展|科技|技术|电子|电气|汽车|银行|证券|基金|保险|地产|置业|医药|药业|食品|"
    r"（中国）|\(中国\)|中国)$")

GAP = 1.0
_lock = threading.Lock()
_next_at = [0.0]


def throttle() -> None:
    """全局 1 rps：所有主机共享一个闸门（最保守，也最容易解释）。"""
    with _lock:
        now = time.monotonic()
        at = max(now, _next_at[0])
        _next_at[0] = at + GAP
    if at > now:
        time.sleep(at - now)


def get(client: httpx.Client, url: str) -> httpx.Response | None:
    throttle()
    try:
        return client.get(url, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.8"},
                          follow_redirects=True, timeout=10)
    except Exception:
        return None


def title_of(html: str) -> str:
    m = TITLE_RE.search(html[:200000])
    return re.sub(r"\s+", " ", m.group(1)).strip()[:120] if m else ""


def slugify(name: str, brand: str) -> list[str]:
    base = DROP_A.sub("", brand or name)
    base = DROP_B.sub("", base) or base
    stripped = re.sub(r"[\s·\-—_/,（）()]+", "", base) or name
    out = []
    if re.fullmatch(r"[A-Za-z0-9&+]{2,20}", stripped):
        out += [stripped.lower(), stripped.lower().replace("&", "")]
    if re.search(r"[\u4e00-\u9fff]", stripped):
        py = "".join(lazy_pinyin(stripped, style=Style.NORMAL))
        out += [py, py + "hr"]
        ini = "".join(lazy_pinyin(stripped, style=Style.FIRST_LETTER))
        if 2 <= len(ini) <= 8:
            out.append(ini)
    seen, uniq = set(), []
    for s in out:
        s = re.sub(r"[^a-z0-9]", "", s)[:24]
        if len(s) >= 2 and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq[:4]


def is_career_page(url: str, title: str) -> bool:
    return bool(CAREER_TITLE.search(title)) or bool(re.search(r"招聘|校招|careers?|/jobs?|zhaopin", url, re.I))


def round1_targets(company, brand, kb):
    """第 1 轮：已知 ATS 站点 + 官网首页。返回要抓的 URL 列表。"""
    urls = []
    if kb.get("host"):
        urls.append((f"https://{kb['host']}/", "ats"))
    for s in slugify(company, brand):
        urls.append((f"https://www.{s}.com/", "home"))
        urls.append((f"https://www.{s}.cn/", "home"))
        urls.append((f"https://www.{s}.com.cn/", "home"))
    return urls


def round2_targets(company, brand, kb):
    """第 2 轮：招聘子域 + 北森/大易门户。"""
    urls = []
    for s in slugify(company, brand)[:3]:
        for sub in SUBDOMAINS:
            urls.append((f"https://{sub}.{s}.com/", "sub"))
            urls.append((f"https://{sub}.{s}.cn/", "sub"))
        urls.append((f"https://{s}.zhiye.com/", "beisen"))
        urls.append((f"https://{s}.hotjob.cn/", "hotjob"))
    return urls


def job(item):
    """一个探测任务：抓 URL → 判断是否招聘页 → 是首页则再抽出招聘链接候选。"""
    company, sector, brand, url, kind, kb = item
    with httpx.Client(follow_redirects=True, timeout=10, headers={"User-Agent": UA}) as client:
        r = get(client, url)
        if r is None or r.status_code != 200 or len(r.text) < 700:
            return {"company": company, "url": url, "kind": kind, "ok": False,
                    "status": r.status_code if r is not None else None}
        title = title_of(r.text)
        final = str(r.url)
        out = {"company": company, "url": final, "kind": kind, "ok": True, "status": 200, "title": title,
               "career": is_career_page(final, title)}
        # 北森不存在的租户返回 200 + 1228 字节 "Not Found" 页
        if kind == "beisen" and (len(r.text) < 1600 or "not found" in title.lower()):
            out["ok"] = out["career"] = False
            return out
        if kind == "home" and not out["career"]:
            cands = []
            for href in HREF_RE.findall(r.text[:300000]):
                if CAREER_WORD.search(href):
                    u = urljoin(final, href)
                    if urlsplit(u).hostname and u not in cands:
                        cands.append(u)
            out["sub_links"] = cands[:3]
        if kind == "hotjob":
            out["career"] = True  # 大易租户根页是 iframe 壳，标题就是「招聘官网」，界面可用
            out["title"] = title or "招聘官网"
        return out


def load_known() -> dict:
    known = {}
    for p in ("work/ats_verified.jsonl", "work/sample_stats_all.jsonl", "work/companies.jsonl"):
        f = ROOT / p
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            name = row.get("company") or row.get("name")
            if not name:
                continue
            known.setdefault(name, {}).update(
                {k: row.get(k) for k in ("host", "ats", "tenant", "count") if row.get(k)})
    return known


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, default=1, choices=(1, 2))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=40)
    ap.add_argument("--out", default="work/careers_probe.jsonl")
    args = ap.parse_args()

    pool = [(r[0], r[1], (r[2] if len(r) > 2 else "")) for r in
            csv.reader(open(ROOT / "work/pool.tsv", encoding="utf-8"), delimiter="\t")]
    known = load_known()

    done = set()
    outfile = ROOT / args.out
    if outfile.exists():
        for line in outfile.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["company"])
            except Exception:
                pass
    todo = [p for p in pool if p[0] not in done]
    if args.limit:
        todo = todo[:args.limit]

    items = []
    for company, sector, brand in todo:
        kb = known.get(company) or {}
        tgt = round1_targets(company, brand, kb) if args.round == 1 else round2_targets(company, brand, kb)
        seen = set()
        for url, kind in tgt:
            if url not in seen:
                seen.add(url)
                items.append((company, sector, brand, url, kind, kb))
    print(f"companies={len(todo)} urls={len(items)}", file=sys.stderr)

    # 按公司聚合：一家公司的全部 URL 并发抓完再一次性落盘
    from collections import defaultdict
    per_url = defaultdict(list)
    for it in items:
        per_url[it[0]].append(it)

    n = 0
    t0 = time.time()
    with open(outfile, "a", encoding="utf-8") as fh, ThreadPoolExecutor(args.workers) as ex:
        futs = {}
        for company, lst in per_url.items():
            futs[company] = [ex.submit(job, it) for it in lst]
        for company, lst in per_url.items():
            res = [f.result() for f in futs[company]]
            fh.write(json.dumps({"company": company, "sector": lst[0][1], "brand": lst[0][2],
                                 "round": args.round, "probes": res,
                                 "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                                ensure_ascii=False) + "\n")
            fh.flush()
            n += 1
            if n % 20 == 0:
                rate = n / max(time.time() - t0, 1) * 60
                print(f"[{n}/{len(per_url)}] {rate:.1f} 家/分", file=sys.stderr)
    print(f"done {n} in {time.time() - t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
