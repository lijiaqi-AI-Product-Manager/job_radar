"""发布自检：把 v1.0 的门槛变成可执行的检查，而不是文档里的一句话。

用法：
    uv run python scripts/release_check.py --home ~/.jobradar --sources sources --targets targets/top_companies.yaml

退出码 0 表示全部达标；1 表示有未达标项（逐条打印当前值与门槛）。
在 CI 里可以 nightly 跑一次，提醒离发布还差多少。
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.pipeline.calendar import match_targets, target_names  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

# 门槛（可随实际调整，但要有共识后再改）。
# 分子分母都按「当前目标总数」算比例，不再写死绝对值——2026-10-26 目标从 500 扩到 1021 家后，
# 原来的 160/450 两个绝对值让「目标覆盖」变成 0/0，门槛形同虚设。
# min_* 是绝对下限：只有 2 个目标时 1 个覆盖就是 50%，光看比例会误判成"达标"。
GATES = {
    # 配置了启用源的目标公司数，不代表当日有在招岗位。
    "data_coverage_ratio": 0.15,
    "data_coverage_min": 100,
    # 至少一条日历条目的目标公司数
    "calendar_coverage_ratio": 0.42,
    "calendar_coverage_min": 300,
    "campus_city": 0.20,       # 校园岗有城市占比（北森新版门户不返回城市，20% 是当前源结构的现实上限）
    # 日历条目里「城市」填了的占比。城市是用户筛日历的第一维度（「我能在北京投什么」），
    # 空城市的条目对用户等于不可用。2026-10-26 打通 E0 结构化城市前是 41%，打通后 47%。
    "calendar_city": 0.44,
    # 日历条目里「网申时间」至少有一端填了的占比。北森接口不返回截止日，
    # 这条覆盖率的现实上限就是「有多少公司能从简章/大易拿到日期」，别定得比真相高。
    "calendar_window": 0.20,
    "jd_coverage": 0.95,       # 在招岗位有 JD 正文占比
    # 日历字段完整度：一条日历 11 个必填字段里至少填了 7 个的条目占比
    # （2026-10-23 用户要求：集团/公司/届次/项目类型/方向/网申时间/城市/入口/来源/时间戳）
    "calendar_fields": 0.37,
    "calendar_fields_by_company": 0.60,
    # 数据自检：不允许出现「空标题 / 非法招聘类型 / 届次越界 / 网申窗口倒挂 / 同源重复」
    "data_sanity": 0,
}

FILES = ["README.md", "CHANGELOG.md", "COMPLIANCE.md", "LICENSE"]


def _targets(path: Path) -> dict:
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def data_coverage(targets: dict, companies: set[str]) -> tuple[int, int]:
    matched = match_targets(targets, companies)
    blocked = targets.get("blocked") or {}
    covered = sum(1 for name, names in matched.items() if names and name not in blocked)
    return covered, len(target_names(targets))


CAL_FIELDS = ["group_name", "company", "grad_year", "project_type", "tracks", "apply_start",
              "apply_end", "cities", "apply_url", "source_name", "as_of"]


def calendar_fields(calendar_db: Path | None) -> tuple[float, str]:
    """日历字段完整度：人工条目里 ≥7/11 字段的占比。"""
    if not calendar_db or not calendar_db.exists():
        return 0.0, "无 calendar.db", 0.0
    import sqlite3
    con = sqlite3.connect(calendar_db)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM entry WHERE origin='manual'").fetchall()

    def filled(r, k):
        v = r[k]
        if v is None:
            return False
        if isinstance(v, str) and v.strip() in ("", "[]", "null"):
            return False
        if isinstance(v, (list, dict)) and not v:
            return False
        return True

    if not rows:
        return 0.0, "0 条", 0.0
    good = sum(1 for r in rows if sum(1 for k in CAL_FIELDS if filled(r, k)) >= 7)
    all_rows = con.execute("SELECT * FROM entry").fetchall()
    all_good = sum(1 for r in all_rows if sum(1 for k in CAL_FIELDS if filled(r, k)) >= 7)
    # 按公司看：每家只要有一条完整条目，用户就能查到这家的届次/方向/城市
    by_group: dict[str, bool] = {}
    for r in all_rows:
        ok = sum(1 for k in CAL_FIELDS if filled(r, k)) >= 7
        by_group[r["group_name"]] = by_group.get(r["group_name"], False) or ok
    groups_ok = sum(1 for v in by_group.values() if v)
    by_company = groups_ok / len(by_group) if by_group else 0.0
    detail = (f"{good}/{len(rows)}；全部条目 {all_good}/{len(all_rows)} = {all_good / len(all_rows):.1%}；"
              f"按公司 {groups_ok}/{len(by_group)} = {by_company:.1%}" if all_rows else f"{good}/{len(rows)}")
    return good / len(rows), detail, by_company


def calendar_ratios(calendar_db: Path | None) -> tuple[float | None, float | None]:
    """日历条目的两个「能不能用」指标：(有城市占比, 有网申时间占比)。

    分母排除两类条目，两类都写清理由，不是为了让数字好看：
      1. `project_type='社招'`：本产品是**校园招聘**日历。社招岗来自海投式社招板
         （一家公司几千条「Java 开发工程师」），既没有届次也没有批次窗口，
         把它们算进分母等于要求社招岗也有校招批次——那是口径错配，不是数据缺陷。
      2. 只有入口、没有任何字段的 `official_site` 条目：这类条目的价值是
         「投递入口 + 来源」，它出现在日历里的意义是让人点进去，本来就取不到
         日期和城市（官网首页正文中位数 108 字，全是标题）。用它们当分母，
         等于把「有入口」和「有窗口」两件事混成一个指标，指标就失去诊断意义了。
         判据是 notes 里的来源标记（生成器写死的固定前缀），不是靠猜。
    「所有条目（含入口条目）」的口径另外单独输出，避免用口径掩盖问题。
    """
    if not calendar_db or not calendar_db.exists():
        return None, None
    con = sqlite3.connect(calendar_db)
    try:
        scope = ("FROM entry WHERE project_type != '社招' "
                 "AND COALESCE(notes,'') NOT LIKE '官方招聘入口（%'")
        total = con.execute(f"SELECT COUNT(*) {scope}").fetchone()[0]
        if not total:
            return None, None

        def filled_count(sql: str) -> int:
            return con.execute(sql).fetchone()[0]

        city = filled_count(
            "SELECT COUNT(*) " + scope + " AND cities IS NOT NULL AND TRIM(CAST(cities AS TEXT)) "
            "NOT IN ('', '[]', 'null')")
        win = filled_count(
            "SELECT COUNT(*) " + scope + " AND ((apply_start IS NOT NULL AND TRIM(CAST(apply_start AS TEXT)) != '') "
            "OR (apply_end IS NOT NULL AND TRIM(CAST(apply_end AS TEXT)) != ''))")
        return city / total, win / total
    finally:
        con.close()


def calendar_ratios_all(calendar_db: Path | None) -> tuple[float | None, float | None]:
    """同上的两个比例，但分母是**全部条目**（含社招、含只有入口的条目）。

    两个口径都要报：只看宽口径会把「有入口的条目」当成「该有 window 却没写」，
    只看窄口径又有自我美化的嫌疑。并排给出，读者自己判断。
    """
    if not calendar_db or not calendar_db.exists():
        return None, None
    con = sqlite3.connect(calendar_db)
    try:
        total = con.execute("SELECT COUNT(*) FROM entry").fetchone()[0]
        if not total:
            return None, None
        city = con.execute(
            "SELECT COUNT(*) FROM entry WHERE cities IS NOT NULL AND TRIM(CAST(cities AS TEXT)) "
            "NOT IN ('', '[]', 'null')").fetchone()[0]
        win = con.execute(
            "SELECT COUNT(*) FROM entry WHERE (apply_start IS NOT NULL AND TRIM(CAST(apply_start AS TEXT)) != '') "
            "OR (apply_end IS NOT NULL AND TRIM(CAST(apply_end AS TEXT)) != '')").fetchone()[0]
        return city / total, win / total
    finally:
        con.close()


def calendar_coverage(calendar_db: Path | None) -> tuple[int, int, int]:
    """返回 (有日历条目的目标数, 目标总数, blocked 数)。"""
    if not calendar_db or not calendar_db.exists():
        return 0, 0, 0
    con = sqlite3.connect(calendar_db)
    try:
        rows = con.execute("SELECT name, data_companies, COALESCE(blocked_reason,'') FROM target").fetchall()
        covered = 0
        blocked = 0
        for name, data_cos, reason in rows:
            if reason:
                blocked += 1
            if name and (json.loads(data_cos or "[]") or con.execute(
                    "SELECT 1 FROM entry WHERE group_name=? LIMIT 1", (name,)).fetchone()):
                covered += 1
        return covered, len(rows), blocked
    finally:
        con.close()


def campus_city_ratio(jobs_db: Path | None) -> float | None:
    if not jobs_db or not jobs_db.exists():
        return None
    con = sqlite3.connect(jobs_db)
    try:
        # 分母只算「校园招聘」：社招/实习岗本来就不在日历口径里，拉进来只会稀释比例。
        # 而且非北森源（大易）是能给出城市的，混算会让这个指标失去诊断意义。
        n = con.execute("SELECT COUNT(*) FROM job WHERE closed_at IS NULL AND recruit_type='campus'").fetchone()[0]
        if not n:
            return None
        hit = con.execute("""SELECT COUNT(*) FROM job WHERE closed_at IS NULL AND recruit_type='campus'
                             AND COALESCE(cities,'') NOT IN ('', '[]', 'null')""").fetchone()[0]
        return hit / n
    finally:
        con.close()


def jd_ratio(home: Path | None) -> float | None:
    if not home:
        return None
    jobs, text = home / "jobs.db", home / "jd_text.db"
    if not jobs.exists() or not text.exists():
        return None
    j, t = sqlite3.connect(jobs), sqlite3.connect(text)
    try:
        import json as _json

        open_ids = [r[0] for r in j.execute("SELECT id FROM job WHERE closed_at IS NULL")]
        n = len(open_ids)
        if not n:
            return None
        # 只数「在招岗位」的正文：jd_text 里还留着已下架岗位的行，
        # 之前用总数会被 min(have, n) 截到 1.0，把真实覆盖率报高（2026-10-24 修）
        have = t.execute(
            """SELECT COUNT(*) FROM job_text
               WHERE job_id IN (SELECT value FROM json_each(?))
                 AND (COALESCE(description,'') != '' OR COALESCE(requirements,'') != '')""",
            (_json.dumps(open_ids),)).fetchone()[0]
        return have / n
    finally:
        j.close()
        t.close()


def data_sanity(home: Path | None, calendar_db: Path | None) -> tuple[int, str]:
    """数据层面的硬性自检，返回 (异常条数, 明细)。

    这些异常一旦出现就是真 bug（不是覆盖率问题），所以门槛是 0。
    """
    problems: list[str] = []
    if home and (home / "jobs.db").exists():
        j = sqlite3.connect(home / "jobs.db")
        try:
            checks = {
                "空标题": "SELECT COUNT(*) FROM job WHERE closed_at IS NULL AND TRIM(COALESCE(title,''))=''",
                "非法招聘类型": ("SELECT COUNT(*) FROM job WHERE closed_at IS NULL "
                                 "AND recruit_type NOT IN ('campus','intern','social')"),
                "届次越界": ("SELECT COUNT(*) FROM job WHERE closed_at IS NULL AND grad_year IS NOT NULL "
                             "AND (grad_year < 2023 OR grad_year > 2032)"),
                "链接非 http": "SELECT COUNT(*) FROM job WHERE closed_at IS NULL AND url NOT LIKE 'http%'",
            }
            for label, sql in checks.items():
                n = j.execute(sql).fetchone()[0]
                if n:
                    problems.append(f"{label} {n}")
            dups = j.execute(
                "SELECT COUNT(*) FROM (SELECT source_id, source_job_id FROM job WHERE closed_at IS NULL "
                "GROUP BY 1,2 HAVING COUNT(*) > 1)").fetchone()[0]
            if dups:
                problems.append(f"同源重复 {dups}")
        finally:
            j.close()
    if calendar_db and calendar_db.exists():
        c = sqlite3.connect(calendar_db)
        try:
            n = c.execute("SELECT COUNT(*) FROM entry WHERE apply_start IS NOT NULL AND apply_end IS NOT NULL "
                          "AND apply_end < apply_start").fetchone()[0]
            if n:
                problems.append(f"网申窗口倒挂 {n}")
            n = c.execute("SELECT COUNT(*) FROM entry WHERE grad_year IS NOT NULL "
                          "AND (grad_year < 2023 OR grad_year > 2032)").fetchone()[0]
            if n:
                problems.append(f"日历届次越界 {n}")
        finally:
            c.close()
    return len(problems), "；".join(problems) if problems else "无异常"


def deliverable_sanity() -> tuple[int, str]:
    """交付物自身的自洽检查（不依赖数据库，直接看 companies.jsonl / calendar 条目）。

    这些是「说得出但做不到」的矛盾，用户一眼就能看穿：
      - `jd_status=official_page` 却没有 `careers_url`：声称有官方 JD 页却不给链接；
      - `careers_url` 落在第三方聚合站（offernotes/牛客/职友集…）：违反「不用聚合站」红线；
      - 日历条目 `apply_start > apply_end` 的倒挂窗口（数据库侧已查，这里查仓库文件侧）。
    """
    problems: list[str] = []
    f = ROOT / "companies.jsonl"
    if f.exists():
        bad_jd = bad_host = 0
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                problems.append("companies.jsonl 有非法 JSON 行")
                break
            url = (r.get("careers_url") or "").strip()
            if r.get("jd_status") == "official_page" and not url:
                bad_jd += 1
            if url:
                host = url.split("/")[2] if "//" in url else ""
                if any(b in host for b in THIRD_PARTY_HOSTS):
                    bad_host += 1
        if bad_jd:
            problems.append(f"companies.jsonl 声称有官方 JD 却无入口 {bad_jd}")
        if bad_host:
            problems.append(f"companies.jsonl 入口指向第三方聚合站 {bad_host}")
    return len(problems), "；".join(problems) if problems else "无异常"


# 第三方招聘聚合站：不是雇主自己的招聘入口，不能当投递链接
THIRD_PARTY_HOSTS = ("offernotes", "nowcoder", "jobui", "kanzhun", "yingjiesheng", "shixiseng",
                     "maimai.cn", "zhipin.com", "lagou.com", "liepin.com", "51job.com", "zhaopin.com")


def run(home: Path | None, sources: Path, targets_path: Path, calendar_db: Path | None) -> list[dict]:
    t = _targets(targets_path)
    companies = {s.company for s in load_sources(sources) if s.enabled}
    rows = []

    covered, total = data_coverage(t, companies)
    need_data = max(int(GATES["data_coverage_ratio"] * total), GATES["data_coverage_min"])
    rows.append({"gate": "数据源覆盖", "value": f"{covered}/{total}",
                 "ok": covered >= need_data,
                 "target": f"≥{need_data}"
                           f"（{GATES['data_coverage_ratio']:.0%} 且 ≥{GATES['data_coverage_min']}）"})

    cal_covered, cal_total, blocked = calendar_coverage(calendar_db)
    need_cal = max(int(GATES["calendar_coverage_ratio"] * cal_total),
                   GATES["calendar_coverage_min"]) if cal_total else 1
    rows.append({"gate": "目标覆盖(日历或数据)", "value": f"{cal_covered}/{cal_total}（blocked {blocked}）"
                 if cal_total else "无日历库",
                 "ok": cal_total > 0 and cal_covered >= need_cal,
                 "skip": cal_total == 0,
                 "target": f"≥{need_cal}"
                           f"（{GATES['calendar_coverage_ratio']:.0%} 且 ≥{GATES['calendar_coverage_min']}）"})

    city = campus_city_ratio(home / "jobs.db" if home else None)
    rows.append({"gate": "校园岗城市覆盖", "value": "无数据" if city is None else f"{city:.1%}",
                 "ok": city is not None and city >= GATES["campus_city"],
                 "skip": city is None, "target": f"≥{GATES['campus_city']:.0%}"})

    jd = jd_ratio(home)
    rows.append({"gate": "JD 正文覆盖", "value": "无数据" if jd is None else f"{jd:.1%}",
                 "ok": jd is not None and jd >= GATES["jd_coverage"],
                 "skip": jd is None, "target": f"≥{GATES['jd_coverage']:.0%}"})

    fields, detail, by_company = calendar_fields(calendar_db)
    rows.append({"gate": "日历字段完整度", "value": f"{fields:.1%}（≥7/11 字段：{detail}）",
                 "ok": fields >= GATES["calendar_fields"], "skip": calendar_db is None or not calendar_db.exists(),
                 "target": f"≥{GATES['calendar_fields']:.0%}"})
    rows.append({"gate": "日历按公司完整", "value": f"{by_company:.1%}（每家公司至少一条 ≥7/11）",
                 "ok": by_company >= GATES["calendar_fields_by_company"],
                 "skip": calendar_db is None or not calendar_db.exists(),
                 "target": f"≥{GATES['calendar_fields_by_company']:.0%}"})

    cal_city, cal_win = calendar_ratios(calendar_db)
    all_city, all_win = calendar_ratios_all(calendar_db)
    rows.append({"gate": "日历有城市", "value": (
        "无数据" if cal_city is None else
        f"{cal_city:.1%}（全部条目口径 {all_city:.1%}）"),
        "ok": cal_city is not None and cal_city >= GATES["calendar_city"],
        "skip": cal_city is None, "target": f"≥{GATES['calendar_city']:.0%}"})
    rows.append({"gate": "日历有网申时间", "value": (
        "无数据" if cal_win is None else
        f"{cal_win:.1%}（全部条目口径 {all_win:.1%}）"),
        "ok": cal_win is not None and cal_win >= GATES["calendar_window"],
        "skip": cal_win is None, "target": f"≥{GATES['calendar_window']:.0%}"})

    bad, detail = data_sanity(home, calendar_db)
    rows.append({"gate": "数据自检", "value": f"异常 {bad}（{detail}）",
                 "ok": bad <= GATES["data_sanity"], "target": "0 异常"})

    bad, detail = deliverable_sanity()
    rows.append({"gate": "交付物自洽", "value": f"异常 {bad}（{detail}）",
                 "ok": bad <= GATES["data_sanity"], "target": "0 异常"})

    missing = [f for f in FILES if not (ROOT / f).exists()]
    rows.append({"gate": "发布文档齐全", "value": "缺少 " + ",".join(missing) if missing else "齐全",
                 "ok": not missing, "target": "README/CHANGELOG/COMPLIANCE/LICENSE"})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", default=None, help="数据目录（含 jobs.db/jd_text.db/calendar.db）")
    ap.add_argument("--sources", default=str(ROOT / "sources"))
    ap.add_argument("--targets", default=str(ROOT / "targets" / "top_companies.yaml"))
    ap.add_argument("--calendar-db", default=None)
    args = ap.parse_args()
    home = Path(args.home).expanduser() if args.home else None
    cal = Path(args.calendar_db) if args.calendar_db else (home / "calendar.db" if home else None)
    rows = run(home, Path(args.sources), Path(args.targets), cal)
    width = max(len(r["gate"]) for r in rows)
    failed, skipped = 0, 0
    for r in rows:
        # 数据缺失（没跑过 update、没有 jobs.db）不算「未达标」，但也不能算通过——
        # 标成 SKIP 并在结论里单独计数，避免「没数据」被误读成「检查通过」。
        if r.get("skip"):
            mark, skipped = "SKIP", skipped + 1
        else:
            mark = "PASS" if r["ok"] else "FAIL"
            failed += 0 if r["ok"] else 1
        print(f"{mark}  {r['gate']:<{width}}  {r['value']:<28} 门槛 {r['target']}")
    if not failed and not skipped:
        print("\n发布自检： 全部达标")
    else:
        bits = []
        if failed:
            bits.append(f"{failed} 项未达标")
        if skipped:
            bits.append(f"{skipped} 项因缺数据未验证（先跑 jobradar update / calendar-build）")
        print("\n发布自检： " + "，".join(bits))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
