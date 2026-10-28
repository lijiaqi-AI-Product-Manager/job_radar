"""把 careers_ats_harvest.py 的 found 结果转成 sd_hits 形态，交给 apply_sd.py 落库。

输入 work/careers_ats2.jsonl：{company, sector, found: {kind, slug, host, ...}|None, tried}
输出 work/careers_sd_hits.jsonl：{platform, slug, company, host, count, title}

跳过 moka（红线不碰）与 hotjob_probable（未确认）。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "work" / "careers_ats2.jsonl"
OUT = ROOT / "work" / "careers_sd_hits.jsonl"
SKIP = {"moka_blocked", "hotjob_probable", None}


def main() -> int:
    rows = [json.loads(ln) for ln in SRC.read_text(encoding="utf-8").splitlines() if ln.strip()]
    out, seen = [], set()
    for r in rows:
        f = r.get("found") or {}
        kind = f.get("kind")
        if kind in SKIP:
            continue
        slug = f.get("slug") or f.get("host") or ""
        key = (kind, slug)
        if not slug or key in seen:
            continue
        seen.add(key)
        out.append({
            "platform": "beisen" if kind == "beisen_host" else kind,
            "kind": kind,
            "slug": slug,
            "company": f.get("company") or r.get("company") or "",
            "host": f.get("host") or "",
            "count": f.get("count") or 0,
            "title": f.get("title") or "",
        })
    OUT.write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in out), encoding="utf-8")
    from collections import Counter
    print("写出", OUT.name, len(out), Counter(o["kind"] for o in out))
    print("公司名样本", [o["company"] for o in out[:8]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
