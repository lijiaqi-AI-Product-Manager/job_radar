"""把官方公众号推文转成招聘日历条目（人工编辑流程的半自动化）。

红线（docs/DEVELOPMENT.md）：公众号来源只认**公司官方账号**，且必须写推文日期。
所以这里做两件事：
1. 抓推文页，取出公众号昵称、发布时间、标题；
2. 昵称里必须出现给定的公司关键词（如 中国石化 → 中石化），否则拒绝。

用法：
    uv run python scripts/wechat_entries.py --file candidates.json [--apply]
    candidates.json: [{"group": "中国石化", "slug": "sinopec", "keywords": ["中石化"], "urls": ["https://mp.weixin.qq.com/s/..."]}]

不加 --apply 只打印判定结果；加了才会写/追加 calendar/entries/<slug>.yaml（按 URL 去重）。
"""

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
ENTRIES = ROOT / "calendar" / "entries"
# 2026-10-26 实测：带 URL 的 UA 会被公众号判为抓取器并回 18 KB「环境异常」壳页；
# 短 UA `Mozilla/5.0 (compatible; jobradar-bot/0.1)` 能拿到完整文章页（仍是诚实爬虫标识）。
# 与 scripts/wechat_parse.py 共用同一个 UA，改一处必须改两处。
UA = "Mozilla/5.0 (compatible; jobradar-bot/0.1)"
NICK = re.compile(r'nickname\s*=\s*htmlDecode\(\"([^\"]+)\"')
CT = re.compile(r'var create_time = "(\d+)"')
TITLE = re.compile(r'property="og:title" content="([^"]+)"')


_BLOCK_MARKERS = ("环境异常", "完成验证后即可继续访问", "请输入验证码", "该内容已被发布者删除")


def _blocked(html: str) -> bool:
    """验证页/删文页/空壳页。正文页也会带 "captcha"（JS 资源名），所以只认中文提示。"""
    return any(k in html for k in _BLOCK_MARKERS) or len(html) < 5000


def parse(html: str) -> dict:
    nick = NICK.search(html)
    ct = CT.search(html)
    title = TITLE.search(html)
    date = dt.datetime.fromtimestamp(int(ct.group(1)), dt.UTC).strftime("%Y-%m-%d") if ct else None
    return {"nickname": nick.group(1) if nick else None, "date": date,
            "title": title.group(1) if title else None}


def append_entry(slug: str, group: str, entry: dict) -> str:
    path = ENTRIES / f"{slug}.yaml"
    if path.exists():
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if any(e.get("apply_url") == entry["apply_url"] for e in doc.get("entries") or []):
            return "duplicate"
    else:
        doc = {"group": group, "entries": []}
    doc.setdefault("entries", []).append(entry)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return "written"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    candidates = json.loads(Path(args.file).read_text(encoding="utf-8"))
    ok = 0
    blocked = 0
    with httpx.Client(headers={"User-Agent": UA, "Accept": "text/html"}, timeout=25,
                      follow_redirects=True) as c:
        for cand in candidates:
            group, slug = cand["group"], cand["slug"]
            keywords = cand.get("keywords") or [group]
            for url in cand.get("urls") or []:
                try:
                    html = c.get(url).text
                except Exception as e:  # noqa: BLE001
                    print(f"ERR  {group:8s} {type(e).__name__} {url[:60]}")
                    continue
                if _blocked(html):
                    # 被验证页拦住时必须显式报出来：静默返回"昵称=None"会被误读成
                    # "这条不是官方账号"，从而把真推文整条丢掉（旧版就是这样丢了全部四条）。
                    blocked += 1
                    print(f"BLOCK {group:8s} {url[:60]}")
                    continue
                info = parse(html)
                nick = info["nickname"] or ""
                # 必须「账号名以关键词开头」：用 in 会误判（"电科" 会命中 "西电科大就业指导服务中心"）
                official = any(nick.startswith(k) for k in keywords)
                print(f"{'OK  ' if official else 'skip'} {group:8s} {nick[:20]:20s} {info['date']} "
                      f"{(info['title'] or '')[:34]}")
                if not (official and info["date"] and info["title"]):
                    continue
                entry = {
                    "id": f"{slug}-wechat-{info['date'].replace('-', '')}",
                    "company": nick,
                    "project_type": "校招",
                    "apply_url": url,
                    "source": {"type": "wechat", "name": f"{nick} 公众号", "url": url, "date": info["date"]},
                    "as_of": dt.date.today().isoformat(),
                    "jd": {"status": "none"},
                    "notes": f"官方公众号推文《{info['title']}》（{info['date']}）。投递入口与批次时间以推文内二维码/链接为准，未固定写出，故不填网申时间。",
                }
                if args.apply:
                    print("     ->", append_entry(slug, group, entry))
                ok += 1
    print(f"\n官方账号命中 {ok} 条，被验证页拦截 {blocked} 条", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
