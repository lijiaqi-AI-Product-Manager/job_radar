"""站内导航：从公司官网首页/招聘频道，找到真正的职位列表页。

D 级（官网首页）和 C 级（招聘介绍页）不是可用的日历入口，但它们是最好的**导航起点**。
这一步抓一次这些页面，提取「招聘 / 职位 / 校园招聘 / 加入我们 / Careers」链接，
再验证目标页确实是职位列表（含职位卡片、职位数、投递按钮等特征），从而升级为 A/B 级。

同时处理 ATS 深链：zhiye.com 只给租户根域、hotjob 只给 host，都补成具体列表页。

红线：同主机 ≤1 req/s；只读公开页面；找不到就保持 D 级（不收录），不硬凑。

用法：
    python3 work/navigate_careers.py [--limit N]
输出：work/entry_upgraded.jsonl（在原 grade 基础上更新 url/grade）
"""

import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hostrules import ATS_HOSTS, usable_as_entry  # noqa: E402

sys.path.insert(0, str(ROOT / "src"))
from jobradar.pipeline.calendar_extract import strip_tags  # noqa: E402

UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, "
      "polite crawler; contact via GitHub issues)")
GAP = 1.0
_lock = threading.Lock()
_host_at: dict[str, float] = {}

LINK_RX = re.compile(
    r"招聘|职位|岗位|校园招聘|校招|加入我们|人才|社会招聘|实习|careers?|jobs?|join|position|recruit|"
    r"zhaopin|campus|opportunit", re.I)
# 职位列表页的特征（出现任一条即可认为"能看到岗位"）
LIST_FEATURE = re.compile(
    r"(职位搜索|职位列表|岗位列表|在招职位|热招职位|全部职位|共\s*\d+\s*个职位|职位名称|"
    r"工作地点|发布时间|投递简历|立即投递|申请职位|search\s+jobs|all\s+jobs|open\s+positions|"
    r"current\s+openings|job\s+search|position\s+list)", re.I)
BLOCK = re.compile(r"验证码|滑块|安全验证|人机验证|captcha|请先登录|Just a moment", re.I)


def throttle(h: str) -> None:
    with _lock:
        now = time.monotonic()
        at = max(now, _host_at.get(h, 0.0) + GAP)
        _host_at[h] = at
    if at > now:
        time.sleep(at - now)


def get(client, url, timeout=15):
    h = (urlsplit(url).hostname or "").lower()
    throttle(h)
    try:
        r = client.get(url, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.8"},
                       follow_redirects=True, timeout=timeout)
    except Exception as e:
        return {"url": url, "status": None, "html": "", "err": type(e).__name__}
    ok = r.status_code == 200
    return {"url": str(r.url), "status": r.status_code, "html": r.text if ok else "",
            "blocked": bool(BLOCK.search(r.text[:3000])) if ok else False}


def score_page(html: str, url: str) -> tuple[int, list[str]]:
    """给一个页面打"是否职位列表页"的分，附证据。"""
    text = strip_tags(html)
    hits = []
    for m in LIST_FEATURE.finditer(text[:200000]):
        w = m.group(0)
        if w not in hits:
            hits.append(w)
    n = len(hits)
    # 职位卡片密度：出现「-上海」「上海」这类地点 + 岗位名的组合
    cards = len(re.findall(r"(工程师|经理|专员|助理|总监|顾问|分析师|实习生|管培生|设计师|研究员|"
                           r"主管|代表|开发|运营|销售|会计|审计|法务|HRBP)", text[:200000]))
    return n * 3 + min(cards, 40), hits[:6]


