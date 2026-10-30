"""对照覆盖目标（targets/top_companies.yaml）与已接入的数据源，输出覆盖率报告（Markdown）。

用法：python scripts/coverage_report.py [--db data/jobs.db] > coverage.md
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.pipeline.calendar import match_targets  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402


def load_targets(path: Path = ROOT / "targets" / "top_companies.yaml") -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_industries(path: Path = ROOT / "targets" / "industries.yaml") -> dict:
    """365 行细分行业 → 每行 2-4 家代表企业；文件不存在时返回空。"""
    return yaml.safe_load(path.read_text(encoding="utf-8"))["sectors"] if path.exists() else {}


def load_industry_aliases(path: Path = ROOT / "targets" / "industry_targets.yaml") -> dict:
    """行业池自己的别名表（只作用于行业代表企业，不污染核心池）。"""
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")).get("aliases") or {}


CAREERS_PATH = ROOT / "targets" / "coverage_evidence.yaml"

# 「没覆盖」的原因分类：只按我们记录过的招聘入口 URL 归类，没记录过的一律 unknown。
REASON_PATTERNS = (
    ("moka", ("mokahr.com",)),
    ("aggregator", ("zhaopin.com", "liepin.com", "51job.com", "yingjiesheng.com", "nowcoder.com")),
    ("platform", ("zhiye.com", "hotjob.cn", "jobs.feishu.cn", "myworkdayjobs.com", "tupu360.com", "gllue.com")),
)


def validate_careers(payload: object) -> dict[str, str]:
    """验证最小入口证据；缺失或损坏不能静默变成「全部 unknown」。"""
    if (not isinstance(payload, dict) or type(payload.get("schema_version")) is not int
            or payload["schema_version"] != 1):
        raise ValueError("coverage evidence must have schema_version: 1")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("coverage evidence must contain a non-empty entries list")
    out: dict[str, str] = {}
    for index, row in enumerate(entries, start=1):
        if not isinstance(row, dict) or set(row) - {"company", "url", "checked_at"}:
            raise ValueError(f"coverage evidence entry {index}: invalid fields")
        company, url = row.get("company"), row.get("url")
        if not isinstance(company, str) or not company.strip() or company in out:
            raise ValueError(f"coverage evidence entry {index}: empty or duplicate company")
        if not isinstance(url, str):
            raise ValueError(f"coverage evidence entry {index}: URL must be a string")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(f"coverage evidence entry {index}: URL must be a public HTTP(S) entry")
        checked_at = row.get("checked_at")
        if checked_at is not None:
            if not isinstance(checked_at, str):
                raise ValueError(f"coverage evidence entry {index}: checked_at must be an ISO timestamp or null")
            try:
                stamp = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"coverage evidence entry {index}: invalid checked_at timestamp") from exc
            if stamp.tzinfo is None:
                raise ValueError(f"coverage evidence entry {index}: checked_at must include a timezone")
        out[company] = url
    return out


def load_careers(path: Path | None = None) -> dict[str, str]:
    """入口只是侦察线索，不证明公司归属、可抓取性或仅有这一条入口。"""
    path = path if path is not None else CAREERS_PATH
    return validate_careers(yaml.safe_load(path.read_text(encoding="utf-8-sig")))


def reason_of(url: str) -> str:
    low = url.lower()
    for reason, needles in REASON_PATTERNS:
        if any(n in low for n in needles):
            return reason
    return "self" if low.startswith("http") else "unknown"


def uncovered_reasons(targets: dict, matched: dict[str, list[str]],
                      careers: dict[str, str]) -> dict[str, int]:
    """未覆盖目标的入口类型分布，用来解释覆盖率为什么上不去。"""
    blocked = targets.get("blocked") or {}
    counts: dict[str, int] = {}
    seen: set[str] = set()
    for names in list(targets["sectors"].values()) + list((targets.get("provinces") or {}).values()):
        for n in names:
            if n in seen or matched.get(n) or n in blocked:
                continue
            seen.add(n)
            reason = reason_of(careers.get(n, ""))
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def match(targets: dict, companies: set[str]) -> dict[str, list[str]]:
    """与日历共用同一套匹配（精确匹配优先，别名生效），避免两处规则漂移。"""
    return match_targets(targets, companies)


def channel_coverage(targets: dict, sources: list) -> dict[str, set[str]]:
    """官方优先，聚合只计补充覆盖；有两种入口的目标另报交集。停用源不计覆盖。"""
    blocked = targets.get("blocked") or {}
    covered = {}
    for kind in ("official", "aggregator"):
        companies = {s.company for s in sources if s.enabled and s.source_kind == kind}
        covered[kind] = {name for name, found in match(targets, companies).items()
                         if found and name not in blocked}
    return {"official": covered["official"],
            "aggregator": covered["aggregator"] - covered["official"],
            "overlap": covered["aggregator"] & covered["official"]}


def render(targets: dict, matched: dict[str, list[str]], jobs: dict[str, int] | None = None,
           companies: set[str] | None = None, aggregator: set[str] | None = None,
           careers: dict[str, str] | None = None, channels: dict[str, set[str]] | None = None) -> str:
    blocked = targets.get("blocked") or {}
    total = len(matched)
    # blocked 的公司即使被子串误匹配（「京东」in「京东方」）也不能算已覆盖
    covered = sum(1 for k, v in matched.items() if v and k not in blocked)
    lines = ["# 覆盖率报告", "",
             f"目标 {total} 家：已覆盖 **{covered}**（{covered / total:.0%}），"
             f"不可合规覆盖 {len(blocked)}，待侦察 {total - covered - len(blocked)}。", ""]
    if channels is None and aggregator:
        agg_matched = match(targets, aggregator)
        agg_covered = {k for k, v in agg_matched.items() if v and k not in blocked}
        all_covered = {k for k, v in matched.items() if v and k not in blocked}
        channels = {"official": all_covered - agg_covered, "aggregator": agg_covered, "overlap": set()}
    if channels is not None:
        official, aggregate = len(channels["official"]), len(channels["aggregator"])
        lines += ["## 分口径", "",
                  "| 口径 | 已覆盖 | 覆盖率 | 说明 |", "|---|---|---|---|",
                  f"| 官方直连 | {official} | {official / total:.0%} | 公司自有招聘系统（北森/大易/飞书/Workday 等） |",
                  f"| 聚合补充 | {aggregate} | {aggregate / total:.0%} | 公开聚合入口；不重复计入已有官方入口的目标 |",
                  f"| 合计 | {covered} | {covered / total:.0%} | 去重后 |", ""]
        if channels["overlap"]:
            lines += [f"另有 {len(channels['overlap'])} 家同时具备官方和聚合入口，计入官方口径。", ""]
    lines += [
             "| 行业 | 目标 | 已覆盖 | 覆盖率 |", "|---|---|---|---|"]
    for sector, names in targets["sectors"].items():
        c = sum(1 for n in names if matched[n] and n not in blocked)
        lines.append(f"| {sector} | {len(names)} | {c} | {c / len(names):.0%} |")
    prov = targets.get("provinces") or {}
    if prov:
        lines += ["", f"## 分省覆盖率（{len(prov)} 个省级行政区）", "",
                  "| 省份 | 目标 | 已覆盖 | 覆盖率 |", "|---|---|---|---|"]
        empty = []
        for p, names in prov.items():
            uniq = list(dict.fromkeys(names))
            c = sum(1 for n in uniq if matched.get(n) and n not in blocked)
            lines.append(f"| {p} | {len(uniq)} | {c} | {c / len(uniq):.0%} |")
            if c == 0:
                empty.append(p)
        if empty:
            lines.append(f"\n零覆盖省份 {len(empty)} 个：{'、'.join(empty)}")
    lines += ["", "## 已覆盖", ""]
    for sector, names in targets["sectors"].items():
        got = [n for n in names if matched[n] and n not in blocked]
        if got:
            def fmt(n):
                cnt = sum((jobs or {}).get(c, 0) for c in matched[n])
                return f"{n}（{cnt}）" if jobs else n
            lines.append(f"- **{sector}**：" + "、".join(fmt(n) for n in got))
    ind = load_industries()
    comp = companies or set()
    if ind:
        lines += ["", "## 细分行业覆盖（365 行）", "", "| 板块 | 行数 | 有覆盖 | 覆盖率 |", "|---|---|---|---|"]
        hit_rows = miss_rows = 0
        for sec, rows in ind.items():
            hit = 0
            for _line, names in rows.items():
                if any(match_targets({"sectors": {"x": [str(n)]}}, comp).get(str(n)) for n in names):
                    hit += 1
            hit_rows += hit
            miss_rows += len(rows) - hit
            lines.append(f"| {sec} | {len(rows)} | {hit} | {hit / len(rows):.0%} |")
        lines.append(f"\n合计 {hit_rows + miss_rows} 行：有覆盖 **{hit_rows}**（{hit_rows / (hit_rows + miss_rows):.0%}），"
                     f"零覆盖 {miss_rows}。")
        # 行有覆盖 ≠ 代表企业有源：一行 2-4 家，只要一家有源就算「这行有覆盖」。
        # 这段单独按「代表企业」算一遍，避免看报告的人把两个口径混在一起。
        names_all = sorted({str(c) for rows in ind.values() for names in rows.values() for c in names})
        # 行业池有自己的别名表（targets/industry_targets.yaml 的 aliases），
        # 例如 TCL中环←中环股份、威高股份←山东威高——不并进来会把这些算成没覆盖。
        ind_aliases = load_industry_aliases()
        pseudo = {"sectors": {"行业细分": names_all},
                  "aliases": {**(targets.get("aliases") or {}), **ind_aliases}}
        m_ind = match_targets(pseudo, comp)
        cov_ind = [n for n in names_all if m_ind.get(n)]
        core_names = set(matched)
        core_cov = {k for k, v in matched.items() if v and k not in blocked}
        extra = [n for n in names_all if n not in core_names]
        extra_cov = [n for n in extra if m_ind.get(n)]
        union = core_names | set(names_all)
        union_cov = core_cov | set(extra_cov)
        lines += [
            "",
            f"代表企业口径：{len(names_all)} 家里有源 **{len(cov_ind)}**"
            f"（{len(cov_ind) / len(names_all):.0%}）；核心池没有的 {len(extra)} 家里有源 {len(extra_cov)} 家。",
            f"两池合计目标 **{len(union)}** 家，已覆盖 **{len(union_cov)}**"
            f"（{len(union_cov) / len(union):.0%}）。",
        ]
    reasons = uncovered_reasons(targets, matched, load_careers() if careers is None else careers)
    if reasons:
        label = {"moka": "已记录 Moka 入口（访问限制需逐站复核）", "aggregator": "已记录第三方招聘入口",
                 "platform": "平台入口已知但没建成源", "self": "自建站或普通企业页",
                 "unknown": "没有记录过任何招聘入口"}
        total_un = sum(reasons.values())
        lines += ["", "## 未覆盖原因（按记录到的招聘入口）", "",
                  "入口线索不代表已验证公司归属、可抓取性或唯一入口；分类来自版本管理内的最小证据快照。", "",
                  "| 原因 | 家数 | 占比 |", "|---|---|---|"]
        for key in ("platform", "self", "moka", "aggregator", "unknown"):
            if reasons.get(key):
                n = reasons[key]
                lines.append(f"| {label[key]} | {n} | {n / total_un:.0%} |")
    lines += ["", "## 不可合规覆盖", ""] + [f"- {n}：{r}" for n, r in blocked.items()]
    lines += ["", "## 待侦察", ""]
    for sector, names in targets["sectors"].items():
        todo = [n for n in names if not matched[n] and n not in blocked]
        if todo:
            lines.append(f"- **{sector}**：" + "、".join(todo))
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="jobs.db 路径；给出时显示每家在招岗位数")
    ap.add_argument("--json", action="store_true", help="只输出摘要 JSON（给脚本/看板用）")
    ap.add_argument("--evidence", type=Path, default=CAREERS_PATH, help="入口证据 YAML；默认 targets/coverage_evidence.yaml")
    ap.add_argument("--min-coverage", type=float, help="验收下限（0..1），如 0.8；不足时输出报告并退出 1，不改变分母")
    args = ap.parse_args()
    if args.min_coverage is not None and not 0 <= args.min_coverage <= 1:
        ap.error("--min-coverage 必须在 0 到 1 之间")
    targets = load_targets()
    sources = [s for s in load_sources(ROOT / "sources") if s.enabled]
    companies = {s.company for s in sources}
    aggregator = {s.company for s in sources if s.source_kind == "aggregator"}
    channels = channel_coverage(targets, sources)
    jobs = None
    if args.db:
        conn = sqlite3.connect(args.db)
        jobs = dict(conn.execute("SELECT c.name, COUNT(*) FROM job j JOIN company c ON c.id=j.company_id "
                                 "WHERE j.closed_at IS NULL GROUP BY 1"))
    matched = match(targets, companies)
    careers = load_careers(args.evidence)
    blocked = targets.get("blocked") or {}
    total = len(matched)
    covered = sum(1 for k, v in matched.items() if v and k not in blocked)
    exit_code = 0 if args.min_coverage is None or (total and covered / total >= args.min_coverage) else 1
    if args.json:
        ind = load_industries()
        rows = hit = 0
        comp = companies
        for _sec, lines_ in ind.items():
            for _line, names in lines_.items():
                rows += 1
                if any(match_targets({"sectors": {"x": [str(n)]}}, comp).get(str(n)) for n in names):
                    hit += 1
        print(json.dumps({"targets": total, "covered": covered, "blocked": len(blocked),
                          "sources": len({s.id for s in sources}),
                          "companies": len(companies), "aggregator_companies": len(aggregator), "industry_rows": rows,
                          "official_covered": len(channels["official"]),
                          "aggregator_covered": len(channels["aggregator"]),
                          "overlap_covered": len(channels["overlap"]),
                          "industry_covered": hit,
                          "uncovered_reasons": uncovered_reasons(targets, matched, careers)}, ensure_ascii=False))
        return exit_code
    print(render(targets, matched, jobs, companies, aggregator, careers, channels), end="")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
