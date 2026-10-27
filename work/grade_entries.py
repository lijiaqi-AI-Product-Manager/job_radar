"""入口定级：把「公司官网首页」与「真正的招聘入口」分开，并且优先选职位列表页。

2026-10-26 实测的教训——池子里混进了大量不是招聘入口的页面：
    IBM        → www.ibm.com/us-en            （公司首页）
    DSV中国     → www.dsv.com/en               （公司首页）
    360集团     → hao.360.com                  （导航站）
    ABB中国     → c.gongkong.com/MarketMain    （行业资讯站）
    SAP中国     → www.sap.cn/index.html        （公司首页）
这些页面挂上去，用户点开看不到任何岗位，属于不可用的日历条目。

定级规则（A > B > C > D）：
    A 级：职位列表页（URL 或页面结构表明是岗位列表：/position、/jobs、/campus/jobs、ATS 门户首页）
    B 级：招聘频道首页（careers./join./campus./zhaopin./hr. 子域，或标题含「招聘/校招/加入我们」）
    C 级：公司官网上的招聘板块（URL 含 careers/jobs/join/recruit 但只是介绍页）
    D 级：公司官网首页 / 导航站 / 资讯站 → **不收录**

收录标准：A 或 B，且页面标题/正文确实是招聘相关；C 级只在没有更好选择时保留并降级标注。

用法：
    python3 work/grade_entries.py
输出：work/entry_graded.jsonl
"""

import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent

ATS = ("zhiye.com", "hotjob.cn", "mokahr.com", "myworkdayjobs.com", "myworkday.cn", "feishu.cn",
       "f.mioffice.cn", "italent.cn", "dayee.com", "hcmcloud.cn", "career.site", "ultraai.site")

LIST_PATH = re.compile(
    r"(/position|/positions|/job[s]?(/|$|list|info|search)|/campus/jobs|/zhiye|/zhiwei|/recruit(/|$)|"
    r"/campus|/school|/social|/apply|/search|/openings|/vacanc|/joinus|/join-us|/joblist)", re.I)
CAREER_TITLE = re.compile(r"招聘|校招|校园|实习|careers?|jobs?|join\s*us|加入我们|职位|岗位|openings", re.I)
HOME_PATH = re.compile(r"^/?$|^/index\.(html?|php|aspx?)$|^/cn/?$|^/zh/?$|^/zh-cn/?$", re.I)


def host(u: str) -> str:
    return (urlsplit(u).hostname or "").lower()


def grade(r: dict) -> tuple[str, str]:
    u, t = r["url"], r.get("title") or ""
    h = host(u)
    path = urlsplit(u).path or "/"
    is_ats = any(h == a or h.endswith("." + a) for a in ATS)
    if is_ats:
        # ATS 门户：租户首页即职位列表
        return "A", "ats_portal"
    if LIST_PATH.search(path):
        return "A", "list_path"
    # 招聘子域
    if re.match(r"^(careers?|jobs?|join|campus|zhaopin|talent|hr|recruit|zhiye|rc|zp|wecruit)\.", h):
        return "B", "career_subdomain"
    if CAREER_TITLE.search(t) and re.search(r"招聘|career|job|join|campus|zhaopin", u, re.I):
        return "B", "title_and_url"
    if HOME_PATH.search(path):
        return "D", "company_homepage"
    if CAREER_TITLE.search(t):
        return "C", "career_page"
    return "D", "not_career"


def main() -> None:
    rows = [json.loads(s) for s in
            (ROOT / "work/entry_pool.jsonl").read_text(encoding="utf-8").splitlines() if s.strip()]
    out = []
    for r in rows:
        g, why = grade(r)
        out.append({**r, "grade": g, "grade_why": why})
    out.sort(key=lambda r: (r["grade"], r["company"]))
    (ROOT / "work/entry_graded.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in out), encoding="utf-8")
    print("total", len(out), Counter(r["grade"] for r in out))
    print("reasons", Counter(f"{r['grade']}:{r['grade_why']}" for r in out).most_common())
    keep = [r for r in out if r["grade"] in ("A", "B")]
    print("keep A+B:", len(keep))
    print("--- D 级示例 ---")
    for r in [x for x in out if x["grade"] == "D"][:15]:
        print("  ", r["company"], "|", r["url"][:66], "|", r["grade_why"])


if __name__ == "__main__":
    main()