def candidates_from(html: str, base: str, tokens: list[str] | None = None) -> list[str]:
    """从页面里找「招聘/职位/校园招聘」入口。

    允许跨域，但目标域名必须满足其一：
      a) 同一注册域（含子域）；
      b) 第三方 ATS 域（北森/大易/飞书/Workday…）——公司把招聘站托管在 ATS 上是常态；
      c) 域名里含本案公司的拼音/英文 token（jobs.bytedance.com 之于「字节跳动」）。
    其余跨域链接一律不收：那些多半是广告位、合作方、招聘中介。
    """
    base_host = (urlsplit(base).hostname or "").lower()
    base_root = ".".join(base_host.split(".")[-2:]) if base_host.count(".") >= 1 else base_host
    toks = [t for t in (tokens or []) if len(t) >= 3]
    out = []
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
        href, label = m.group(1), strip_tags(m.group(2))[:60]
        if not (LINK_RX.search(label) or LINK_RX.search(href)):
            continue
        u = urljoin(base, href)
        if urlsplit(u).scheme not in ("http", "https"):
            continue
        h = (urlsplit(u).hostname or "").lower()
        root = ".".join(h.split(".")[-2:]) if h.count(".") >= 1 else h
        flat = re.sub(r"[^a-z0-9]", "", h)
        same_site = root == base_root
        is_ats = any(h == a or h.endswith("." + a) for a in ATS_HOSTS)
        has_token = any(t in flat for t in toks)
        if not (same_site or is_ats or has_token):
            continue
        if not usable_as_entry(u):
            continue
        if u not in out:
            out.append(u)
    return out[:14]


def work(item):
    _company, url, _grade = item["company"], item["url"], item["grade"]
    with httpx.Client(follow_redirects=True, timeout=15, headers={"User-Agent": UA}) as c:
        base = get(c, url)
        if not base.get("html"):
            return {**item, "upgrade": None, "nav": {"err": base.get("err") or base.get("status")}}
        cands = candidates_from(base["html"], base["url"], item.get("tokens") or [])
        best = None
        checked = 0
        for u in cands:
            if checked >= 5:
                break
            checked += 1
            r = get(c, u)
            if not r.get("html"):
                continue
            sc, ev = score_page(r["html"], r["url"])
            if sc >= 6 and (best is None or sc > best[0]):
                best = (sc, r["url"], ev)
        if best is None:
            # 自己也可能是列表页（有些站点首页就是岗位列表）
            sc, ev = score_page(base["html"], base["url"])
            if sc >= 9:
                best = (sc, base["url"], ev)
        return {**item, "nav": {"checked": checked, "score": best[0] if best else 0},
                "upgrade": ({"url": best[1], "score": best[0], "evidence": best[2]} if best else None)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--grades", default="C,D")
    ap.add_argument("--workers", type=int, default=20)
    args = ap.parse_args()

    rows = [json.loads(s) for s in
            (ROOT / "work/entry_graded.jsonl").read_text(encoding="utf-8").splitlines() if s.strip()]
    want = set(args.grades.split(","))
    todo = [r for r in rows if r["grade"] in want]
    if args.limit:
        todo = todo[:args.limit]
    print(f"todo={len(todo)}", file=sys.stderr)

    out = ROOT / "work/navigated.jsonl"
    done = set()
    if out.exists():
        done = {json.loads(s)["company"] for s in out.read_text(encoding="utf-8").splitlines() if s.strip()}
    todo = [t for t in todo if t["company"] not in done]
    print(f"remaining={len(todo)}", file=sys.stderr)

    n, up, t0 = 0, 0, time.time()
    with open(out, "a", encoding="utf-8") as fh, ThreadPoolExecutor(args.workers) as ex:
        for rec in ex.map(work, todo):
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            n += 1
            if rec.get("upgrade"):
                up += 1
                print(f"[{n}] UP {rec['company']} -> {rec['upgrade']['url'][:70]}", file=sys.stderr)
            elif n % 20 == 0:
                print(f"[{n}/{len(todo)}] {n / max(time.time() - t0, 1) * 60:.1f} 家/分 "
                      f"升级 {up}", file=sys.stderr)
    print(f"done {n} upgraded {up}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
