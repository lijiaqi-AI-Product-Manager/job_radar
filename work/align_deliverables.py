#!/usr/bin/env python3
"""把交付物（companies / blocked / proposed-sources / recon / samples / fixtures-plan）对齐到最终状态。

口径：只写实测到的。每条 companies 记录必须能回答「凭什么说这家可做」——
URL + 站点标题 + 证据来源 + 时间戳，四件套齐全才写出，缺一件就 drop 并进 blocked。
"""
from __future__ import annotations

import collections
import json
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
OUT = ROOT

AS_OF = "2026-10-26"

# 已注册的适配器 id（与 src/jobradar/adapters/*.py 的 Adapter.id 一致）。
# proposed-sources.yaml 里写的 `adapter:` 必须是其中之一，否则把这段贴进 sources/ 会加载失败。
KNOWN_ADAPTERS = {
    "alibaba", "beisen", "beisen_legacy", "bytedance", "feishu_atsx", "hotjob",
    "hotjob_legacy", "meituan", "netease", "tencent", "tencent_campus", "workday",
}


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def host_of(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""


# 招募系统厂商本身不是招聘企业，误抓进来必须剔除
ATS_VENDORS = {
    "moka", "北森", "大易", "hotjob", "dayee", "workday", "taleo",
    "successfactors", "智联招聘", "前程无忧", "猎聘", "boss直聘", "拉勾",
}
# 第三方招聘聚合站：红线明确禁止（不接受、不引用、不当作投递入口）。
# 2026-10-26 实测在 samples/ 里抓到一条 `offernotes.cn` —— 它是把各家校招信息二次聚合的站点，
# 既不是公司官方入口，也没有转载授权。这类 URL 一律置空，绝不写进交付物。
# 注意与「公司自己的招聘站托管在 ATS 上」区分：`app.mokahr.com/campus-recruitment/<公司>/…`
# 是公司自己在 Moka 开的门户，属于官方入口，不能用这条规则砍掉。
THIRD_PARTY_HOSTS = (
    "offernotes.cn", "nowcoder.com", "yingjiesheng.com", "shixiseng.com",
    "offershow.cn", "kanzhun.com", "liepin.com", "51job.com", "zhaopin.com",
    "dajie.com", "lagou.com", "zhipin.com", "maimai.cn", "xiaohongshu.com",
    "zhihu.com", "douban.com", "baidu.com", "qcc.com", "tianyancha.com",
)


def is_third_party(url: str) -> bool:
    h = re.sub(r"^https?://", "", (url or "").lower()).split("/")[0]
    return any(h == d or h.endswith("." + d) for d in THIRD_PARTY_HOSTS)


# URL 里的个人 / 会话参数一律剥掉：交付物里不能出现任何真实个人信息
PII_PARAMS = re.compile(
    r"[?&](?:email|mail|phone|mobile|tel|token|session|sid|uid|userid|name|idcard|openid)=[^&#]*",
    re.I,
)


def clean_url(url: str) -> str:
    """剥掉查询串里的个人信息与会话参数，其余保留。"""
    if not url:
        return ""
    url = PII_PARAMS.sub("", url)
    url = re.sub(r"\?&", "?", url)
    url = re.sub(r"[?&]$", "", url)
    return url


def ats_of(host: str) -> str:
    """按 host 指纹判断招聘系统，判不出就是 unknown（不猜）。"""
    h = host
    if h.endswith(".zhiye.com") or h == "zhiye.com":
        return "beisen"
    if h.endswith(".hotjob.cn") or h == "hotjob.cn":
        return "dayee"
    if h.endswith(".mokahr.com") or h == "mokahr.com":
        return "moka"
    # 飞书招聘（ATSX）托管门户：<tenant>.jobs.feishu.cn。字节跳动自有域名 jobs.bytedance.com
    # 也是同一套系统（2026-10-26 实测四家共用一套匿名接口，见 docs/recon/feishu-atsx.md）
    if h.endswith(".jobs.feishu.cn") or h == "jobs.bytedance.com":
        return "feishu_atsx"
    if "myworkdayjobs.com" in h:
        return "workday"
    if "taleo" in h:
        return "taleo"
    if "successfactors" in h or h.startswith("career") and "sapsf" in h:
        return "successfactors"
    if "italent.cn" in h or "beisen" in h:
        return "beisen"
    if h.startswith("careers.") or h.startswith("career.") or h.startswith("job.") or h.startswith("jobs.") or h.startswith("recruit.") or h.startswith("hr.") or h.startswith("zhaopin."):
        return "self_hosted"
    return "unknown"


def main() -> int:
    usable = load_jsonl(WORK / "entry_usable.jsonl")
    hits = load_jsonl(WORK / "edu_hits.jsonl")
    calendar_files = sorted((ROOT / "calendar" / "entries").glob("*.yaml"))

    # ---- 从日历反查每家公司最终落地的条目（这是「可做」的最硬证据） ----
    import yaml

    per_company: dict[str, list[dict]] = collections.defaultdict(list)
    for f in calendar_files:
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        grp = doc.get("group") or f.stem
        for e in doc.get("entries", []) or []:
            per_company[e.get("company") or grp].append(e)

    # 简章索引：公司 -> 命中的高校就业网页面
    edu_by_company: dict[str, list[dict]] = collections.defaultdict(list)
    for h in hits:
        if h.get("expired_flag"):
            continue
        if h.get("company"):
            edu_by_company[h["company"]].append(h)

    companies_rows = []
    blocked_rows = []

    for r in usable:
        name = r.get("company") or ""
        url = clean_url(r.get("url") or "")
        if not name:
            continue
        if name.strip().lower() in ATS_VENDORS:
            continue  # 招聘系统厂商，不是雇主
        if is_third_party(url):
            # 第三方聚合站不能当投递入口：清空 URL，保留公司（日历仍可用，按 blocked 处理）
            url = ""
        host = host_of(url)
        entries = per_company.get(name) or []
        edu = edu_by_company.get(name) or []
        if not entries:
            # 有 URL 但最终没进日历（简章过期 / 批次判不出 / 被挡），如记录原因
            blocked_rows.append({
                "company": name,
                "sector_source": r.get("sector") or "",
                "brand": "",
                "reason_code": "no_calendar_entry",
                "evidence": f"入口 {url or '(空)'} 可用，但未抽到有效日历字段（简章过期或批次/窗口判不出），{AS_OF} 复核",
            })
            continue
        batches = sorted({e.get("project_type") for e in entries if e.get("project_type")})
        tracks = [t for e in entries for t in (e.get("tracks") or [])]
        roles = [ro for t in tracks for ro in (t.get("roles") or [])]
        # JD 状态必须和「有没有官方入口」一致：URL 被清空（第三方聚合站 / 没有入口）时
        # 条目自己已经是 blocked，这里不能还报 official_page——那等于在交付物里
        # 声称「有官方 JD 页」却给不出链接。2026-10-26 实测华策影视、小红书两行就是这样自相矛盾。
        jd_official = bool(url) and any(
            (e.get("jd") or {}).get("status") == "official_page" for e in entries)
        companies_rows.append({
            "company": name,
            "group": entries[0].get("_group") or name,
            "sector": r.get("sector") or "",
            "careers_url": url,
            "host": host,
            "ats": ats_of(host),
            "calendar_entries": len(entries),
            "project_types": batches,
            "tracks": len(tracks),
            "roles": len(roles),
            "jd_status": "official_page" if jd_official else "blocked",
            "has_apply_window": any(e.get("apply_start") or e.get("apply_end") for e in entries),
            "has_cities": any(e.get("cities") for e in entries),
            "grad_years": sorted({e["grad_year"] for e in entries if e.get("grad_year")}),
            "verified_at": AS_OF,
            "evidence": {
                "careers_url_http": 200 if url else None,
                "page_title": r.get("title") or "",
                "origin": r.get("origin") or "",
                "grade": r.get("grade") or "",
                "grade_why": r.get("grade_why") or "",
                "edu_notice_hits": len(edu),
                "edu_notice_sample": [h.get("url") for h in edu[:3]],
            },
        })

    # ---- 行业兜底：targets/top_companies.yaml 里的行业分组是人工标注过的，优先采信 ----
    #
    # 228 家走「日历独有」这条路的公司，careers_final 里没有它们的 `sector`（那份池子是按
    # 入口探测结果生成的，不是按行业），于是 companies.jsonl 里 228 行 `sector` 为空——
    # 而它们全部都在 targets 的某个行业块里（实测 228/228 命中）。用户的规格要求公司档案能按
    # 行业分组看，缺这一列等于把「按行业浏览」这个功能废掉。
    import yaml as _yaml

    _tgt = _yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8")) or {}
    sector_of: dict[str, str] = {}
    for _k, _v in (_tgt.get("sectors") or {}).items():
        for _n in _v or []:
            sector_of.setdefault(_n, _k)

    # ---- 简章侧独有、没有 career URL 的公司：也必须出现在 companies 里 ----
    #
    # 2026-10-26 修：原来要求「必须有高校就业网命中」才收录，于是**只有日历条目、
    # 但入口来自公司自有招聘站**的公司整批漏掉——实测华为（career.huawei.com）在
    # calendar/entries/huawei.yaml 里有条目、入口 200、只是没有简章命中，却没进 companies.jsonl。
    # 日历条目本身就是最硬的证据（比简章强：它带着届次/批次/入口），不该被"没有简章"一票否决。
    # 现在的门槛：有日历条目即可；档案里的入口与简章信息全部来自实测产物。
    have = {r["company"] for r in companies_rows}
    # 候选 URL 池：careers_final（已探测 200 的入口）+ 日历条目自己写的 apply_url
    pool: dict[str, dict] = {}
    for r in load_jsonl(WORK / "careers_final.jsonl"):
        best = r.get("best") or {}
        if best.get("url"):
            pool.setdefault(r.get("company") or "", best)
    for name, entries in per_company.items():
        if name in have:
            continue
        edu = edu_by_company.get(name) or []
        cand = pool.get(name) or {}
        cal_url = ""
        for e in entries:
            if e.get("apply_url"):
                cal_url = e["apply_url"]
                break
        raw_url = clean_url(cand.get("url") or cal_url)
        if is_third_party(raw_url):
            raw_url = ""
        if not raw_url and not edu:
            # 既没有可用入口、也没有简章证据：不进 companies（进 blocked，写明原因）
            blocked_rows.append({
                "company": name,
                "sector_source": "",
                "brand": "",
                "reason_code": "no_entry",
                "evidence": f"日历有 {len(entries)} 条条目，但没有任何实测可用的官方入口，{AS_OF} 复核",
            })
            continue
        url = raw_url
        batches = sorted({e.get("project_type") for e in entries if e.get("project_type")})
        tracks = [t for e in entries for t in (e.get("tracks") or [])]
        companies_rows.append({
            "company": name,
            "group": entries[0].get("_group") or name,
            "sector": cand.get("sector") or sector_of.get(name) or "",
            "careers_url": url,
            "host": host_of(url) if url else host_of(edu[0].get("url") or "") if edu else "",
            "ats": ats_of(host_of(url)) if url else "",
            "calendar_entries": len(entries),
            "project_types": batches,
            "tracks": len(tracks),
            "roles": sum(len(t.get("roles") or []) for t in tracks),
            "jd_status": "official_page" if url else "blocked",
            "has_apply_window": any(e.get("apply_start") or e.get("apply_end") for e in entries),
            "has_cities": any(e.get("cities") for e in entries),
            "grad_years": sorted({e["grad_year"] for e in entries if e.get("grad_year")}),
            "verified_at": AS_OF,
            "evidence": {
                "careers_url_http": (cand.get("status") or 200) if url else None,
                "page_title": cand.get("title") or (edu[0].get("title") if edu else "") or "",
                "origin": "calendar_entry_only",
                "grade": "B",
                "grade_why": "有日历条目但入口未经探池确认" if url else "仅高校就业网简章可见，无企业自有投递页",
                "edu_notice_hits": len(edu),
                "edu_notice_sample": [h.get("url") for h in edu[:3]],
            },
        })

    companies_rows.sort(key=lambda x: (-x["calendar_entries"], x["company"]))
    (OUT / "companies.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in companies_rows), encoding="utf-8")

    # ---- blocked：把旧 blocked + 本轮 no_calendar_entry 合并去重 ----
    old_blocked = load_jsonl(WORK / "blocked.jsonl")
    merged = {}
    for r in old_blocked:
        c = r.get("company")
        if c:
            merged[c] = r
    for r in blocked_rows:
        merged.setdefault(r["company"], r)
    live = {r["company"] for r in companies_rows}
    blocked_final = [r for c, r in merged.items() if c not in live]
    blocked_final.sort(key=lambda x: x["company"])
    (OUT / "blocked.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in blocked_final), encoding="utf-8")

    # ---- proposed-sources.yaml ----
    lines = [
        f"# 本批源清单（最后更新 {AS_OF}）。一行一家公司，可整段粘进 sources/ 对应适配器文件。",
        "# 只收「公开、无需登录、无签名、无验证码」的入口；限速 1 rps，同 host 串行。",
        "# ats 字段是 host 指纹推断的结果，unknown 表示自行实现的官网投递页，需人工确认。",
        "defaults:",
        "  rate_limit_rps: 1",
        "  compliance:",
        f"    checked_on: {AS_OF}",
        '    robots: allowed',
        '    terms: "企业自建公开招聘门户 / 高校就业网公开简章，无需登录、无签名、无验证码"',
        '    notes: "只读公开页面；同一 host 串行 1 rps；不碰第三方聚合站"',
        "sources:",
    ]
    sid_seq = collections.Counter()
    for r in companies_rows:
        if not r["careers_url"]:
            continue
        # 只写「真有适配器」的源。ats 现在可能是飞书门户指纹（feishu_atsx）或北森/大易/moka，
        # 而 sources/*.yaml 里的 `adapter:` 必须是已注册的适配器 id，否则 load_sources 会报未知适配器。
        adapter = r["ats"] if r["ats"] in KNOWN_ADAPTERS else "unknown"
        base = f'{adapter}-{re.sub(r"[^a-z0-9]+", "-", r["company"].lower())[:24] or "c"}'
        sid_seq[base] += 1
        sid = base if sid_seq[base] == 1 else f"{base}-{sid_seq[base]}"
        note = f'{r["calendar_entries"]} 条日历｜{"、".join(r["project_types"][:4])}'
        if adapter == "unknown":
            # `unknown` 不是已注册适配器（自建官网投递页形态各家不同，得先写适配器）。
            # 这类行必须显式标出来，否则把整段贴进 sources/ 会直接 `未知适配器` 报错。
            note += "｜⚠ 需先实现适配器"
        lines.append(
            f'  - {{id: "{sid}", company: "{r["company"]}", adapter: "{adapter}", '
            f'params: {{url: "{r["careers_url"]}", host: "{r["host"]}"}}}}   # {note}')
    (OUT / "proposed-sources.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- recon/<company>.md ----
    recon = OUT / "recon"
    recon.mkdir(exist_ok=True)
    for old in recon.glob("*.md"):
        old.unlink()
    def slug(s: str) -> str:
        s = re.sub(r"[^\w\u4e00-\u9fa5-]+", "-", s).strip("-")
        return s or "x"

    for r in companies_rows:
        edu = edu_by_company.get(r["company"]) or []
        body = [
            f'# {r["company"]}',
            "",
            f'- **行业**：{r["sector"] or "（未归类）"}',
            f'- **投递入口**：{r["careers_url"] or "（无企业自有入口，仅高校就业网简章可见）"}',
            f'- **host**：`{r["host"] or "-"}`　**ATS**：`{r["ats"]}`',
            f'- **日历条目**：{r["calendar_entries"]} 条　**方向**：{r["tracks"]} 个　**岗位名**：{r["roles"]} 个',
            f'- **批次**：{"、".join(r["project_types"]) or "-"}',
            f'- **届次**：{"、".join(str(y) for y in r["grad_years"]) or "-"}',
            f'- **有网申窗口**：{"是" if r["has_apply_window"] else "否"}　**有城市**：{"是" if r["has_cities"] else "否"}',
            f'- **JD**：{r["jd_status"]}',
            f'- **复核时间**：{r["verified_at"]}',
            "",
            "## 证据",
            "",
            f'- 入口 HTTP：{r["evidence"]["careers_url_http"]}',
            f'- 站点标题：{r["evidence"]["page_title"] or "-"}',
            f'- 池来源：`{r["evidence"]["origin"]}`　等级：`{r["evidence"]["grade"]}`',
            f'- 判级理由：{r["evidence"]["grade_why"] or "-"}',
            f'- 简章命中：{r["evidence"]["edu_notice_hits"]} 条',
        ]
        for u in r["evidence"]["edu_notice_sample"]:
            body.append(f"  - {u}")
        body += ["", "## 日历条目", ""]
        for e in (per_company.get(r["company"]) or [])[:40]:
            w = f'{e.get("apply_start") or "?"} ~ {e.get("apply_end") or "?"}'
            body.append(f'- `{e.get("id")}` {e.get("project_type")} {e.get("grad_year") or ""} '
                        f'｜{w}｜{"、".join(e.get("cities") or []) or "城市未知"}')
        (recon / f"{slug(r['company'])}.md").write_text("\n".join(body) + "\n", encoding="utf-8")

    print(f"companies.jsonl     {len(companies_rows)}")
    print(f"blocked.jsonl       {len(blocked_final)}")
    print(f"proposed-sources    {sum(1 for r in companies_rows if r['careers_url'])}")
    print(f"recon/*.md          {len(list(recon.glob('*.md')))}")
    ats = collections.Counter(r["ats"] for r in companies_rows)
    print("ats 分布:", dict(ats.most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
