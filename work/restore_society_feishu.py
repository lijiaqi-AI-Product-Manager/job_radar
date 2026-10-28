"""复核 2026-10-28 因「0 岗」被删掉的那批飞书门户。

当时判定用的是门户首页 `https://{slug}.jobs.feishu.cn/` + 默认 `website_path: campus` 的组合，
而挂在 `/index` 的门户带 `website-path: campus` 头会回 `{"code": -9000003, "site not exist"}`，
于是整批被误判成「只有社招、校招列表为空」并写进 `blocked.jsonl`（reason_code=society_only）。

这里按修正后的口径重探（校招口径与 index 口径都试，取校招多的那个）：
- 有校招/实习岗 → `recruit_types: [campus, intern]`
- 只有社招岗 → `recruit_types: [campus, intern, social]`（数据集本身覆盖社招，不能当死源删掉）
- 仍然 0 岗 → 保留 blocked 记录

用法：python work/restore_society_feishu.py [--write]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(WORK))

import apply_feishu as A  # noqa: E402  复用探针与模板口径

from jobradar.sources import load_sources  # noqa: E402

FEISHU_HOST = re.compile(r"https://([a-z0-9][a-z0-9-]*?)\.jobs\.feishu\.cn")


def blocked_rows() -> list[dict]:
    rows = []
    for ln in (ROOT / "blocked.jsonl").read_text(encoding="utf-8").splitlines():
        if ln.strip():
            d = json.loads(ln)
            if d.get("reason_code") == "society_only":
                rows.append(d)
    return rows


def main() -> None:
    write = "--write" in sys.argv
    rows = blocked_rows()
    todo = []
    for d in rows:
        m = FEISHU_HOST.search(d.get("evidence") or "")
        if m:
            todo.append((m.group(1), d))
    print(f"blocked.jsonl 里 society_only {len(rows)} 条，其中飞书门户 {len(todo)} 条")

    existing = load_sources(ROOT / "sources")
    have_id = {s.id for s in existing}
    restored, still_zero = [], []
    with httpx.Client(headers=A.UA, follow_redirects=True, timeout=25) as c:
        for i, (slug, d) in enumerate(todo, 1):
            if slug in have_id:
                restored.append({"slug": slug, "company": d["company"], "already": True})
                continue
            info = A.probe(c, slug)
            if not info or not info["count"]:
                still_zero.append((slug, d["company"]))
                continue
            restored.append({"slug": slug, "company": d["company"], **info})
            if i % 10 == 0:
                print(f"  ... {i}/{len(todo)}")

    print(f"可恢复 {len(restored)} 个（其中校区岗 {sum(1 for r in restored if r.get('campus'))} 个），"
          f"仍 0 岗 {len(still_zero)} 个")
    for r in restored[:10]:
        print(f"  {r['slug']:<22} {r['company']:<16} 校招 {r.get('campus', 0):>3} / 全部 {r.get('count', 0):>4}"
              f"  path={r.get('website_path', '?')}")

    if not write:
        print("（dry-run，加 --write 落盘）")
        return

    for r in restored:
        if r.get("already"):
            continue
        slug = r["slug"]
        types = "[campus, intern]" if r["campus"] > 0 else "[campus, intern, social]"
        body = f"""id: {slug}
company: {r['company']}
adapter: feishu_atsx
recruit_types: {types}
rate_limit_rps: 1
params:
  base_url: "https://{slug}.jobs.feishu.cn"
  website_path: {r['website_path']}
  portal_type: {r['portal_type']}
  page_size: 100
  job_url: "https://{slug}.jobs.feishu.cn/{r['website_path']}/position/{{id}}/detail"
compliance:
  checked_on: 2026-10-28
  robots: "none"            # robots.txt 404（平台层无站点级规则）；只读公开职位列表，不触达 /referral
  terms: "飞书招聘 ATSX 门户：匿名 csrf token + 公开职位列表 JSON，无登录、无验证码、无签名校验。会话 token 只在内存中使用（CLAUDE.md 铁律 1）。用户协议待人工复核"
  notes: "2026-10-28 子域枚举与公开代码搜索发现；门户 <title> 为「{r['title'][:40]}」，portal_type={r['portal_type']}、website_path={r['website_path']} 时公开职位 {r['count']} 条（校招/实习 {r['campus']} 条）。"
"""
        (ROOT / "sources" / f"{slug}.yaml").write_text(body, encoding="utf-8")

    # 把已恢复的 slug 从 blocked.jsonl 里摘掉（剩余的真 0 岗保留）
    bad = {r["slug"] for r in restored}
    keep = []
    for ln in (ROOT / "blocked.jsonl").read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        d = json.loads(ln)
        m = FEISHU_HOST.search(d.get("evidence") or "")
        if m and m.group(1) in bad:
            continue
        keep.append(ln)
    (ROOT / "blocked.jsonl").write_text("\n".join(keep) + "\n", encoding="utf-8")
    after = load_sources(ROOT / "sources")
    print(f"写入 {len([r for r in restored if not r.get('already')])} 个飞书门户："
          f"{len(existing)} → {len(after)} 源；blocked.jsonl {len(rows)} → {len(keep)} 条")


if __name__ == "__main__":
    main()
