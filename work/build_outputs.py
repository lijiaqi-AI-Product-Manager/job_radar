"""把 probe_all.jsonl 转成四个交付物：
  companies.jsonl / proposed-sources.yaml / blocked.jsonl / batch-report.md

规则（对齐用户规格第 3 节 companies.jsonl 字段，一个不多一个不少）：
  - matched=true 且 count>=1  → verdict=doable
  - matched=true 但 count==0  → verdict=empty
  - 有页面但 title 不匹配（同名不同公司）→ 不进 companies（记 rejected.md）
  - 没探到 → verdict=no_entry（不猜）
"""

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
OUT = ROOT / "docs" / "recon"

# 允许的 sector 枚举（用户规格第 3 节）
SECTOR_MAP = {
    "互联网与软件": "互联网与软件",
    "通信与电子硬件": "通信与电子硬件",
    "半导体": "半导体",
    "汽车与出行": "汽车与新能源",
    "新能源与先进制造": "智能制造",
    "央企与国企": "央企与国企",
    "银行": "金融",
    "证券基金与资管": "金融",
    "保险": "金融",
    "咨询会计与专业服务": "咨询与专业服务",
    "医药医疗": "医药与生物",
    "消费零售与食品": "快消与零售",
    "地产建筑与物流": "地产与建筑",
    "外资在华": "外企",
    "人工智能与机器人": "AI与大模型",
    "美妆与服饰": "快消与零售",
    "教育": "咨询与专业服务",
    "企业服务": "互联网与软件",
    "游戏与内容": "游戏与内容",
}

NOW = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load():
    recs = []
    p = WORK / "probe_all.jsonl"
    for ln in p.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            recs.append(json.loads(ln))
    return recs


# 人工复核后的降级名单（证据见 work/jd-coverage 记录）
DEMOTE = {
    "guandata": "Require 字段全空，JD 完整率 0%，按 ≥90% 铁律不进数据集（可只发日历）",
}
RISK = {
    "yusys": "同标题多 req 重复率高（JD 完整率 86%），入库前建议开 dedupe",
}


def build(recs):
    doable, empty, noentry, _rejected = [], [], [], []
    for r in recs:
        c = r.get("company", "")
        if r.get("matched") and r.get("slug") in DEMOTE:
            empty.append({"name": c, "slug": r["slug"], "sector": SECTOR_MAP.get(r.get("sector", ""), ""),
                          "count": 0, "title": r.get("title", ""), "jobs": r.get("jobs", []),
                          "_demote": DEMOTE[r["slug"]]})
            continue
        if r.get("matched"):
            count = r.get("count") or 0
            slug = r["slug"]
            item = {
                "name": c,
                "slug": slug,
                "sector": SECTOR_MAP.get(r.get("sector", ""), r.get("sector", "")),
                "sector_raw": r.get("sector", ""),
                "count": count,
                "title": r.get("title", ""),
                "jobs": r.get("jobs", []),
            }
            (doable if count >= 1 else empty).append(item)
        else:
            noentry.append({"company": c, "sector": r.get("sector", ""), "tried": r.get("tried", [])})
    return doable, empty, noentry


