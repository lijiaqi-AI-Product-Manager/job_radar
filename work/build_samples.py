#!/usr/bin/env python3
"""生成 samples/<company>/ 与 fixtures-plan.md。

samples 放「这家公司到底是怎么被抓到的」的实证：入口 URL、页面标题、抓到的结构化岗位样本。
fixtures-plan 说明哪些源要录制成可回放响应，优先级按在招岗位数排序。
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
AS_OF = "2026-10-26"


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def slug(s: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fa5-]+", "-", s).strip("-")
    return s or "x"


def main() -> int:
    companies = load_jsonl(ROOT / "companies.jsonl")
    stats = {r["name"]: r for r in load_jsonl(WORK / "sample_stats_all.jsonl") if r.get("name")}

    sdir = ROOT / "samples"
    sdir.mkdir(exist_ok=True)
    for old in sdir.rglob("*"):
        if old.is_file():
            old.unlink()

    written = 0
    fixtures = []
    for c in companies:
        name = c["company"]
        st = stats.get(name)
        d = sdir / slug(name)
        d.mkdir(exist_ok=True)
        meta = {
            "company": name,
            "careers_url": c["careers_url"],
            "host": c["host"],
            "ats": c["ats"],
            "page_title": c["evidence"]["page_title"],
            "calendar_entries": c["calendar_entries"],
            "project_types": c["project_types"],
            "tracks": c["tracks"],
            "roles": c["roles"],
            "jd_status": c["jd_status"],
            "verified_at": AS_OF,
            "evidence": c["evidence"],
        }
        (d / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        written += 1

        if st and st.get("samples"):
            (d / "jobs.json").write_text(
                json.dumps(st["samples"], ensure_ascii=False, indent=2), encoding="utf-8")
            fixtures.append({
                "company": name,
                "source_host": c["host"],
                "ats": c["ats"],
                "count": st.get("count") or 0,
                "sampled": st.get("sampled") or 0,
                "jd_rate": st.get("jd_rate"),
                "page_title": c["evidence"]["page_title"],
            })

    fixtures.sort(key=lambda x: (-x["count"], x["company"]))
    ats_count = collections.Counter(f["ats"] for f in fixtures)

    lines = [
        f"# fixtures 录制计划（{AS_OF}）",
        "",
        "目的：给每个**接口型**源留一份可回放的脱敏响应，CI 不联网也能跑通适配器契约测试。",
        "只读公开接口，录制时按 1 rps 串行；不录任何需要登录、签名或验证码的接口。",
        "",
        "## 1. 录制范围",
        "",
        f"- 全量可做公司：**{len(companies)}** 家",
        f"- 已有结构化采样（可立即录制）：**{len(fixtures)}** 家",
        f"- 按招聘系统分布：{('、'.join(f'`{k}` {v}' for k, v in ats_count.most_common()))}",
        "",
        "其余公司为自行实现的官网投递页（`self_hosted` / `unknown`），页面结构各异，",
        "不进 fixtures，走 `tests/test_calendar_entries.py` 的日历字段校验即可。",
        "",
        "## 2. 录制命令",
        "",
        "```bash",
        "python scripts/record_fixtures.py <source_id> --max-pages 1",
        "```",
        "",
        "## 3. 优先级（按实测在招岗位数降序）",
        "",
        "| # | 公司 | host | 系统 | 在招(Count) | 采样 | JD 覆盖 |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, f in enumerate(fixtures, 1):
        jd = f"{f['jd_rate']*100:.0f}%" if isinstance(f["jd_rate"], (int, float)) else "-"
        lines.append(f"| {i} | {f['company']} | `{f['source_host']}` | `{f['ats']}` "
                     f"| {f['count']} | {f['sampled']} | {jd} |")

    lines += [
        "",
        "## 4. 脱敏要求",
        "",
        "- 响应里的企业联系人电话 / 邮箱一律替换为 `REDACTED`；",
        "- 候选人相关的任何字段（投递记录、简历）不属于公开列表接口，不在录制范围；",
        "- 录制产物只保留前 1 页，避免仓库膨胀。",
    ]
    (ROOT / "fixtures-plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"samples/ 目录 {written} 家（含 meta.json，其中 {len(fixtures)} 家另有 jobs.json）")
    print(f"fixtures-plan.md {len(fixtures)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
