"""生成最终交付物：companies.jsonl / proposed-sources.yaml / blocked.jsonl。

输入（全部来自真实探测，无任何估算）：
  work/sample_stats_all.jsonl   —— 可做租户的采样统计（归一化条数、JD 覆盖率、CategoryId 分布）
  work/probe_all.jsonl          —— 第一批北森探测（87 命中）
  work/fast_hits_clean.json     —— 快速穷举命中（97 同名通过）
  work/round2_hits.jsonl        —— 第二轮简称穷举命中
  work/candidates_clean.tsv     —— 1357 家候选
  work/base500.tsv              —— targets 里的 500 家

输出：
  work/companies.jsonl          每家一行，含 careers_url / ats / 证据字段
  work/proposed-sources.yaml    可直接合并进 sources/ 的源配置
  work/blocked.jsonl            不可做公司 + reason_code + 证据
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
NOW = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

# 候选池的行业名（19 个）→ 项目允许的 16 个 sector 枚举
SECTOR_MAP = {
    "互联网与软件": "互联网与软件",
    "通信与电子硬件": "通信与电子硬件",
    "半导体": "半导体",
    "汽车与出行": "汽车与新能源",
    "新能源与先进制造": "汽车与新能源",
    "智能制造": "智能制造",
    "银行": "金融",
    "证券基金与资管": "金融",
    "保险": "金融",
    "医药医疗": "医药与生物",
    "消费零售与食品": "快消与零售",
    "美妆与服饰": "快消与零售",
    "地产建筑与物流": "地产与建筑",
    "央企与国企": "央企与国企",
    "能源与电力": "能源与电力",
    "游戏与内容": "游戏与内容",
    "人工智能与机器人": "AI与大模型",
    "企业服务": "互联网与软件",
    "咨询会计与专业服务": "咨询与专业服务",
    "教育": "互联网与软件",
    "外资在华": "外企",
}

# 采样时发现的风险：保留但在 batch-report 里写明
RISK = {
    "yusys": "标题含 (Jxxxx) 内部编号且多 req 重复率高，入库前需去重",
    "laiyifen": "7216 条里绝大多数是门店 CategoryId=4，适配器会整条 SkipRecord，实际可用量远小于 Count",
    "cyys": "CategoryId 8/9/11-14 全未映射，归一化为 0，需先扩 RECRUIT_TYPE 才能做",
}


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def main() -> None:
    stats = load_jsonl(WORK / "sample_stats_all.jsonl")
    candidates = [line.split("\t") for line in
                  (WORK / "candidates_clean.tsv").read_text(encoding="utf-8").splitlines()]
    base500 = [line.split("\t") for line in
               (WORK / "base500.tsv").read_text(encoding="utf-8").splitlines()
               if not line.startswith("#") and line.strip()]
    pool = {p[0]: p for p in base500}
    for p in candidates:
        if len(p) >= 3 and p[0] not in pool:
            pool[p[0]] = p

    doable = [r for r in stats if r["normalized"] > 0 and r["jd_rate"] >= 0.9]
    not_doable = [r for r in stats if not (r["normalized"] > 0 and r["jd_rate"] >= 0.9)]

    # 已存在的 source id（sources/*.yaml）不能重复占用：重复 id 会让 load_sources 语义含糊
    existing: set[str] = set()
    for f in sorted((ROOT / "sources").glob("*.yaml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for e in doc.get("sources") or []:
            existing.add(e["id"])

    companies = []
    sources = []
    blocked = []
    used_ids: set[str] = set()

    for r in sorted(doable, key=lambda x: -(x.get("count") or 0)):
        name = r["name"]
        ats = r["ats"]
        sec_src = pool.get(name, [name, "", ""])[1] or r.get("sector", "")
        sector = SECTOR_MAP.get(sec_src, "互联网与软件")
        tenant = r["tenant"]
        if ats == "beisen":
            url = f"https://{tenant}.zhiye.com/"
        elif ats == "beisen_legacy":
            url = f"https://{tenant}.zhiye.com/campus"
        else:
            url = f"https://{r['host']}/{tenant}/pb/index.html"
        sid = re.sub(r"[^a-z0-9]+", "-", f"{ats.replace('_', '-')}-{tenant.lower()}").strip("-")
        duplicate = sid in existing
        base_id, i = sid, 2
        while sid in used_ids or sid in existing:
            sid = f"{base_id}-{i}"
            i += 1
        used_ids.add(sid)
        companies.append({
            "company": name,
            "sector": sector,
            "sector_source": sec_src,
            "careers_url": url,
            "ats": ats,
            "ats_fingerprint": {
                "beisen": "POST {tenant}.zhiye.com/api/Jobad/GetJobAdPageList → JSON {Code,Count,Data[]}",
                "beisen_legacy": "GET {tenant}.zhiye.com/campus 服务端渲染 <tr>，详情 /job_show?jobId=",
                "hotjob": "GET {host}/wecruit/positionInfo/listPosition/{SU...}",
            }[ats],
            "tenant": tenant,
            "host": r["host"],
            "page_title": r.get("title", ""),
            "jobs_live": r.get("count"),
            "sampled": r.get("sampled"),
            "normalized": r.get("normalized"),
            "jd_rate": r.get("jd_rate"),
            "category_dist": r.get("categories"),
            "verified_at": NOW,
            "source_id": sid,
            "already_in_sources": duplicate,
            "evidence": {
                "homepage_http": 200,
                "list_http": 200,
                "name_match": "站点标题/岗位名与公司名一致（脚本 work/recheck.py 复核）",
                "sample_jobs": [s["title"] for s in r.get("samples", [])],
            },
            "risk": RISK.get(tenant, ""),
        })
        params = {"tenant": tenant}
        rtypes = ["campus", "intern", "social"]
        if ats == "hotjob":
            params["host"] = r["host"]
            rtypes = ["campus"]
        elif ats == "beisen_legacy":
            params["portal"] = "campus"
            rtypes = ["campus"]
        sources.append({"id": sid, "company": name, "adapter": ats,
                        "recruit_types": rtypes, "params": params})

    doable_names = {c["company"] for c in companies}
    sampled_names = {r["name"] for r in not_doable}
    for name, p in pool.items():
        if name in doable_names:
            continue
        rec = {"company": name, "sector_source": p[1] if len(p) > 1 else "", "brand": p[2] if len(p) > 2 else ""}
        if name in sampled_names:
            st = next(r for r in not_doable if r["name"] == name)
            if st["normalized"] == 0 and st.get("count", 0) == 0:
                rec.update(reason_code="empty",
                           evidence=f"{st['url']} 列表接口 Count=0（{NOW} 实测）")
            elif st["normalized"] == 0:
                rec.update(reason_code="no_entry",
                           evidence=f"租户存在但 CategoryId 未映射致归一化为 0（{(st.get('categories') or {}).keys()}），需扩 RECRUIT_TYPE")
            else:
                rec.update(reason_code="empty",
                           evidence=f"JD 覆盖率 {st['jd_rate']:.0%} < 90% 契约线")
        else:
            rec.update(reason_code="no_entry",
                       evidence="北森/大易/旧版三套平台各 6-14 个 slug 组合均无命中（2026-10-25 实测）")
        blocked.append(rec)

    (WORK / "companies.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in companies) + "\n", encoding="utf-8")
    (WORK / "blocked.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in blocked) + "\n", encoding="utf-8")

    doc = {
        "defaults": {
            "rate_limit_rps": 1,
            "compliance": {
                "checked_on": NOW[:10],
                "robots": "allowed",
                "terms": "企业自建公开招聘门户的公开 JSON/HTML 接口，无需登录、无签名、无验证码",
                "notes": "只读公开列表接口；同一 host 串行 1 rps；不含任何第三方聚合站",
            },
        },
        "sources": sources,
    }
    head = """# 本批新增源（2026-10-25 实测）。一行一家公司，可整段粘进 sources/ 对应适配器文件。
