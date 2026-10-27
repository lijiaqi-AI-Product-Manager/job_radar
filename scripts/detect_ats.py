"""识别一批域名的招聘站用的是哪家 ATS，并给出「能不能接」的初判。

为什么单独写：覆盖率瓶颈不是「某家公司的岗位抓不抓得到」，而是**它用哪个 ATS**
（见 docs/internal/COVERAGE-PLAN.md §4）。一个适配器 = 几十家公司。
所以每轮扩源的第一步应该是「批量识别平台」，而不是「逐家读页面」。

识别只靠**公开静态特征**：
  ① 域名本身就是平台（`*.zhiye.com` / `*.mokahr.com` / `*.jobs.feishu.cn` …）；
  ② 首页跳转后的最终 URL；
  ③ HTML 里的平台指纹（`careers.danone.com.cn` 的 `avature` JS、Workday 的 `myworkdayjobs` …）。

**本脚本不下判断「能接」，只给线索**：命中平台后再去读该平台的 robots 与接口形态。
这样「扫描」和「合规判定」两件事分开，前者可以放心批量跑。

用法：
    uv run python scripts/detect_ats.py --file domains.txt --out /tmp/ats.json
    uv run python scripts/detect_ats.py https://career.example.com
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import httpx

UA = "jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; ats detect)"

# ① 域名级平台：命中即确定，不用看内容
DOMAIN_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\.zhiye\.com$"), "beisen"),
    (re.compile(r"\.mokahr\.com$"), "moka"),
    (re.compile(r"\.jobs\.feishu\.cn$"), "feishu_atsx"),
    (re.compile(r"\.hotjob\.cn$"), "hotjob"),
    (re.compile(r"\.myworkdayjobs\.com$"), "workday"),
    (re.compile(r"\.workday\.com$"), "workday"),
    (re.compile(r"\.icims\.com$"), "icims"),
    (re.compile(r"\.taleo\.net$"), "taleo"),
    (re.compile(r"\.successfactors\.(com|eu)$"), "successfactors"),
    (re.compile(r"\.smartrecruiters\.com$"), "smartrecruiters"),
    (re.compile(r"\.greenhouse\.io$"), "greenhouse"),
    (re.compile(r"\.lever\.co$"), "lever"),
    (re.compile(r"\.gllue\.com$"), "gllue"),
    (re.compile(r"\.dayee\.com$|\.dayee\.cn$"), "dayee"),
    (re.compile(r"\.italent\.cn$"), "italent"),
    (re.compile(r"\.51job\.com$|\.51jobcdn\.com$"), "51job"),
    (re.compile(r"\.zhaopin\.com$"), "zhaopin"),
    (re.compile(r"\.liepin\.com$"), "liepin"),
    (re.compile(r"\.lagou\.com$"), "lagou"),
    (re.compile(r"\.nowcoder\.com$"), "nowcoder"),
    (re.compile(r"\.careerqia\.com$"), "careerqia"),
    (re.compile(r"\.jobsqb\.com$"), "jobsqb"),
    (re.compile(r"\.avature\.net$"), "avature"),
    (re.compile(r"\.eightfold\.ai$|\.pcsx\.(?:com|io)$"), "eightfold"),
    (re.compile(r"\.phenompeople\.com$|\.phenom\.cloud$"), "phenom"),
    (re.compile(r"\.radancy\.(?:com|net)$"), "radancy"),
    (re.compile(r"\.tal\.net$"), "tal"),
    (re.compile(r"\.jobvite\.com$"), "jobvite"),
    (re.compile(r"\.brassring\.com$"), "brassring"),
    (re.compile(r"\.ultipro\.com$"), "ultipro"),
    (re.compile(r"\.recruitee\.com$"), "recruitee"),
    (re.compile(r"\.personio\.(?:de|com)$"), "personio"),
]

# ③ 内容指纹：只放**平台独有**的字符串，避免 `jobs`/`career` 这类通用词误判
BODY_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"avature|AvaturePortal|SearchJobs", re.I), "avature"),
    (re.compile(r"myworkdayjobs|workdaycdn|data-automation-id=\"jobPosting\"", re.I), "workday"),
    (re.compile(r"GetJobAdPageList|zhiye\.com/", re.I), "beisen"),
    (re.compile(r"mokahr|moka-|ats-apply/website", re.I), "moka"),
    (re.compile(r"feishu\.cn/api/v1/search/job/posts|atsx", re.I), "feishu_atsx"),
    (re.compile(r"hotjob\.cn|wecruit", re.I), "hotjob"),
    (re.compile(r"gllue", re.I), "gllue"),
    (re.compile(r"dayee\.(?:com|cn)", re.I), "dayee"),
    (re.compile(r"eightfold|pcsx", re.I), "eightfold"),
    (re.compile(r"phenompeople|phenom\.cloud", re.I), "phenom"),
    (re.compile(r"radancy|TMPW|talentbrew", re.I), "radancy"),
    (re.compile(r"smartrecruiters", re.I), "smartrecruiters"),
    (re.compile(r"icims", re.I), "icims"),
    (re.compile(r"taleo", re.I), "taleo"),
    (re.compile(r"successfactors|jobs2web", re.I), "successfactors"),
    (re.compile(r"greenhouse\.io|boards-api", re.I), "greenhouse"),
    (re.compile(r"lever\.co/postings", re.I), "lever"),
]


def host_of(url: str) -> str:
    u = httpx.URL(url if "://" in url else f"https://{url}")
    return (u.host or "").lower()


def from_domain(host: str) -> str | None:
    for pat, name in DOMAIN_RULES:
        if pat.search(host):
            return name
    return None


def from_body(html: str) -> str | None:
    # 只看前 400KB：有的站内嵌了巨大的 base64 头像，扫全文没意义
    head = html[:400_000]
    for pat, name in BODY_RULES:
        if pat.search(head):
            return name
    return None


def probe(client: httpx.Client, url: str) -> dict:
    """一次 GET，返回 {input, final, status, platform, via, title}。失败也给行，不抛。"""
    out: dict = {"input": url, "final": None, "status": None, "platform": None, "via": None, "title": ""}
    try:
        r = client.get(url if "://" in url else f"https://{url}")
    except Exception as e:  # noqa: BLE001 — 批量扫描里单条失败正常
        out["error"] = type(e).__name__
        return out
    out["final"] = str(r.url)
    out["status"] = r.status_code
    m = re.search(r"<title[^>]*>(.{0,120}?)</title>", r.text, re.S | re.I)
    if m:
        out["title"] = re.sub(r"\s+", " ", m.group(1)).strip()

    # 跳转后的域名优先（很多公司把 careers 域名 CNAME 到平台）
    if (p := from_domain(host_of(str(r.url)))):
        out["platform"], out["via"] = p, "redirect-host"
        return out
    if (p := from_domain(host_of(url))):
        out["platform"], out["via"] = p, "input-host"
        return out
    if r.status_code == 200 and (p := from_body(r.text)):
        out["platform"], out["via"] = p, "body"
    return out


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--file", help="一行一个域名/URL")
    ap.add_argument("--out", help="结果 JSON")
    ap.add_argument("--workers", type=int, default=4, help="并发数（默认 4，别开大）")
    args = ap.parse_args()

    targets = list(args.urls)
    if args.file:
        targets += [ln.strip() for ln in Path(args.file).read_text(encoding="utf-8-sig").splitlines()
                    if ln.strip() and not ln.strip().startswith("#")]
    if not targets:
        ap.error("至少给一个 URL 或 --file")

    from concurrent.futures import ThreadPoolExecutor

    def one(u: str) -> dict:
        # 每个线程自己的 client：httpx.Client 不是线程安全的
        with httpx.Client(headers={"User-Agent": UA}, timeout=httpx.Timeout(12, connect=6),
                          follow_redirects=True) as c:
            return probe(c, u)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(one, targets))

    by_platform: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_platform[r["platform"] or "(unknown)"].append(r)

    print(f"{'平台':22s} {'数量':>4s}")
    for k, v in sorted(by_platform.items(), key=lambda kv: -len(kv[1])):
        print(f"{k:22s} {len(v):4d}")
    print(f"\n共 {len(rows)} 个入口，{sum(1 for r in rows if r['platform'])} 个识别出平台",
          file=sys.stderr)

    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"-> {args.out}", file=sys.stderr)
    # 明细打到 stdout（按平台分组），方便直接看
    for k, v in sorted(by_platform.items(), key=lambda kv: -len(kv[1])):
        if k == "(unknown)":
            continue
        print(f"\n## {k}（{len(v)}）")
        for r in v:
            print(f"  {r['status']}  {r['input'][:60]:60s} -> {r['platform']} ({r['via']}) {r['title'][:30]}")
    return 0
