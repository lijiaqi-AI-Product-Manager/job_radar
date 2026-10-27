"""招聘日历扩量第 3 步：把「已确认的官方招聘入口」写成 calendar/entries/<slug>.yaml。

用户 2026-10-26 定义的条目口径（十项）与本项目的字段对应关系：
    集团               -> group（文件名与 group 名一致，且必须在 targets/top_companies.yaml 里）
    具体公司/产品       -> company / product（入口页标题里明写才填）
    届次               -> grad_year（页面明写「2027届」才填，不猜）
    项目类型           -> project_type（taxonomy/calendar.yaml 受控词表，实习/校招分条目）
    方向               -> tracks（页面明写的招聘方向词；抽不到就不写）
    网申时间           -> apply_start / apply_end（页面明写日期才填）
    城市               -> cities（页面明写的城市才填）
    投递入口           -> apply_url
    来源               -> source{type, name, url, date}（只用公司官方招聘站 = official_site）
    数据时间戳         -> as_of

JD 规则：
- 数据层已有该公司在招岗位（sources/*.yaml 里能抓到）→ 交给 calendar build 自动判 linked；
- 入口页本身就是岗位列表（北森/大易/Moka/自建 careers）→ jd.status = official_page，挂该页；
- 入口页只是「招聘首页/需要点进去」→ jd.status = none，查询时附「{公司名}希望你去他们的招聘页逛一逛哦~」。

红线：不编造。页面没写的字段一律留空；项目类型拿不准时用 `校招`（词表里明确写了「来源未细分批次时用」），
而不是硬填「秋招正式批」。

用法：
    python3 work/build_calendar_entries.py --dry        # 只统计
    python3 work/build_calendar_entries.py --apply      # 写 calendar/entries/<slug>.yaml
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pypinyin import Style, lazy_pinyin

ROOT = Path(__file__).resolve().parent.parent

# 数据时间戳：所有条目都写这个日期，时效过滤也以它为准（而不是机器当天日期——
# 重跑历史数据时，「今天」会让同一条目在不同机器上得出不同结论）。
AS_OF = "2026-10-26"
ENTRIES = ROOT / "calendar" / "entries"
TAXONOMY = yaml.safe_load((ROOT / "taxonomy" / "calendar.yaml").read_text(encoding="utf-8"))

# 项目类型判定表：只用入口页标题/URL 里**明写**的词
TYPE_RULES = (
    (r"提前批", "提前批"),
    (r"暑期实习|暑期", "暑期实习"),
    (r"寒假实习|寒假", "寒假实习"),
    (r"日常实习", "日常实习"),
    (r"校园大使", "校园大使"),
    (r"秋招补录|补录", "秋招补录"),
    (r"春招", "春招"),
    (r"秋招|秋季校园招聘", "秋招"),
    (r"校园招聘|校招|campus", "校招"),
    (r"实习|intern", "实习"),
    (r"社会招聘|社招|experienced|social", "社招"),
)
# 入口站本身就是岗位列表的 ATS（点开就能挑岗位）
JD_LIST_HOSTS = ("zhiye.com", "hotjob.cn", "mokahr.com", "myworkdayjobs.com", "feishu.cn", "f.mioffice.cn",
                 "italent.cn", "dayee.com", "hcmcloud.cn")
CITY_LIST = ("北京", "上海", "广州", "深圳", "杭州", "成都", "南京", "武汉", "西安", "苏州", "天津", "重庆",
             "长沙", "合肥", "厦门", "青岛", "郑州", "济南", "无锡", "佛山", "东莞", "宁波", "福州", "大连",
             "沈阳", "哈尔滨", "长春", "石家庄", "太原", "南昌", "贵阳", "昆明", "南宁", "兰州", "乌鲁木齐",
             "中国香港", "中国澳门", "中国台湾", "新加坡", "东京", "首尔", "伦敦", "纽约")


def slug_of(name: str) -> str:
    s = "".join(lazy_pinyin(name, style=Style.NORMAL))
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return (s or "company")[:48]


def project_type_of(title: str, url: str, directions: list[str]) -> str:
    blob = f"{title} {url}"
    for pat, ptype in TYPE_RULES:
        if re.search(pat, blob, re.I):
            return ptype
    # 站点是「招聘官网」且没写批次 → 校招（词表：来源未细分批次时用）
    if re.search(r"招聘|careers?|jobs?", blob, re.I):
        return "校招"
    return "校招"


def jd_of(url: str, title: str, snippet: str) -> dict:
    host = (urlsplit(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) or h in host for h in JD_LIST_HOSTS):
        return {"status": "official_page", "url": url}
    if re.search(r"position|jobs?/|zhiwei|岗位", url, re.I):
        return {"status": "official_page", "url": url}
    return {"status": "none"}


def cities_of(snippet: str, title: str) -> list[str]:
    blob = f"{title} {snippet}"
    hits = [c for c in CITY_LIST if c in blob]
    return hits[:8]


# ---- 数据层证据：入口页没写日期，但该公司自己的招聘站接口写了 ----------
#
# 交付物里 `apply_start/apply_end` 原来 100% 为空：只用「入口页正文」抽日期，
# 而入口页正文本来就不写网申窗口。可同一批公司的招聘站接口（北森/大易）是明写
# `endDate` 的，已经抓在 work/ats_evidence.jsonl 里——数据在自己的仓库里躺着没用上。
# 这里把它接进来，规则和 pipeline 完全一致（宁缺毋滥）：
#   apply_end   = 该批在招职位里**多数**写的那天（不是 min，见 pipeline 注释里的案例）
#   apply_start = 仅当「同批 ≥3 条且占比 ≥40% 的职位同一天上架」，且那天不等于截止日
# 证据必须落在同一个 project_type 上；没有对应批次的证据一律不用。
_TYPE2RT = {"校招": "campus", "秋招正式批": "campus", "秋招补录": "campus", "春招": "campus",
            "提前批": "campus", "校园大使": "campus", "暑期实习": "intern", "寒假实习": "intern",
            "日常实习": "intern", "实习": "intern", "社招": "social", "秋招": "campus"}

# 第三方招聘聚合站：红线明确禁止（不接受、不引用、不当作投递入口）。
# 与 work/align_deliverables.py 的名单保持一致，另外补上「页面标题里自称聚合站」的判据——
# 有些站换域名很快，但标题里一定写着自己是"招聘信息聚合/转载"。
_THIRD_PARTY_HOSTS = (
    "offernotes.cn", "nowcoder.com", "yingjiesheng.com", "shixiseng.com", "offershow.cn",
    "kanzhun.com", "liepin.com", "51job.com", "zhaopin.com", "dajie.com", "lagou.com",
    "zhipin.com", "maimai.cn", "niuqizp.com", "shixi.com", "qiuzhi.com",
)
_THIRD_PARTY_TITLE_WORDS = ("牛企直聘", "转载自", "信息聚合", "聚合招聘", "招聘信息网",
                            "职位搜索_", "找工作网", "招聘网_")


def is_third_party(url: str, title: str = "") -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in _THIRD_PARTY_HOSTS):
        return True
    t = title or ""
    return any(w in t for w in _THIRD_PARTY_TITLE_WORDS)


def _norm(name: str) -> str:
    s = re.sub(r"[（(][^）)]*[）)]", "", name or "")
    s = re.sub(r"\s+", "", s)
    for suf in ("股份有限公司", "有限责任公司", "有限公司", "集团有限公司", "集团", "公司"):
        if s.endswith(suf) and len(s) > len(suf) + 1:
            return s[: -len(suf)]
    return s


def load_evidence() -> dict[str, dict]:
    """读 `jobradar` 导出的结构化证据，用法与 `work/build_calendar.py` 完全一致。

    这只是「给日历条目取字段」，不新增抓取，也不猜值——证据文件本身是 crawl 的产物。
    """
    p = ROOT / "work" / "ats_evidence.jsonl"
    if not p.exists():
        return {}
    raw = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        raw.setdefault(rec["company"], rec)
    # 与 build_calendar.build_evidence_index 同款：原名 + 归一后名字两级索引，
    # 不做子串匹配（「中国银行」不能抢走「中国银行保险」的证据）。
    idx = dict(raw)
    for name, rec in raw.items():
        k = _norm(name)
        if k and k not in idx:
            idx[k] = rec
    return idx


def window_from_evidence(ev: dict, ptype: str) -> tuple[str | None, str | None, str | None]:
    """返回 (start, end, 证据说明)。拿不到就 (None, None, None)。"""
    rtype = _TYPE2RT.get(ptype)
    if not ev or not rtype:
        return None, None, None
    ends = (ev.get("ends_by_type") or {}).get(rtype) or []
    end = ends[0] if ends else None
    starts = (ev.get("starts_by_type") or {}).get(rtype) or []
    start = starts[-1] if starts else None
    if start and end and start >= end:
        start = None  # 起点不晚于终点，否则宁可不写
    if not (start or end):
        return None, None, None
    return start, end, f"{rtype} 批次接口字段（多数字段口径，非推测）"


def _dates_in_text(text: str) -> tuple[str | None, str | None]:
    """从入口页正文里抽「网申时间：A ~ B」这种**明写**的窗口。

    只认两种写法：明确的区间（`2026-08-03 ~ 2026-12-31`、`2026/8/3至2026/12/31`）
    和单个截止（`截止 2026-12-31` / `网申截止时间：…`）。抽不到就返回空——
    页面没写不等于「大概在那个时候」，不许拿年份补。
    """
    if not text:
        return None, None
    d = r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})"
    m = re.search(d + r"[^0-9]{0,6}(?:~|～|-|—|–|至|到)\s*" + d, text)
    if m:
        a = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        b = f"{int(m.group(4)):04d}-{int(m.group(5)):02d}-{int(m.group(6)):02d}"
        return (a, b) if a < b else (None, None)
    m = re.search(r"(?:截止|截至|deadline)[^0-9]{0,10}" + d, text, re.I)
    if m:
        return None, f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--src", default="work/careers_final.jsonl")
    args = ap.parse_args()

    rows = [json.loads(s) for s in (ROOT / args.src).read_text(encoding="utf-8").splitlines() if s.strip()]
    ok = [r for r in rows if r.get("best")]
    # 已有日历文件的 group，避免覆盖人工维护的条目
    existing_groups = {}
    for p in ENTRIES.glob("*.yaml"):
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if d.get("group"):
            existing_groups[d["group"]] = p
    used_ids = set()
    for p in ENTRIES.glob("*.yaml"):
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for e in d.get("entries") or []:
            used_ids.add(e.get("id"))

    stats = Counter()
    out = []
    evidence = load_evidence()
    for r in ok:
        group = r["company"]
        if group in existing_groups:
            stats["skip_existing"] += 1
            continue
        best = r["best"]
        url = best["url"]
        title = best.get("title") or ""
        # 红线：第三方聚合站不能当投递入口（不接受、不引用）。
        # 实测这批数据里混进了 campus.niuqizp.com（牛企直聘）——它是把各家校招公告
        # 二次搬运的站点，既不是公司官方入口，也没有转载授权。这类直接拒绝，
        # 连"日期好用"都不算理由：日期也是从搬运页抄来的。
        if is_third_party(url, title):
            stats["reject_third_party"] += 1
            continue
        ptype = project_type_of(title, url, best.get("directions") or [])
        # 入口页正文里明写的日期优先（那是「页面自己说的」），没有再取数据层接口字段
        ev = evidence.get(group) or evidence.get(_norm(group)) or {}
        w_start, w_end, w_why = window_from_evidence(ev, ptype)
        page_start, page_end = _dates_in_text(best.get("snippet") or "")
        w_start = page_start or w_start
        w_end = page_end or w_end
        slug = slug_of(group)
        eid = f"{slug}-{ 'social' if ptype == '社招' else 'campus' }-entry"
        while eid in used_ids:
            eid += "-2"
        used_ids.add(eid)
        # 时效过滤：截止日早于数据时间戳的批次已经结束了。
        # 日历里留一条「2025-11-15 截止」的秋招，用户点进去只会看到「已截止」——
        # 这比没有这条更糟（白高兴一场）。实测 mi/鸿星尔克、中国国航就是这样漏进来的：
        # 它们是从「入口页正文」抽到的旧公告日期，入口本身仍然可用，但那个批次早关了。
        # 所以：入口条目保留，**日期清空**（入口本身是真的），不能连日期一起发出去。
        if w_end and w_end < AS_OF:
            w_start = w_end = None
            w_why = None
        entry = {
            "id": eid,
            "company": None,
            "grad_year": None,
            "project_type": ptype,
            "tracks": [],
            "apply_start": w_start,
            "apply_end": w_end,
            "cities": cities_of(best.get("snippet") or "", title),
            "apply_url": url,
            "source": {"type": "official_site", "name": f"{group}招聘官网", "url": url, "date": None},
            "as_of": AS_OF,
            "jd": jd_of(url, title, best.get("snippet") or ""),
            "notes": f"官方招聘入口（2026-10-26 实测可访问；页面标题：{title or '无'}）。"
                     + (f"网申时间取自{w_why}。" if w_why else "入口页与数据层都未写明网申时间，留空，以官网为准。")
                     + "未写明的届次一律留空。",
        }
        if best.get("directions"):
            entry["tracks"] = [{"direction": d, "roles": []} for d in best["directions"][:4]]
        out.append({"group": group, "slug": slug, "entry": entry, "sector": r.get("sector"),
                    "url": url, "title": title})
        stats["new"] += 1

    print(json.dumps({"confirmed": len(ok), **stats}, ensure_ascii=False))
    print("project_type:", dict(Counter(o["entry"]["project_type"] for o in out)))
    if not args.apply:
        return 0

    for o in out:
        path = ENTRIES / f"{o['slug']}.yaml"
        i = 2
        while path.exists() and yaml.safe_load(path.read_text(encoding="utf-8")).get("group") != o["group"]:
            path = ENTRIES / f"{o['slug']}-{i}.yaml"
            i += 1
        doc = {"group": o["group"], "entries": [o["entry"]]}
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"written={len(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
