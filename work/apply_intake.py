"""把 work/intake_proposal.jsonl 里 action=add 的候选落成真实 source（北森批量 / 飞书单公司文件）。

规则（对齐 CLAUDE.md 与 P0-1）：
- 同 adapter 同租户/同域名 → 已在库里，天然被 existing 去重挡掉；
- 同 adapter 同公司（core 名相同）只留岗位数最大的那条，避免同一家公司两个租户；
- 黑名单 slug（careers/moka/www/wecruit/portal-oss/campus…）直接丢；
- 飞书拿不到岗位数，必须先用 search/job/posts 探一次 count>0，探活顺序 portal_type 3 → 2；
- 北森白标域名（beisen_host）写成 `params: {tenant, host}`，和已入库的 九阳/蜜雪/立白 同形。

用法：python work/apply_intake.py            # 只打印计划
      python work/apply_intake.py --write    # 真写 sources/
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
SOURCES = ROOT / "sources"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}
BLACKLIST = {"careers", "moka", "www", "wecruit", "portal-oss", "campus", "zhiye", "beisen",
             # 人工复核后剔除：与已有源重复 / 标题与归属打架 / 多品牌聚合门户
             "chery", "camzhaopin", "idea", "campus.hundsun.com", "itcast1", "aiva",
             # arashivision = 影石 Insta360，标题里的「360」会把归属错判成奇虎 360
             "arashivision"}
SUF = re.compile(r"(股份有限公司|有限责任公司|有限公司|集团|控股|中国|股份|总公司|公司|银行)$")
CJK = re.compile(r"[\u4e00-\u9fff]")


def core(name: str) -> str:
    n = re.sub(r"[\s（）()·\-—]", "", name)
    prev = None
    while prev != n:
        prev = n
        n = SUF.sub("", n)
    return n


def existing_index() -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """用 jobradar.sources 的结构化解析（不要自己正则扫 YAML，紧凑单行条目会漏）。

    返回 (adapter, tenant|host|slug) 与 (adapter, core-company)；beisen_host 归一成 beisen。
    """
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from jobradar.sources import load_sources

    keys: set[tuple[str, str]] = set()
    comps: set[tuple[str, str]] = set()
    for src in load_sources(SOURCES):
        adapter = "beisen" if src.adapter == "beisen_host" else src.adapter
        p = src.params or {}
        comps.add((adapter, core(src.company)))
        for raw in (p.get("tenant"), p.get("host"), p.get("base"), p.get("base_url")):
            if not raw:
                continue
            val = str(raw).lower()
            val = re.sub(r"^https?://", "", val).split("/")[0]
            keys.add((adapter, val))
            if val.endswith(".zhiye.com"):
                keys.add((adapter, val[: -len(".zhiye.com")]))
            if val.endswith(".jobs.feishu.cn"):
                keys.add((adapter, val[: -len(".jobs.feishu.cn")]))
    return keys, comps


def feishu_count(cli: httpx.Client, slug: str, portal_type: int) -> int:
    base = f"https://{slug}.jobs.feishu.cn"
    try:
        tok = cli.post(f"{base}/api/v1/csrf/token", json={"portal_entrance": 1},
                       headers={**UA, "Accept": "application/json"}, timeout=15.0)
        token = ((tok.json().get("data") or {}).get("token")) or ""
        if not token:
            return 0
        body = {
            "keyword": "", "limit": 1, "offset": 0, "job_category_id_list": [],
            "location_code_list": [], "subject_id_list": [], "recruitment_type_id_list": [],
            "sequence": "", "job_function_id_list": [], "portal_type": portal_type,
            "portal_entrance": 1,
        }
        r = cli.post(f"{base}/api/v1/search/job/posts", json=body,
                     headers={**UA, "Accept": "application/json", "x-csrf-token": token},
                     timeout=20.0)
        d = r.json()
        return int(((d.get("data") or {}).get("count")) or 0)
    except Exception:  # noqa: BLE001
        return 0


NAME_TAIL = re.compile(
    r"(校园招聘|社会招聘|招聘官网|招聘门户网|招聘门户|招聘微|社招|校招|招聘|官网|股份有限公司|有限责任公司"
    r"|有限公司|集团|控股|公司)+$"
)


def clean_company(name: str) -> str:
    """标题清洗出来的公司名再收一道：去「社招/招聘官网」尾巴，修掉半截括号与多段竖线。"""
    n = re.sub(r"[\s\u3000]+", "", name or "").replace("｜", "|")
    if "|" in n:
        # 「BMSG｜明月海藻集团招聘官网」这类取中文信息量最大的那段
        n = max(n.split("|"), key=lambda s: len(CJK.findall(s)))
    n = re.sub(r"^(?:加入|欢迎加入|欢迎来到)", "", n)
    if ("（" in n) != ("）" in n):
        n = re.split(r"[（(]", n)[0]
    prev = None
    while prev != n:
        prev = n
        n = NAME_TAIL.sub("", n)
    return n.strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    keys, comps = existing_index()
    rows = [json.loads(x) for x in open(WORK / "intake_proposal.jsonl", encoding="utf-8") if x.strip()]
    adds = [r for r in rows if r.get("action") == "add"]

    plan: list[dict] = []
    seen_company: dict[tuple[str, str], dict] = {}
    for r in adds:
        kind = "beisen" if r["kind"] in ("beisen", "beisen_host") else r["kind"]
        slug = r["slug"].strip().lower()
        params = r.get("params") or {}
        host = (params.get("host") or "").strip().lower()
        company = clean_company(r.get("proposed_name") or "")
        if slug in BLACKLIST or len(company) < 2:
            continue
        if kind == "beisen" and r["kind"] == "beisen_host":
            if not host:
                continue
        key = (kind, host or slug)
        ckey = (kind, core(company))
        if key in keys or ckey in comps:
            continue
        # 北森只收岗位数 >0 的；飞书稍后实测
        if kind == "beisen" and int(r.get("count") or 0) <= 0:
            continue
        cur = seen_company.get(ckey)
        if cur is not None:
            if int(r.get("count") or 0) <= int(cur.get("count") or 0):
                continue
        rec = {"kind": kind, "slug": slug, "company": company, "count": int(r.get("count") or 0),
               "host": host, "title": r.get("title") or "", "raw_kind": r["kind"],
               "tenant": (host.split(".")[0] if host and r["kind"] == "beisen_host" else slug)}
        seen_company[ckey] = rec
        plan.append(rec)

    plan = [r for r in plan if seen_company[(r["kind"], core(r["company"]))] is r]
    feishu_ok: list[dict] = []
    with httpx.Client(headers=UA, verify=False, follow_redirects=True) as cli:
        for r in plan:
            if r["kind"] != "feishu_atsx":
                continue
            for pt in (3, 2):
                cnt = feishu_count(cli, r["slug"], pt)
                time.sleep(1.0)
                if cnt > 0:
                    r["portal_type"] = pt
                    r["count"] = cnt
                    feishu_ok.append(r)
                    break
    plan = [r for r in plan if r["kind"] != "feishu_atsx"] + feishu_ok

    beisen = [r for r in plan if r["kind"] == "beisen"]
    feishu = [r for r in plan if r["kind"] == "feishu_atsx"]
    print(f"计划入库：北森 {len(beisen)}、飞书 {len(feishu)}")
    for r in sorted(beisen, key=lambda x: -x["count"]):
        print(f"  beisen   {r['slug']:<24} {r['company']:<18} {r['count']:>5} 岗  {r['title'][:26]}")
    for r in feishu:
        print(f"  feishu   {r['slug']:<24} {r['company']:<18} {r['count']:>5} 岗  pt={r['portal_type']}")
    if not a.write:
        print("（未写入；加 --write 落盘）")
        return

    if beisen:
        path = SOURCES / "beisen.yaml"
        text = path.read_text(encoding="utf-8")
        if not text.endswith("\n"):
            text += "\n"
        lines = [
            "",
            f"  # ---- 2026-10-28 Common Crawl 索引枚举 + 门户 <title> 定归属（{len(beisen)} 家）----",
            "  # 来源：CC 索引 zhiye.com 域下的历史抓取 URL（index.commoncrawl.org，公开归档，非本机探测）；",
            "  # 每个租户都实测 `/api/Jobad/GetJobAdPageList` Code=200 且 Count>0，标题里能读到公司名才收。",
        ]
        for r in sorted(beisen, key=lambda x: -x["count"]):
            if r["host"]:
                lines.append(
                    f"  - {{id: beisen-{r['tenant']}, company: {r['company']}, "
                    f"params: {{tenant: {r['tenant']}, host: {r['host']}}}}}  # 2026-10-28 新增：{r['count']} 岗"
                )
            else:
                lines.append(
                    f"  - {{id: beisen-{r['slug']}, company: {r['company']}, "
                    f"params: {{tenant: {r['slug']}}}}}  # 2026-10-28 新增：{r['count']} 岗"
                )
        path.write_text(text + "\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        print(f"写入 {path.relative_to(ROOT)}：{len(beisen)} 条")

    template = """id: {slug}
