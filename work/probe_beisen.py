"""批量探测北森新版租户（{slug}.zhiye.com）+ 同名核对。

与 scripts/probe_beisen_tenants.py 的区别：
  - 输入是「公司名 + 品牌名」，需要先生成 slug 候选
  - 串行、每 host ≤1 rps、失败重试上限 2 次、遇 429 立刻停
  - 命中后必须做同名核对：页面 <title> 或列表里任一岗位标题要包含公司名关键词

输出：work/probe_results.jsonl，一行一个命中/失败记录。

用法：
    python3 work/probe_beisen.py --file work/candidates_clean.tsv --limit 200 --out work/probe_a.jsonl
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx
from pypinyin import Style, lazy_pinyin
from pypinyin.constants import PHRASES_DICT  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import USER_AGENT  # noqa: E402

LIST_PATH = "/api/Jobad/GetJobAdPageList"
UA = USER_AGENT


def slug_candidates(name: str, brand: str) -> list[str]:
    """按命中概率从高到低给候选 slug。"""
    out: list[str] = []

    def add(s: str | None) -> None:
        if not s:
            return
        s = s.strip().lower().replace(" ", "").replace("&", "").replace("'", "")
        if not s or len(s) < 2 or not s.isascii():
            return
        if s not in out:
            out.append(s)

    # 1) 品牌名原样（英文名最常直接做 slug）
    add(brand)
    add(brand.replace(" ", ""))
    # 2) 拼音全拼（去掉括号/英文后缀）
    base = name
    for cut in ("（", "(", "集团", "控股", "股份", "有限公司", "中国", "科技"):
        base = base.replace(cut, "")
    py = "".join(lazy_pinyin(base, style=Style.NORMAL))
    add(py)
    add(py + "hr")
    add(py + "1")
    # 3) 拼音首字母 + hr（少数门户）
    add("".join(lazy_pinyin(base, style=Style.FIRST_LETTER)))
    return out[:6]


def probe(client: httpx.Client, slug: str) -> dict:
    rec: dict = {"slug": slug}
    try:
        r = client.get(f"https://{slug}.zhiye.com/", timeout=12, follow_redirects=False)
    except Exception as e:  # noqa: BLE001
        rec.update(ok=False, error=type(e).__name__)
        return rec
    rec["status"] = r.status_code
    if r.status_code != 200:
        rec["ok"] = False
        return rec
    title = ""
    s = r.text.find("<title>")
    if s >= 0:
        title = r.text[s + 7:r.text.find("</title>", s)].strip()
    rec["title"] = title[:60]
    try:
        d = client.post(f"https://{slug}.zhiye.com{LIST_PATH}",
                        json={"PageIndex": 0, "PageSize": 20, "KeyWords": "",
                              "SpecialType": 0, "PortalId": ""}, timeout=15).json()
    except Exception as e:  # noqa: BLE001
        rec.update(ok=False, error="not-json:" + type(e).__name__)
        return rec
    rec["code"] = d.get("Code")
    rec["count"] = d.get("Count")
    names = [x.get("JobAdName", "") for x in (d.get("Data") or [])][:8]
    rec["jobs"] = names
    rec["ok"] = d.get("Code") == 200
    return rec


def name_matches(company: str, rec: dict) -> bool:
    """同名核对：title 或岗位标题里出现公司名的核心词。"""
    core = company
    for cut in ("（", "(", "集团", "股份", "控股", "有限公司", "中国"):
        core = core.replace(cut, "")
    blob = (rec.get("title") or "") + " " + " ".join(rec.get("jobs") or [])
    if not blob.strip():
        return False
    # 公司名在 blob 里出现
    if core and core in blob:
        return True
    # title 里出现公司名前 2-3 字
    head = core[:2]
    return bool(head and head in (rec.get("title") or ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip", type=int, default=0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = []
    for ln in Path(args.file).read_text(encoding="utf-8").splitlines():
        p = ln.split("\t")
        if len(p) >= 3:
            rows.append((p[0], p[1], p[2]))
    if args.skip:
        rows = rows[args.skip:]
    if args.limit:
        rows = rows[: args.limit]

    out = open(args.out, "w", encoding="utf-8")
    hits = 0
    hosts_seen: dict[str, float] = {}
    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"},
                      timeout=12) as client:
        for i, (company, sector, brand) in enumerate(rows, 1):
            cands = slug_candidates(company, brand)
            got = None
            for slug in cands:
                host = f"{slug}.zhiye.com"
                # 1 rps / host 硬约束
                wait = hosts_seen.get(host, 0) + 1.0 - time.time()
                if wait > 0:
                    time.sleep(wait)
                hosts_seen[host] = time.time()
                rec = probe(client, slug)
                if rec.get("ok") and name_matches(company, rec):
                    got = rec
                    break
                if rec.get("status") == 429:
                    print(f"[429] {slug} 触发限流，停止 60s", file=sys.stderr)
                    time.sleep(60)
            if got:
                got.update(company=company, sector=sector, brand=brand, matched=True)
                hits += 1
            else:
                got = {"company": company, "sector": sector, "brand": brand,
                       "matched": False, "tried": cands}
            out.write(json.dumps(got, ensure_ascii=False) + "\n")
            out.flush()
            if i % 10 == 0:
                print(f"进度 {i}/{len(rows)} 命中 {hits}", file=sys.stderr)
    out.close()
    print(f"完成：{len(rows)} 家，命中 {hits}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
