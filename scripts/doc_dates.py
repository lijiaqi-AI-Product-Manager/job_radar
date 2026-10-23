"""从「招聘公告/简章」子页面里抽网申时间（日历里最缺的字段）。

渲染大厂招聘页时顺手收集的 `doc_links` 指向公告/简章/通知页；这些页面是普通 HTML，
网申时间基本都写在里面（「网申时间：2026 年 9 月 1 日—10 月 31 日」）。

用法：
    uv run python scripts/doc_dates.py --enrich enrich-b6.json --out doc-dates.json [--apply]

红线：只读公开页面；抽不到就留空，不猜。
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
ENTRIES = ROOT / "calendar" / "entries"
UA = "jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; open dataset, polite crawler; contact via GitHub issues)"

YEAR = re.compile(r"(20\d{2})\s*届")
CN = r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?"
RANGE = re.compile(CN + r"\s*(?:—|－|~|～|至|到|-)\s*(?:(20\d{2})[年./-])?(\d{1,2})[月./-](\d{1,2})日?")
KW = re.compile(r"(网申|报名|投递|申请|截止|简历|招聘时间|时间安排)")


def fetch(url: str) -> str:
    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=20, follow_redirects=True) as c:
            r = c.get(url)
            return r.text if r.status_code == 200 else ""
    except Exception:
        return ""


def _ok(s: str, e: str) -> bool:
    try:
        y1, m1, d1 = (int(x) for x in s.split("-"))
        y2, m2, d2 = (int(x) for x in e.split("-"))
        if not (s < e) or y1 < 2025 or y1 > 2028:
            return False
        return 3 <= (date(y2, m2, d2) - date(y1, m1, d1)).days <= 400
    except Exception:
        return False


def parse(html: str) -> dict:
    out: dict = {}
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)[:200_000]
    m = YEAR.search(text)
    if m and 2024 <= int(m.group(1)) <= 2032:
        out["grad_year"] = int(m.group(1))
    best = None
    for mm in RANGE.finditer(text):
        g = mm.groups()
        start = f"{g[0]}-{int(g[1]):02d}-{int(g[2]):02d}"
        end = f"{g[3] or g[0]}-{int(g[4]):02d}-{int(g[5]):02d}"
        if not _ok(start, end):
            continue
        ctx = text[max(0, mm.start() - 40):mm.start() + 40]
        score = 2 if KW.search(ctx) else 1
        if best is None or score > best[0]:
            best = (score, start, end)
    if best:
        out["apply_start"], out["apply_end"] = best[1], best[2]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enrich", required=True, help="render_extract 输出的 JSON（含 doc_links）")
    ap.add_argument("--out", default="doc-dates.json")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-per-entry", type=int, default=3)
    args = ap.parse_args()
    data = json.loads(Path(args.enrich).read_text(encoding="utf-8"))
    results = {}
    for eid, got in data.items():
        docs = (got.get("doc_links") or [])[: args.max_per_entry]
        merged: dict = {}
        for d in docs:
            parsed = parse(fetch(d["url"]))
            if not parsed:
                continue
            for k in ("grad_year", "apply_start", "apply_end"):
                if parsed.get(k) and not merged.get(k):
                    merged[k] = parsed[k]
            if merged.get("apply_start") and merged.get("grad_year"):
                break
        if merged:
            results[eid] = {**merged, "group": got.get("group"), "source": docs[0]["url"] if docs else None}
            print(f"{got.get('group')}: {merged.get('grad_year')}届 {merged.get('apply_start')}~{merged.get('apply_end')}",
                  flush=True)
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n抽出 {len(results)} 条 → {args.out}", file=sys.stderr)
    if not args.apply:
        return 0
    import yaml
    files = 0
    for p in ENTRIES.glob("*.yaml"):
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        changed = False
        for e in doc.get("entries") or []:
            got = results.get(e.get("id"))
            if not got:
                continue
            for k in ("grad_year", "apply_start", "apply_end"):
                if got.get(k) and not e.get(k):
                    e[k] = got[k]
                    changed = True
        if changed:
            p.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
            files += 1
    print(f"写回 {files} 个文件", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