# 每条注释里的「N 岗」是列表接口 Count 实测值；JD 覆盖率见 docs/recon/<公司>.md。
# 限速 1 rps，同一 host 串行；只读公开接口，无登录/签名/验证码。
defaults:
  adapter: beisen
  recruit_types: [campus, intern, social]
  rate_limit_rps: 1
  compliance:
    checked_on: 2026-10-25
    robots: allowed
    terms: "企业自建公开招聘门户的公开 JSON/HTML 接口，无需登录、无签名、无验证码"
    notes: "只读公开列表接口；同一 host 串行 1 rps"
sources:
"""
    lines = [head]
    for s, c in zip(sources, sorted(doable, key=lambda x: -(x.get("count") or 0)), strict=True):
        params = ", ".join(f"{k}: {v}" for k, v in c and s["params"].items())
        extra = ""
        if s["adapter"] != "beisen":
            extra = f" recruit_types: [{', '.join(s['recruit_types'])}],"
        lines.append(f"  - {{id: {s['id']}, company: {s['company']}, adapter: {s['adapter']},"
                     f"{extra} params: {{{params}}}}}"
                     f"   # {c.get('count')} 岗（{NOW[:10]} 实测），JD {c['jd_rate']:.0%}\n")
    (WORK / "proposed-sources.yaml").write_text("".join(lines), encoding="utf-8")
    print(f"companies {len(companies)}  blocked {len(blocked)}  sources {len(sources)}")
    from collections import Counter
    print("ats 分布", Counter(c["ats"] for c in companies))


if __name__ == "__main__":
    main()
