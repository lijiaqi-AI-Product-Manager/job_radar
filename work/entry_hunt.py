"""通用 ATS 入口发现：顺藤摸瓜、多平台并行、限速按主机。

为什么不是「只猜北森拼音」：800 家没接进库的公司，绝大多数**不是没入口，是入口在别的平台**。
北森只是六种 ATS 里的一种（占我库里 85% 的岗位，但在 800 家里只命中 8 家）。
剩下五路（大易 / Moka / 飞书 / hotjob / 自建站）必须一起摸。

本脚本对一家公司做四件事，任一命中即停：
  1. **扒官网**：`https://{域名}` 及其 `/join` `/careers` `/hr` `/zhaopin` `/rczp` 等常见路径，
     从 HTML 里正则抽所有 ATS 域名（`*.zhiye.com` / `*.hotjob.cn` / `*.mokahr.com` /
     `*.jobs.feishu.cn` / `*.dayee.com` / `*.myworkdayjobs.com` …）。
     ATS 链接通常直接写在招聘页里——**这是命中率最高的一路**，比猜 slug 高一个数量级。
  2. **顺着跳转**：扒到的页面若是 302 到 ATS，直接收。
  3. **追问 JS**：招聘页里的 `<script src>` 若含 `.js`，下载后在 JS 里再正则一次
     （Vue/React 站的 ATS 地址常写在 bundle 里）。
  4. **搜索引擎兜底**：前三路都没结果时，用必应 `site:` 查询反查（可选，`--search`）。

红线：
  - 每主机 ≤1 rps、同主机串行（本脚本用「按主机分桶 + 每桶内 sleep」实现，不用全局并发）；
  - 不伪造 UA（统一 `jobradar/0.1`）；
  - 不解析、不逆向任何签名/加密；只读公开 HTML/JS；
  - 只把 ATS 域名当**入口线索**，真正的岗位数据仍由各自适配器按既有规则抓。
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
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import USER_AGENT  # noqa: E402

ATS_HOST = re.compile(
    r"https?://([a-z0-9][a-z0-9._-]{1,40}\.(?:zhiye\.com|hotjob\.cn|mokahr\.com|dayee\.com|"
    r"myworkdayjobs\.com|avature\.net|tupu360\.com|jobs\.feishu\.cn|hire\.tencent\.com|"
    r"jobs\.bytedance\.com|taleo\.net|successfactors\.com|icims\.com|smartrecruiters\.com|"
    r"lever\.co|greenhouse\.io|workable\.com|jobvite\.com))", re.I)

# 招聘页常见路径（国内企业站几乎都在这几个词里）
CAREER_PATHS = ("/", "/hr", "/hr/index.html", "/join", "/joinus", "/join-us", "/careers", "/career",
                "/job", "/jobs", "/zhaopin", "/rczp", "/recruit", "/recruit/index.html",
                "/rencai", "/zp", "/talent", "/about/join", "/job/index.html",
                "/hr/campus.html", "/hr/join.html", "/zhaopin/index.html")

# 北森「旧版门户」：`xxx.zhiye.com` 直接给出岗位列表页，没有 `/api/Jobad/GetJobAdPageList`。
# 这类页面的 HTML 里就带岗位条目，`href="/jobdetail/..."` + 标题可解析。
LEGACY_LIST = re.compile(r'href="(?:https?://[^/]+)?/(?:jobdetail|JobDetail|job)/([A-Za-z0-9_-]{4,40})"[^>]*>\s*([^<]{2,80})<', re.I)

# 企业自研招聘门户：页面路径里出现这些词，就当成「自建站岗位列表」记录下来（不进 sources，进线索池）
SELF_HOSTED_HINT = re.compile(r"(zhaopin|recruit|job|career|apply|position)", re.I)

CSS_HREF = re.compile(r'(?:href|src)\s*=\s*["\']([^"\']+\.(?:js|html?))["\']', re.I)

_host_next: dict[str, float] = {}
_host_lock = threading.Lock()
_print_lock = threading.Lock()


def wait_host(host: str, rps: float = 1.0) -> None:
    """同主机串行 + ≤rps：每个 host 记一个「下次可发请求时间」。"""
    gap = 1.0 / rps
    while True:
        with _host_lock:
            now = time.monotonic()
            nxt = _host_next.get(host, 0.0)
            if now >= nxt:
                _host_next[host] = now + gap
                return
            sleep_for = nxt - now
        time.sleep(min(sleep_for, 0.5))


def fetch(cli: httpx.Client, url: str) -> tuple[int, str, str]:
    """返回 (status, final_url, text)。全程 1 rps/host。

    有些站（石药 `e-cspc.com` 实测）**首次访问返回 200 + Content-Length: 0**，
    带上它下发的 JSESSIONID 再请求一次才给正文。这不是反爬，是会话初始化。
    所以「200 但 0 字节」时带 cookie 重试一次——只重试一次，不无限追。
    """
    host = url.split("/")[2].lower()
    wait_host(host)
    try:
        r = cli.get(url)
    except Exception:  # noqa: BLE001
        return 0, url, ""
    if r.status_code == 200 and not (r.text or "").strip():
        wait_host(host)  # 同主机仍 ≤1 rps
        try:
            r = cli.get(url)
        except Exception:  # noqa: BLE001
            return 0, url, ""
    return r.status_code, str(r.url), r.text or ""


def harvest(cli: httpx.Client, url: str, depth: int = 0) -> tuple[list[str], int, str]:
    """抓一个 URL，返回 (命中的 ATS 主机, 页面字数, 最终 URL)。"""
    status, final, text = fetch(cli, url)
    if status == 0:
        return [], 0, final
    hosts = [m.group(1).lower() for m in ATS_HOST.finditer(text)]
    # 302 跳到 ATS 也算（fetch 用 follow_redirects，final 就是落地页）
    hosts += [m.group(1).lower() for m in ATS_HOST.finditer(final)]
    if not hosts and depth == 0 and status == 200:
        # 追问 JS：只在这个页面看起来像招聘页（字数 > 800）时做，避免把整站 JS 都拉一遍
        plain = re.sub(r"<[^>]+>", " ", text)
        if len(plain) > 800:
            for href in CSS_HREF.findall(text):
                if not href.endswith(".js"):
                    continue
                js_url = httpx.URL(url).join(href)
                if js_url.host != httpx.URL(url).host:
                    continue
                _, _, js = fetch(cli, str(js_url))
                hosts += [m.group(1).lower() for m in ATS_HOST.finditer(js)]
                if len(hosts) >= 3:
                    break
    seen: list[str] = []
    for h in hosts:
        if h not in seen:
            seen.append(h)
    return seen, len(re.sub(r"<[^>]+>", " ", text)), final


def probe_company(item: dict) -> dict:
    name = item["company"]
    # `domain` 可以是裸域名，也可以是公司官网 URL。用 careers_url 时必须先剔掉两类：
    #   - 已知 ATS 域名（那本身就是入口，不需要再摸官网）
    #   - 高校就业网/第三方站（`*.edu.cn`、招聘聚合站），它们不是公司的站
    domain = (item.get("domain") or "").strip()
    out = {"company": name, "domain": domain, "hits": [], "checked": [], "note": ""}
    if not domain:
        out["note"] = "no_domain"
        return out
    low = domain.lower()
    for ats in ("zhiye.com", "hotjob.cn", "mokahr.com", "dayee.com", "myworkdayjobs.com",
                "avature.net", "tupu360.com", "jobs.feishu.cn"):
        if ats in low:
            out["hits"] = [httpx.URL(low).host]
            out["note"] = "already_ats"
            return out
    for junk in (".edu.cn", "yingjiesheng", "zhaopin.com", "51job", "liepin", "kanzhun",
                 "fenbi.com", "shixiseng", "nowcoder"):
        if junk in low:
            out["note"] = "third_party"
            return out

    base = domain if domain.startswith("http") else f"https://{domain}"
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=12.0,
                      follow_redirects=True, verify=False) as cli:  # noqa: S501 企业站证书常过期
        # 先摸官网首页：入口链接往往就写在这里
        hosts, chars, final = harvest(cli, base)
        out["checked"].append(f"{base}:{chars}")
        if hosts:
            out["hits"] = hosts
            out["note"] = "found@home"
            return out
        # 再按常见招聘页路径逐个试
        for p in CAREER_PATHS:
            if p == "/":
                continue
            url = base.rstrip("/") + p
            hosts, chars, final = harvest(cli, url)
            out["checked"].append(f"{url}:{chars}")
            if hosts:
                out["hits"] = hosts
                out["note"] = f"found@{p}"
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True, help="JSONL：{company, domain}")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=4, help="并行公司数（不是并行主机数）")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    items = [json.loads(ln) for ln in Path(args.src).read_text(encoding="utf-8").splitlines() if ln.strip()]
    if args.limit:
        items = items[:args.limit]
    outp = Path(args.out)
    done: set[str] = set()
    if outp.exists():
        for ln in outp.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(ln)["company"])
            except Exception:  # noqa: BLE001
                pass
    todo = [it for it in items if it["company"] not in done]
    print(f"待摸 {len(todo)}（已完成 {len(done)}）", flush=True)

    hits = 0
    t0 = time.time()
    import warnings
    warnings.filterwarnings("ignore")
    with ThreadPoolExecutor(max_workers=args.workers) as ex, outp.open("a", encoding="utf-8") as f:
        for i, rec in enumerate(ex.map(probe_company, todo), 1):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if rec["hits"]:
                hits += 1
                with _print_lock:
                    print(f"HIT  {rec['company']:16s} {rec['note']:14s} {rec['hits']}", flush=True)
            if i % 20 == 0:
                with _print_lock:
                    print(f"... {i}/{len(todo)} {time.time() - t0:.0f}s 命中 {hits}", flush=True)
    print(f"完成 {len(todo)}，命中 {hits}，用时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
