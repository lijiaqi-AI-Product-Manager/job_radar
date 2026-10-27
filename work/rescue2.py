"""回收：把「已确认有招聘页、但被前面几轮规则挡在可用池外」的公司捞回来。

背景（真实数据）：
- work/careers_confirmed.jsonl 里 1019 家拿到了 best 招聘页；
- work/entry_usable.jsonl 只有 799 家；
- 差集 296 家里，219 家甚至没有拒绝记录（上一轮冲突过滤直接丢掉了，没留痕）。

这里不搞"放宽阈值"，而是对每一条候选做**逐条硬核验**，只有同时满足以下条件才回收：
1. URL 能 200 打开（实测，不是缓存）；
2. 主机名不是第三方聚合站、不是媒体、不是高校就业网；
3. 页面标题或链接文本里出现**公司名**，或出现**该公司的英文品牌词**
   （英文品牌词从 targets/top_companies.yaml 的 aliases 取，如 携程→ctrip）；
4. 不是明显错配（如「360集团」拿到 hao.360.com 这种导航站、「微博」拿到 campus.163.com）。

不满足就写进 work/rescue_rejected.jsonl 并写明原因，绝不硬塞。

用法：
    python3 work/rescue_careers.py2.py            # 试跑，只打印
    python3 work/rescue_careers.py2.py --apply    # 写出 work/rescued_entries.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import yaml

WORK = Path(__file__).resolve().parent
ROOT = WORK.parent
sys.path.insert(0, str(WORK))

from hostrules import usable_as_entry  # noqa: E402

UA = ("jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; "
      "open dataset, polite crawler; contact via GitHub issues)")

# 导航站/门户首页不是招聘页，哪怕域名属于本公司（hao.360.com、www.360.cn 之类）
NAV_HOST = ("hao.", "www.", "m.", "导航")

# 同一集团内多家子公司的品牌别名不算"他家公司"，避免把集团分支互相判成冲突
GROUPS = {
    "招商局": ["招商", "cmhk"], "中国建筑": ["中建", "cscec"], "中国中车": ["中车", "crrc"],
    "中国中铁": ["中铁", "crec"], "中国铁建": ["铁建", "crcc"], "国家电网": ["国网", "sgcc"],
    "中国石油": ["中石油", "petrochina"], "中国石化": ["中石化", "sinopec"],
}


def load_targets() -> tuple[dict[str, list[str]], dict[str, str]]:
    """返回 (中文别名表, 集团映射)，并把 brand_tokens 里的英文品牌词一并并入别名表。

    aliases 只有 22 条中文别名，光靠它匹配不到 careers.ctrip.com / campus.geely.com
    这类英文域名；targets/top_companies.yaml 的 brand_tokens 是为这件事单独维护的。
    """
    t = yaml.safe_load((ROOT / "targets/top_companies.yaml").read_text(encoding="utf-8")) or {}
    aliases: dict[str, list[str]] = {}
    for key in ("aliases", "brand_tokens"):
        for k, vals in (t.get(key) or {}).items():
            aliases.setdefault(k, []).extend(v for v in (vals or []) if isinstance(v, str))
    group_of: dict[str, str] = {}
    for brand, variants in aliases.items():
        for v in variants:
            group_of.setdefault(v, brand)
    return aliases, group_of


def brand_tokens(company: str, aliases: dict[str, list[str]], group_of: dict[str, str]) -> list[str]:
    """公司名 → 可用于匹配 URL/标题的英文品牌词（小写，纯 ASCII，长度>=3）。"""
    toks: list[str] = []
    cand = [company, group_of.get(company, "")]
    for c in cand:
        if not c:
            continue
        for v in aliases.get(c, []) + [c]:
            flat = v.lower()
            if flat.isascii() and len(flat) >= 3 and flat.isalnum():
                toks.append(flat)
    # 去重保序
    return list(dict.fromkeys(toks))


def verify(company: str, url: str, client: httpx.Client,
           aliases: dict[str, list[str]], group_of: dict[str, str]) -> tuple[bool, str, str]:
    """返回 (是否可用, 原因, 页面标题)。"""
    if not usable_as_entry(url):
        return False, "host_not_usable", ""
    host = urlsplit(url).hostname or ""
    if host.startswith(NAV_HOST):
        return False, "nav_portal", ""
    try:
        r = client.get(url, headers={"User-Agent": UA}, timeout=20, follow_redirects=True)
    except Exception as e:
        return False, f"fetch:{type(e).__name__}", ""
    if r.status_code != 200:
        return False, f"status:{r.status_code}", ""
    body = r.text[:60000]
    low = body.lower()
    title = ""
    if "<title" in low:
        seg = body[low.index("<title"):low.index("<title") + 400]
        title = seg.split(">", 1)[-1].split("<", 1)[0].strip()

    zh = "".join(ch for ch in company if "\u4e00" <= ch <= "\u9fa5")
    hit_name = bool(zh) and (zh in title or zh in body[:20000])
    toks = brand_tokens(company, aliases, group_of)
    host_flat = "".join(ch for ch in host.lower() if ch.isalnum())
    hit_brand = any(t in host_flat or t in low for t in toks)

    if not (hit_name or hit_brand):
        return False, "no_name_evidence", title
    if len(body) < 600 and not title:
        return False, "empty_page", title
    return True, "ok", title


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    aliases, group_of = load_targets()
    conf = {}
    for line in (WORK / "careers_confirmed.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            conf[r["company"]] = r
    used = set()
    for line in (WORK / "entry_usable.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                used.add(json.loads(line)["company"])
            except Exception:
                continue

    todo = [c for c, r in conf.items() if c not in used and (r.get("best") or {}).get("url")]
    print(f"候选 {len(todo)} 家（有 best 但不在可用池）", file=sys.stderr)

    ok, bad = [], []
    with httpx.Client(timeout=20) as client:
        for i, c in enumerate(todo, 1):
            url = conf[c]["best"]["url"]
            good, why, title = verify(c, url, client, aliases, group_of)
            if good:
                ok.append({"company": c, "sector": conf[c].get("sector", ""), "url": url,
                           "title": title, "grade": "A", "grade_why": "rescued",
                           "host": urlsplit(url).hostname,
                           "kind": "site", "pages": [], "note": "rescued"})
            else:
                bad.append({"company": c, "url": url, "reason": why})
            if i % 40 == 0:
                print(f"  {i}/{len(todo)} ok={len(ok)}", file=sys.stderr)

    print(f"回收 {len(ok)} / 拒绝 {len(bad)}")
    (WORK / "rescue2_rejected.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in bad), encoding="utf-8")
    if args.apply:
        (WORK / "rescued_entries.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ok), encoding="utf-8")
        print("写出 work/rescued_entries.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
