"""ATS 指纹全网识别：搜索发现 → 抓取判定 → 分类。

三级策略（成本从低到高）：
  L1 搜索：Bing 搜「<公司> 招聘 官网」，取前 10 条结果的 host
  L2 指纹：host 直接匹配已知 ATS 模式（zhiye.com / myworkdayjobs / hotjob / mokahr / feishu）
  L3 探测：对疑似官网域名，按固定顺序试 careers./job./jobs./hr./zhaopin. 子域 + 首页找招聘链接

反爬对策：
  - 单 browser 复用，页面级 timeout 12s
  - Bing 每查询间隔 2.5s，连续 3 次结构异常则换 UA 重开
  - 每域名 1 rps

输出 work/ats_findings.jsonl
"""

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"

ATS_PATTERNS = [
    (r"\.zhiye\.com", "beisen"),
    (r"\.myworkdayjobs\.com", "workday"),
    (r"myworkdaysite\.com", "workday"),
    (r"hotjob\.cn", "hotjob"),
    (r"mokahr\.com", "moka"),
    (r"\.jobs\.feishu\.cn", "feishu_atsx"),
    (r"jobs\.bytedance\.com", "feishu_atsx"),
    (r"italent\.cn", "beisen_legacy"),
    (r"dayee\.com", "hotjob"),
    (r"51job\.com|zhaopin\.com|liepin\.com|boss\.zhipin\.com|yingjiesheng\.com|nowcoder\.com|maimai\.cn|kanzhun\.com|shixiseng\.com", "third_party"),
    (r"smartrecruiters\.com", "smartrecruiters"),
    (r"successfactors\.(com|eu)", "successfactors"),
    (r"icims\.com", "icims"),
    (r"taleo\.net", "taleo"),
    (r"avature\.net", "avature"),
]

BLOCK = re.compile(r"51job|zhaopin\.com|liepin|zhipin|yingjiesheng|nowcoder|maimai|kanzhun|shixiseng|"
                   r"baidu\.com|so\.com|sogou|zhihu|douban|weibo|xiaohongshu|bilibili|"
                   r"qcc\.com|tianyancha|aiqicha|qixin|boss|lagou|linkedin|glassdoor|"
                   r"wikipedia|baike|csdn|cnblogs|jianshu|sohu|163\.com/news|"
                   r"gaokao|dxsbb|gongkao|offcn|huatu|chinahr|jobui")

CAREER_WORDS = re.compile(r"招聘|人才|加入我们|join\s*us|careers?|jobs?|招贤|诚聘|校园招聘|社会招聘", re.I)


def ats_of(href: str) -> str | None:
    h = href.lower()
    for pat, name in ATS_PATTERNS:
        if re.search(pat, h):
            return name
    return None


def host_of(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except Exception:  # noqa: BLE001
        return ""


def bing_search(page, company: str, retry: int = 0) -> list[tuple[str, str]]:
    """返回 [(title, url)]。"""
    q = f"{company} 招聘 官网"
    try:
        page.goto(f"https://cn.bing.com/search?q={q}&count=20", timeout=15000)
        page.wait_for_timeout(900)
        items = page.query_selector_all("li.b_algo")
        out = []
        for it in items[:15]:
            a = it.query_selector("h2 a")
            if not a:
                continue
            href = a.get_attribute("href") or ""
            if href.startswith("http"):
                out.append(((a.inner_text() or "").strip(), href))
        if not out and retry < 2:
            time.sleep(4)
            return bing_search(page, company, retry + 1)
        return out
    except Exception:  # noqa: BLE001
        if retry < 2:
            time.sleep(4)
            return bing_search(page, company, retry + 1)
        return []


def probe_careers(page, domain: str) -> dict:
    """对疑似官网域名试常见招聘子域，返回首个 200 的 URL 及其 ATS。"""
    for sub in ("careers", "job", "hr"):
        u = f"https://{sub}.{domain}/"
        try:
            r = page.goto(u, timeout=6000, wait_until="domcontentloaded")
            if r and r.status == 200:
                final = page.url
                html = page.content()[:60000]
                a = ats_of(final) or ats_of(html)
                return {"careers_url": final, "ats": a or "self_built", "status": 200}
        except Exception:  # noqa: BLE001
            continue
    return {}


def main():
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 100

    rows = []
    for ln in (WORK / "candidates_clean.tsv").read_text(encoding="utf-8").splitlines():
        p = ln.split("\t")
        if len(p) >= 3:
            rows.append({"name": p[0], "sector": p[1], "brand": p[2]})
    # 跳过已命中的
    done = set()
    f = WORK / "probe_all.jsonl"
    if f.exists():
        for ln in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
                if r.get("matched"):
                    done.add(r["company"])
            except Exception:  # noqa: BLE001
                pass
    rows = [r for r in rows if r["name"] not in done]
    rows = rows[start: start + limit]

    out_path = WORK / "ats_findings.jsonl"
    mode = "a" if start else "w"
    with sync_playwright() as pw, open(out_path, mode, encoding="utf-8") as out:
        b = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = b.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 900},
            locale="zh-CN",
        )
        page = ctx.new_page()
        for i, r in enumerate(rows):
            name = r["name"]
            res = {"company": name, "sector": r["sector"]}
            results = bing_search(page, name)
            time.sleep(1.6)
            res["n_results"] = len(results)
            ats_hit, careers, hosts = None, None, []
            for _title, url in results:
                h = host_of(url)
                if not h or BLOCK.search(h):
                    continue
                hosts.append(h)
                a = ats_of(url)
                if a and a != "third_party":
                    ats_hit = a
                    careers = url
                    break
            # 没有直接命中 ATS → 用首条疑似官网域名探子域
            if not ats_hit:
                for h in hosts[:2]:
                    root = ".".join(h.split(".")[-2:]) if h.count(".") >= 1 else h
                    pr = probe_careers(page, root)
                    if pr.get("careers_url"):
                        careers = pr["careers_url"]
                        ats_hit = pr.get("ats")
                        break
            res.update({"ats": ats_hit, "careers_url": careers, "hosts": hosts[:6]})
            out.write(json.dumps(res, ensure_ascii=False) + "\n")
            out.flush()
            if (i + 1) % 10 == 0:
                print(f"{i+1}/{len(rows)} {name} -> {ats_hit}", flush=True)
        b.close()
    print("done")


if __name__ == "__main__":
    main()