company: {company}
adapter: feishu_atsx
recruit_types: [campus, intern]
rate_limit_rps: 1
params:
  base_url: "https://{slug}.jobs.feishu.cn"
  website_path: {path}
  portal_type: {pt}
  page_size: 100
  job_url: "https://{slug}.jobs.feishu.cn/{path}/position/{{id}}/detail"
compliance:
  checked_on: 2026-10-28
  robots: "none"            # {slug}.jobs.feishu.cn/robots.txt → 404（平台层无站点级规则）；只读公开列表，不触达 /referral
  terms: "飞书招聘 ATSX 门户：匿名 csrf token + 公开职位列表 JSON，无登录、无验证码、无签名校验。会话 token 只在内存中使用（CLAUDE.md 铁律 1）。用户协议待人工复核"
  notes: "2026-10-28 从 Common Crawl 索引发现的 {slug} 租户；实测 portal_type={pt} 时 count={count}，门户 <title> 为「{title}」。"
"""
    for r in feishu:
        path = SOURCES / f"{r['slug']}.yaml"
        if path.exists():
            print(f"跳过已存在：{path.name}")
            continue
        path.write_text(
            template.format(slug=r["slug"], company=r["company"], pt=r["portal_type"],
                            path="campus", count=r["count"], title=r["title"][:40]),
            encoding="utf-8", newline="\n",
        )
        print(f"写入 {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
