"""探测北森租户（`{slug}.zhiye.com`）是否存在，并输出可直接粘进 sources/beisen.yaml 的行。

覆盖率瓶颈不是「某家公司抓不抓得到」，而是它用哪个 ATS（docs/COVERAGE-PLAN.md）。
北森租户命名没有公开目录，只能用「猜 slug + 校验」：租户存在时首页 200、列表接口返回 JSON；
不存在时 302 到 /404。本脚本把这件事做成可重复的操作。

用法：
    uv run python scripts/probe_beisen_tenants.py byd catl nio        # 直接给 slug
    uv run python scripts/probe_beisen_tenants.py --file slugs.txt    # 一行一个
    uv run python scripts/probe_beisen_tenants.py --file slugs.txt --yaml  # 输出 sources 行

注意：只读公开首页与列表接口，1 秒 1 个；不要在脚本里并发。
"""

import argparse
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import USER_AGENT  # noqa: E402

LIST_PATH = "/api/Jobad/GetJobAdPageList"


def probe(client: httpx.Client, slug: str) -> dict:
    """返回 {slug, ok, count, title}；ok=False 表示该租户不存在（或不是新版门户）。"""
    try:
        page = client.get(f"https://{slug}.zhiye.com/")
    except httpx.HTTPError as e:
        return {"slug": slug, "ok": False, "error": type(e).__name__}
    if page.status_code != 200:
        return {"slug": slug, "ok": False, "status": page.status_code}
    title = ""
    start = page.text.find("<title>")
    if start >= 0:
        title = page.text[start + 7:page.text.find("</title>", start)].strip()
    try:
        data = client.post(f"https://{slug}.zhiye.com{LIST_PATH}",
                           json={"PageIndex": 0, "PageSize": 1, "KeyWords": "",
                                 "SpecialType": 0, "PortalId": ""}).json()
    except (httpx.HTTPError, ValueError):
        return {"slug": slug, "ok": False, "title": title, "error": "not-json"}
    return {"slug": slug, "ok": data.get("Code") == 200, "title": title, "count": data.get("Count")}


def main() -> int:
    # Windows 控制台默认 GBK：公司名里的生僻字会让 print 崩，和 jobradar CLI 一样处理
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*", help="候选 slug（公司英文名/拼音，常见变体加数字 1）")
    ap.add_argument("--file", help="候选文件，一行一个 slug")
    ap.add_argument("--yaml", action="store_true", help="只输出可直接粘进 sources/beisen.yaml 的行")
    args = ap.parse_args()

    slugs = list(args.slugs)
    if args.file:
        slugs += [ln.strip() for ln in Path(args.file).read_text(encoding="utf-8").splitlines()
                  if ln.strip() and not ln.startswith("#")]
    if not slugs:
        ap.error("至少给一个 slug")

    hits = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True) as client:
        for slug in slugs:
            r = probe(client, slug)
            if r["ok"]:
                hits.append(r)
                if not args.yaml:
                    print(f"HIT  {slug:20s} {r['count']:>6} 岗  {r['title']}")
            elif not args.yaml:
                print(f"---  {slug:20s} {r.get('status') or r.get('error') or ''}")
            time.sleep(1.0)

    if args.yaml:
        for r in hits:
            print(f"  - {{id: beisen-{r['slug']}, company: 待填, params: {{tenant: {r['slug']}}}}}"
                  f"   # {r['count']} 岗 {r['title']}")
    print(f"\n命中 {len(hits)} / {len(slugs)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