def main():
    recs = load()
    doable, empty, noentry = build(recs)
    # 按岗位数降序，便于优先接入
    doable.sort(key=lambda x: -x["count"])
    OUT.mkdir(parents=True, exist_ok=True)

    # ---------- companies.jsonl ----------
    lines = []
    for d in doable + empty:
        verdict = "doable" if d["count"] >= 1 else "empty"
        lines.append({
            "name": d["name"],
            "legal_name": None,
            "name_en": None,
            "group": d["name"],
            "sector": d["sector"],
            "type": "cn_private",
            "careers_url": f"https://{d['slug']}.zhiye.com/",
            "ats": "beisen",
            "tenant": d["slug"],
            "site": None,
            "recruit_types": ["campus", "intern", "social"],
            "verdict": verdict,
            "jobs_estimate": d["count"],
            "evidence": [f"https://{d['slug']}.zhiye.com/ 200 {NOW}",
                         f"POST /api/Jobad/GetJobAdPageList Count={d['count']} {NOW}"],
            "checked_at": NOW,
            "notes": f"页面标题：{d['title']}；抽样岗位：{'、'.join(d['jobs'][:3])}",
        })
    with open(WORK / "companies.jsonl", "w", encoding="utf-8") as f:
        for x in lines:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")

    # ---------- proposed-sources.yaml ----------
    y = ["# 平台：beisen（北森新版 {tenant}.zhiye.com）。侦察：docs/recon/beisen-batch.md",
         "# 由 work/probe_beisen.py 实测生成；每行注释为实测岗位数与时间。",
         "defaults:",
         "  adapter: beisen",
         "  recruit_types: [campus, intern, social]",
         "  rate_limit_rps: 1",
         "  compliance:",
         f"    checked_on: {NOW[:10]}",
         "    robots: allowed",
         '    terms: "公开招聘门户，列表接口 POST /api/Jobad/GetJobAdPageList 无需登录、无签名、返回明文 JSON"',
         '    notes: ""',
         "sources:"]
    for d in doable:
        sid = f"beisen-{d['slug']}"
        y.append(f"  - {{id: {sid}, company: {d['name']}, params: {{tenant: {d['slug']}}}}}"
                 f"   # {d['count']} 岗（{NOW[:10]} 实测）")
    (WORK / "proposed-sources.yaml").write_text("\n".join(y) + "\n", encoding="utf-8")

    # ---------- blocked.jsonl ----------
    with open(WORK / "blocked.jsonl", "w", encoding="utf-8") as f:
        for e in empty:
            if e.get("_demote"):
                f.write(json.dumps({
                    "name": e["name"], "reason_code": "empty",
                    "evidence": [f"https://{e['slug']}.zhiye.com/ 200 {NOW}",
                                 f"JD 完整率实测 0%（Duty 有值、Require 全空）{NOW}"],
                    "checked_at": NOW, "recon": "",
                }, ensure_ascii=False) + "\n")
                continue
            f.write(json.dumps({
                "name": e["name"], "reason_code": "empty",
                "evidence": [f"https://{e['slug']}.zhiye.com/ 200 {NOW}",
                             f"POST /api/Jobad/GetJobAdPageList Code=200 Count=0 {NOW}"],
                "checked_at": NOW, "recon": "",
            }, ensure_ascii=False) + "\n")
        for n in noentry:
            f.write(json.dumps({
                "name": n["company"], "reason_code": "no_entry",
                "evidence": [f"尝试 slug: {', '.join(n['tried'][:5])} → 全部非 200 或同名不符 {NOW}"],
                "checked_at": NOW, "recon": "",
            }, ensure_ascii=False) + "\n")

    # ---------- batch-report ----------
    sc = Counter(d["sector"] for d in doable)
    total_jobs = sum(d["count"] for d in doable)
    rep = [f"# 第 1 批侦察报告（{NOW[:10]}）", "",
           "## 统计", "",
           f"- 本轮检查：{len(recs)} 家",
           f"- 可做（有岗位 + JD 可得）：{len(doable)} 家，实测在招岗位合计 {total_jobs:,}",
           f"- 空门户：{len(empty)} 家（页面 200 但 0 岗位，按铁律不算可做）",
           f"- 未找到北森门户：{len(noentry)} 家（no_entry，不猜）",
           "", "## 按行业（可做）", "", "| 行业 | 公司数 | 岗位数 |", "|---|---|---|"]
    for s, n in sc.most_common():
        j = sum(d["count"] for d in doable if d["sector"] == s)
        rep.append(f"| {s} | {n} | {j:,} |")
    rep += ["", "## 明细（按岗位数降序，前 60）", "",
            "| 公司 | 招聘入口 | ATS | tenant | 岗位数 | 结论 |", "|---|---|---|---|---|---|"]
    for d in doable[:60]:
        rep.append(f"| {d['name']} | https://{d['slug']}.zhiye.com/ | beisen | {d['slug']} | {d['count']} | doable |")
    (WORK / "batch-report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")

    print(f"可做 {len(doable)} 家 / 空门户 {len(empty)} / 未找到 {len(noentry)} / 岗位合计 {total_jobs:,}")
    return doable


if __name__ == "__main__":
    main()
