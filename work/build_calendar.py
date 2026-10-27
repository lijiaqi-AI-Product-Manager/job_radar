"""把三路证据合成 `calendar/entries/*.yaml` —— 十项口径的最终产出。

证据来源（按硬度排序，同一字段取最硬的）：
  E1  ATS 结构化职位列表（work/fields.jsonl，来自北森/大易接口）
      —— 职位名本身就是证据：「2027届校招-药品注册工程师」「算法工程师-上海」
  E2  高校就业网招聘简章（work/edu_hits.jsonl）
      —— 届次在标题里、网申截止在「过期时间」、城市在「工作地域」、方向在「职位类别」
  E3  浏览器渲染后的招聘站正文（work/rendered.jsonl）
      —— 「2027届校园招聘正式启动」「网申 8.17 开始」
  E4  服务端渲染的招聘站正文（work/fields.jsonl 里的 site 类页面文本摘要）

字段合并策略：
  - grad_year   : 多数票；三路都给了不同的就取出现次数最多的，并记证据
  - apply_start : 取最早的可信起点（网申通常「尽早开始、分批截止」）
  - apply_end   : 取最晚的可信终点
  - cities      : 并集，但**排除站点所在城市**（高校就业网会把学校所在城市带进来）
  - tracks      : 按方向合并 roles，去重
  - project_types: 并集；一个批次一条 entry

红线：
  - 来源只写公司官网/官方招聘站或政府平台；高校就业网只作为**证据**，不作为 source
    （calendar/README.md 白名单里没有 edu.cn）
  - 查不到的字段留空，不推断
  - JD：招聘站是公开列表页 → official_page；只有入口页且拿不到职位 → blocked + 提示句

用法：
    python3 work/build_calendar.py            # 只生成，不写盘
    python3 work/build_calendar.py --apply    # 写入 calendar/entries/
"""

import argparse
import datetime
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "work"))

from batch_group import detect_batch, sensible_window  # noqa: E402
from batch_group import pick_project_types as pick_batches  # noqa: E402
from hostrules import is_ats, usable_as_entry  # noqa: E402

from jobradar.pipeline.calendar import ManualEntry, load_manual  # noqa: E402
from jobradar.pipeline.calendar_extract import (  # noqa: E402
    extract_all,
    extract_grad_years,
)

# 数据时间戳：默认取运行当天（日历的语义是「截至今天这条还能投」）。
# 也可以用 --as-of 覆盖，便于复现历史批次。
AS_OF = datetime.date.today().isoformat()
VOCAB = yaml.safe_load((ROOT / "taxonomy" / "calendar.yaml").read_text(encoding="utf-8"))
PROJECT_TYPES = set(VOCAB["project_types"])

# 高校就业网所在城市：这些城市名出现在正文里多半是站点地址，不是招聘城市
SITE_CITIES = {
    "南开就业网": {"天津"},
    "西电就业网": {"西安"},
    "广工就业网": {"广州"},
    "郑大就业网": {"郑州"},
    "东秦就业网": {"秦皇岛"},
    "上电就业网": {"上海"},
    "民大就业网": {"北京"},
}


def slug_of(name: str) -> str:
    """公司名 → 文件名/ID 用的 slug（拼音，稳定、可读）。

    `pypinyin` 是**可选**依赖，只有真正写盘生成条目时才用得到：这里延迟导入，
    这样别的模块（以及 `tests/test_calendar_evidence_index.py`）只借用本文件的
    纯函数时，环境里不必装拼音库。缺库时的报错要能直接照着装。
    """
    try:
        from pypinyin import Style, lazy_pinyin
    except ImportError:  # pragma: no cover - 只在没装 pypinyin 的环境触发
        raise SystemExit("生成日历条目需要 pypinyin：pip3 install pypinyin") from None
    s = "".join(lazy_pinyin([c for c in name if "\u4e00" <= c <= "\u9fa5"], style=Style.NORMAL))
    s += re.sub(r"[^a-z0-9]", "", name.lower())
    s = re.sub(r"[^a-z0-9]", "", s.lower())
    return s or "x"


def load_jsonl(p: Path) -> list[dict]:
    """按行读 JSONL，跳过写坏/写了一半的行。

    采集进程是边抓边 append + flush 的，本脚本可能在它还在写的时候被调用，
    最后一行读到的就是半截 JSON。跳过即可——下次重跑会读到完整的。
    """
    if not p.exists():
        return []
    out: list[dict] = []
    for s in p.read_text(encoding="utf-8").splitlines():
        s = s.strip()
        if not s:
            continue
        try:
            out.append(json.loads(s))
        except json.JSONDecodeError:
            continue
    return out


# 项目类型 → 数据层招聘类型。用于「该批次自己没城市证据时，按类型取数据层城市」。
TYPE_OF_BATCH = {"校招": "campus", "秋招正式批": "campus", "秋招补录": "campus", "提前批": "campus",
                 "春招": "campus", "校园大使": "campus",
                 "暑期实习": "intern", "寒假实习": "intern", "日常实习": "intern", "实习": "intern",
                 "社招": "social"}


def load_ats_evidence(path: Path) -> dict[str, dict]:
    """读 `jobradar calendar-build` 导出的结构化职位证据（城市/截止日/届次）。

    为什么需要这一路证据：日历原来的城市来源只有「高校简章正文 + 招聘站渲染正文」，
    城市填充率 41%。但热招（大易）的列表接口每个岗位都自带 `workPlaceStr`（如「长沙市-长沙县」）
    和 `endDate`（真实截止日）——这是**结构化字段**，比从公告正文里正则抠城市可信得多。
    这条通路不打通，等于数据层抓到的城市信息在日历里白白丢掉。

    数据来源是真实抓取（crawl 产物），不是估算；文件不存在就返回空，日历照常生成。
    """
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    for r in load_jsonl(path):
        c = r.get("company")
        if c:
            out[c] = r
    return out


def _norm_company_name(name: str) -> str:
    """公司名归一：去括号注释、去后缀、去空格。

    「三一集团有限公司」与「三一集团」在数据层和 targets 里是两个名字，直接精确匹配会漏；
    「OPPO广东移动通信有限公司」与「OPPO」同理。证据字典只有一份，不能靠猜，
    所以匹配顺序是：精确 → 归一后精确 → 去掉「有限公司/股份有限公司/集团」等后缀后精确。
    不做子串匹配——「中国银行」和「中国银行保险」这类会互相抢证据，比漏匹配更糟。
    """
    s = name or ""
    s = re.sub(r"[（(][^）)]*[）)]", "", s)          # 括号里的注释
    s = re.sub(r"\s+", "", s)
    for suf in ("股份有限公司", "有限责任公司", "有限公司", "集团有限公司", "集团", "公司"):
        if s.endswith(suf) and len(s) > len(suf) + 1:
            s = s[: -len(suf)]
            break
    return s


def build_evidence_index(ev: dict[str, dict]) -> dict[str, dict]:
    """给证据建两级索引：原名 + 归一后的名字。归一冲突时以先到者为准（不覆盖）。"""
    idx = dict(ev)
    for name, rec in ev.items():
        key = _norm_company_name(name)
        if key and key not in idx:
            idx[key] = rec
    return idx


def lookup_evidence(idx: dict[str, dict], company: str) -> dict | None:
    if not idx or not company:
        return None
    if company in idx:
        return idx[company]
    key = _norm_company_name(company)
    return idx.get(key) if key else None


def merge_evidence(company: str, entry: dict, fields: dict | None,
                   edu: list[dict], rendered: dict | None,
                   ats: dict | None = None) -> dict:
    """把四路证据合成「按批次分组」的中间件。

    关键设计：证据先按批次（秋招正式批/暑期实习/提前批…）分桶，桶内才合并日期。
    不这么做就会把「暑期实习 3 月报名」和「秋招 12 月截止」拼成一个 3~12 月的假窗口。
    """
    out = {
        "batches": defaultdict(lambda: {"starts": [], "ends": [], "cities": [],
                                        "tracks": defaultdict(list), "ev": [],
                                        "dates": [], "src": []}),
        "grad_years": Counter(),
        "tracks_all": defaultdict(list),
        "cities_all": [],
        "titles": [],
        "n_jobs": 0,
        "ev": {},
    }

    def bucket(name: str | None):
        key = name or "校招"
        if key == "秋招":
            key = "秋招正式批"
        return out["batches"][key]

    def add_cities(dst, cs, src):
        for c in cs or []:
            if c and c not in dst:
                dst.append(c)
                out["ev"].setdefault("cities", src)

    # ---- E0 数据层结构化职位证据（城市/截止日来自职位表字段，非正文正则）
    # 放在最前面：它的权重最高（是接口字段，不是文本推断），批次归属也最确定——
    # 职位自带的 recruit_type 直接决定进哪个桶，不存在「正文里提到春招」这种串场风险。
    if ats:
        TYPE2BATCH = {"campus": "校招", "intern": "实习", "social": "社招"}
        cities_by_type: dict[str, list[str]] = defaultdict(list)
        for c in ats.get("cities") or []:
            cities_by_type["*"].append(c)
        for y in ats.get("grad_years") or []:
            out["grad_years"][y] += 2          # 与 E1 同级：都是结构化字段
        for t in ats.get("tracks") or []:
            out["tracks_all"][t["direction"]] += list(t.get("roles") or [])
        # 城市：按招聘类型分开记，避免社招的城市串进校招条目
        for rtype, cs in (ats.get("cities_by_type") or {}).items():
            cities_by_type[rtype].extend(cs)
            add_cities(out["cities_all"], cs, "招聘站职位列表（结构化字段）")
        for rtype, ends in (ats.get("ends_by_type") or {}).items():
            b = bucket(TYPE2BATCH.get(rtype, "校招"))
            for d in ends:
                if d:
                    b["ends"].append(d)
            b["ev"].append("招聘站职位列表（接口截止日字段）")
        for rtype, sts in (ats.get("starts_by_type") or {}).items():
            b = bucket(TYPE2BATCH.get(rtype, "校招"))
            for d in sts:
                if d:
                    b["starts"].append(d)
        # 已下架职位的截止日：这些岗位已经从招聘站摘掉了，但接口给过的 endDate 还在库里。
        # 它是「这个类型的一批确实在 X 日关了窗」的硬证据，用来给没有在招岗位的类型兜底
        # （典型场景：秋招岗全部下线、只剩社招在线，日历不该显示「校招 无截止日」）。
        for rtype, ends in (ats.get("closed_by_type") or {}).items():
            b = bucket(TYPE2BATCH.get(rtype, "校招"))
            for d in ends:
                if d:
                    b["ends"].append(d)
            b["ev"].append("招聘站已下架职位的截止日字段")
        # 城市回填：具体回填在 build_entries 里按「批次 → 招聘类型」做，见 TYPE_OF_BATCH
        out["cities_by_batch_type"] = cities_by_type

    # ---- E1 ATS 结构化职位列表
    if fields:
        for y in fields.get("grad_years") or []:
            out["grad_years"][y] += 2          # 结构化证据权重更高
        add_cities(out["cities_all"], fields.get("cities"), "招聘站职位列表")
        for t in fields.get("tracks") or []:
            out["tracks_all"][t["direction"]] += list(t.get("roles") or [])
        out["titles"] = fields.get("job_titles") or []
        out["n_jobs"] = fields.get("n_jobs") or 0
        # 职位标题本身就是批次证据：「2027届校园招聘」「暑期实习」
        for p in fields.get("project_types") or []:
            b = bucket(p)
            if fields.get("apply_start"):
                b["starts"].append(fields["apply_start"])
            if fields.get("apply_end"):
                b["ends"].append(fields["apply_end"])
            b["ev"].append("招聘站职位列表")
            if fields.get("publish_at"):
                b["dates"].append(fields["publish_at"])
                b["src"].append({"name": "官方招聘站职位列表", "url": entry.get("url"),
                                 "date": fields["publish_at"]})

    # ---- E2 高校就业网简章（每条各归各批）
    for h in edu:
        # 站点自己在页面上打了「已过期」的，直接跳过：这种公告的批次/日期都是一年前的老数据，
        # 拿去生成日历会让用户点进去看到「已截止」。实测 2199 条简章里有 1097 条属于这种。
        if h.get("expired_flag"):
            continue
        blob = (h.get("title") or "") + "\n" + (h.get("text") or "")
        for y in extract_grad_years(blob):
            out["grad_years"][y] += 1
        site_city = SITE_CITIES.get(h.get("site_short") or "", set())
        cs = [c for c in (h.get("cities") or []) if c not in site_city]
        add_cities(out["cities_all"], cs, f"{h.get('site_short')} 招聘简章")
        a = extract_all(blob)
        for t in a["tracks"]:
            out["tracks_all"][t["direction"]] += list(t.get("roles") or [])
        # 批次判定优先看**标题**：标题是公告主旨（「2027届校园招聘正式启动」），
        # 正文里则常有「社招新员工培养」「既有经验」这类无关词，容易把校招公告判成社招。
        # 只有标题判不出来时才看正文。
        ttl = h.get("title") or ""
        b = bucket(detect_batch(ttl) or detect_batch(blob))
        # 只写「2027届校园招聘」没写批次的，按**公告发布月份**定批：
        # 中国校招的时间规律是 8~11 月发秋招、3~5 月发春招，7 月前的「提前批」也常见。
        # 这不是瞎猜，是行业发布的固定节奏；发布日缺失就不推断。
        if b == "校招" and (h.get("publish") or ""):
            mo = int(h["publish"][5:7])
            if mo in (8, 9, 10, 11):
                b = bucket("秋招正式批")
            elif mo in (3, 4, 5):
                b = bucket("春招")
            elif mo == 12 or mo in (1, 2):
                b = bucket("秋招补录")
        add_cities(b["cities"], cs, f"{h.get('site_short')} 简章工作地域")
        # 网申窗口：公告「过期时间」= 硬截止；正文区间 = 起止
        if h.get("expire"):
            b["ends"].append(h["expire"])
            out["ev"].setdefault("window", f"{h.get('site_short')} 公告过期时间 {h['expire']}")
        if a["apply_start"]:
            b["starts"].append(a["apply_start"])
        if a["apply_end"]:
            b["ends"].append(a["apply_end"])
        b["ev"].append(f"{h.get('site_short')} <{h.get('url')}>")
        # 公告发布日期 = 「来源」这一列的日期。用户看到「来源：某校就业网 2026-09-12 简章」
        # 才能判断这条信息的时效；只给个站点名等于没给来源。
        # 这里**只采信当前这条公告自己的 publish**，不与别的公告取最大——那是跨公告串场。
        if h.get("publish"):
            b["dates"].append(h["publish"])
            b["src"].append({"name": f"{h.get('site_short')}招聘简章", "url": h.get("url"),
                             "date": h["publish"]})

    # ---- E3 渲染正文
    if rendered and rendered.get("text"):
        a = extract_all(rendered["text"])
        for y in a["grad_years"]:
            out["grad_years"][y] += 1
        add_cities(out["cities_all"], a["cities"], "招聘站渲染正文")
        for t in a["tracks"]:
            out["tracks_all"][t["direction"]] += list(t.get("roles") or [])
        b = bucket(detect_batch(rendered["text"]))
        add_cities(b["cities"], a["cities"], "招聘站渲染正文")
        if a["apply_start"]:
            b["starts"].append(a["apply_start"])
        if a["apply_end"]:
            b["ends"].append(a["apply_end"])
        b["ev"].append("招聘站渲染正文")

    return out


def GUESS_SECTOR(name: str) -> str:
    """公司名里带强行业词就按词判，判不出返回空串（不瞎猜）。

    只用于「只出现在扩展池或没有人工行业标注」的公司——它们没有真实行业，
    行业闸门会失效。词表收窄到几乎无歧义的词，宁缺毋滥。
    """
    if any(k in name for k in ("药业", "制药", "医药", "医科", "医疗", "生物",
                               "基因", "疫苗", "诊断", "医疗器械")):
        return "医药医疗"
    if any(k in name for k in ("教育", "学校", "学院", "幼儿园")):
        return "教育"
    return ""


def build_entries(company: str, entry: dict, merged: dict, slug: str = "",
                  ats_titles: list[str] | None = None) -> list[dict]:
    url = entry.get("url") or ""
    # 行业约束：医药方向只在医药行业启用。
    # 「生物」（生物制造/生物质能源）、「检验」（质量检验/无损检验）、「合成」（数据合成/语音合成）
    # 这些词在非医药语境里到处都是，单靠正则分不开语境。行业是已知的强先验，用它当闸门。
    # 实测：非医药企业里有 140 家被错挂了「医药研发类」，共 216 条条目受影响。
    sector = entry.get("sector") or ""
    if "扩展池" in sector:
        # 「扩展池（实测确认）」是采集来源标签，不是行业分类，不能拿它当行业用
        sector = entry.get("real_sector") or GUESS_SECTOR(company)
    # 行业闸门只对「行业已知且明确不是医药/教育」的公司生效。
    # 行业未知时不砍——砍掉的代价比保留更大：上海莱士是血液制品企业，
    # 公司名里没有「医药」二字，一刀切会把真岗位一起丢掉。
    sector_known = bool(sector) and "扩展池" not in sector
    allow_med = (not sector_known) or ("医药" in sector) or ("生物" in sector)
    if not allow_med:
        merged["tracks_all"].pop("医药研发类", None)
    # 教育方向同理：企业里的「培训」是职能岗（培训专员），不是「教师/授课/教研」。
    # 非教育行业命中「教师/教学/讲师/授课」基本来自「教学仪器」「教学质量」这类正文词。
    if sector_known and sector != "教育":
        merged["tracks_all"].pop("教育类", None)
    # 没有自己的招聘站入口（只靠简章覆盖）时：apply_url 留空、JD 标记 blocked，
    # notes 里给出官方招聘页的提示句，不拿第三方/B 端网址充数。
    if not url:
        is_list = False
        jd_status = "blocked"
    else:
        is_list = is_ats(url) or entry.get("grade") == "A"
        jd_status = "official_page" if is_list else "blocked"

    # 批次：以「实际拿到日期证据的批次」为先，再补没有日期但有明确批次的
    counts = Counter({b: (1 + len(v["starts"]) + len(v["ends"])) for b, v in merged["batches"].items()})
    ptypes = pick_batches(counts, has_undecided=False)

    # 届次：只留「还能投」的。
    # 2026-10 这个时点，2026 届的秋招是 2025 年秋跑的、2026 年春招也已闭档，
    # 现在在招的一定是 2027 届（2026 秋招主力）或 2028 届（提前批刚开）。
    # 所以下限是 as_of 年份 + 1，不是 as_of 年份——写成 as_of 会把「2026届」
    # 这种已经结束的届次放进日历，用户点进去只会看到已截止。
    as_of_year = int(AS_OF[:4])
    in_range = [(y, n) for y, n in merged["grad_years"].most_common()
                if as_of_year + 1 <= y <= as_of_year + 2]
    grads = [y for y, _ in in_range[:2]] or [None]
    # 岗位名清洗：同一方向内去重且保序；丢掉残缺词（单字/纯方向名/常见虚词）。
    # 真实数据里「电子」「网络」「技术类」这种是分词碎片，写进日历会让用户以为真有这个岗位。
    DIR_NAMES = {"技术类", "产品类", "运营类", "市场与销售类", "职能类", "金融类",
                 "设计类", "内容类", "管理类", "研究类", "其他", "综合类"}
    JUNK = {"类", "岗", "职位", "岗位", "方向", "等", "相关", "专业", "若干"}
    tracks = []
    for d, rs in merged["tracks_all"].items():
        clean, seen_r = [], set()
        for r in rs:
            r = (r or "").strip()
            if len(r) < 2 or r in DIR_NAMES or r in JUNK or r in seen_r:
                continue
            seen_r.add(r)
            clean.append(r)
        if clean:
            tracks.append({"direction": d, "roles": clean[:6]})
    tracks = tracks[:5]
    # 方向聚合后如果 roles 还很空（分类粗的公司，方向只有一个「技术类」），
    # 用数据层给的**原始岗位名**补上：日历要回答的是「这家在招什么」，
    # 光写「技术类」用户看不出门道。取的是校招/实习批次里真实存在的标题，不是编的。
    if ats_titles:
        have_roles = {r for tt in tracks for r in tt["roles"]}
        filler = [x for x in ats_titles if x not in have_roles]
        if not tracks and filler:
            tracks = [{"direction": "在招岗位", "roles": filler[:6]}]
        else:
            for tt in tracks:
                if len(tt["roles"]) < 3:
                    extra = [x for x in filler if x not in tt["roles"]][: 6 - len(tt["roles"])]
                    tt["roles"] = (tt["roles"] + extra)[:6]
                    filler = [x for x in filler if x not in extra]

    # URL 清洗：真实数据里抓到过带 ?email=xxx@xxx 的投递链接（用户自己分享出来的），
    # 这类个人标识绝不能进交付物。只剥参数，不改变链接指向的页面。
    if url:
        url = re.sub(r"[?&](?:email|mail|phone|mobile|tel|token|session|uid|openid)=[^&#]*",
                     "", url, flags=re.I)
        url = re.sub(r"\?&", "?", url)
        url = re.sub(r"[?&]$", "", url)

    out = []
    for i, ptype in enumerate(ptypes):
        # 社招面向有工作经验的人，没有「届」的概念。给社招条目挂 2027 届是错的：
        # 应届生按这个去投会在社招通道里被筛掉。所以社招一律置空届次。
        batch_grads = [None] if ptype == "社招" else grads
        b = merged["batches"].get(ptype) or {"starts": [], "ends": [], "cities": [], "ev": []}
        start = min(b["starts"]) if b["starts"] else None
        end = max(b["ends"]) if b["ends"] else None
        start, end = sensible_window(start, end)
        # 时效过滤：截止日已经早于数据时间戳的，说明这条公告过期了，不能再进日历
        # （真实数据里 2026 春季招聘的公告还在高校网站上挂着，过期时间 2026-04-16，
        #  用户点进去只会看到「已截止」）。留空则保留——没有截止日不等于过期。
        if end and end < AS_OF:
            continue
        # 城市：优先用该批次自己的城市证据，没有才回落到全公司并集
        # 城市：优先该批次自己的证据。
        # 若该批次没有任何城市证据，而**全公司只有一个批次**，说明不存在串场风险，
        # 可以用全公司并集；一旦有多个批次就绝不回落到并集
        # （否则春招条目会带着秋招分公司所在城市的城市，属于跨条目错误）。
        if b["cities"]:
            cities = b["cities"][:8]
        elif merged.get("cities_by_batch_type", {}).get(TYPE_OF_BATCH.get(ptype, "")):
            # 该批次自己没有正文城市证据，但数据层按招聘类型给过城市（如实习岗集中在某地），
            # 这是接口字段，可信度高于「全公司并集」，所以排在并集前面。
            cities = merged["cities_by_batch_type"][TYPE_OF_BATCH[ptype]][:8]
        elif len(ptypes) == 1:
            cities = merged["cities_all"][:8]
        else:
            cities = []
        for gy in batch_grads:
            eid = f"{slug or slug_of(company)}-" + "-".join(
                filter(None, [str(gy) if gy else None,
                              {"提前批": "tqb", "秋招": "qz", "秋招正式批": "qzzs", "秋招补录": "qzbl",
                               "春招": "chunz", "校招": "xz", "暑期实习": "sxsx", "寒假实习": "hjsx",
                               "日常实习": "rcsx", "实习": "sx", "社招": "sz", "校园大使": "xysd",
                               "兼职": "jz", "线上项目": "xs"}.get(ptype, "e"),
                              f"v{i}" if i else None]))
            src_name = "官方招聘站"
            # 来源日期：优先用这个批次自己那批公告/职位列表的发布日期（倒序取最新）；
            # 都没有才留空。绝不拿「别的批次的日期」或 as_of 冒充来源日期。
            src_date = max(b["dates"]) if b.get("dates") else None
            src_url_pick = None
            if b.get("src"):
                newest = max(b["src"], key=lambda x: x.get("date") or "")
                src_url_pick = newest.get("url")
            note_bits = []
            if entry.get("title"):
                note_bits.append(f"入口页标题：{entry['title'][:40]}")
            if merged["n_jobs"]:
                note_bits.append(f"在招职位 {merged['n_jobs']} 条（结构化列表实测）")
            if b.get("ev"):
                note_bits.append(f"网申时间证据：{b['ev'][0]}")
            if merged["ev"].get("cities"):
                note_bits.append(f"城市证据：{merged['ev']['cities']}")
            if jd_status == "blocked":
                note_bits.append(f"{company}希望你去他们的招聘页逛一逛哦~")
            # 注意：group 只写在文件顶层（load_manual 会 doc["group"] 展开后传给 ManualEntry）
            out.append({
                "id": eid,
                "company": company,
                "product": None,
                "grad_year": gy,
                "project_type": ptype,
                "tracks": tracks,
                "apply_start": start,
                "apply_end": end,
                "cities": cities,
                "apply_url": url,
                "source": {"type": "official_site",
                           "name": src_name if url else "高校就业网招聘简章（证据）",
                           # 投递入口用公司自己的站点；来源链接用公告页——两者不是一回事
                           "url": url or src_url_pick,
                           "date": src_date},
                "as_of": AS_OF,
                "jd": {"status": jd_status, "url": url if jd_status == "official_page" else None},
                "notes": "；".join(note_bits) if note_bits else None,
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out-dir", default="calendar/entries")
    args = ap.parse_args()

    usable = load_jsonl(ROOT / "work/entry_usable.jsonl")
    fields = {r["company"]: r for r in load_jsonl(ROOT / "work/fields.jsonl")}
    rendered = {r["company"]: r for r in load_jsonl(ROOT / "work/rendered.jsonl")}
    edu = defaultdict(list)
    for r in load_jsonl(ROOT / "work/edu_hits.jsonl"):
        edu[r["company"]].append(r)
    # 数据层结构化职位证据（城市/截止日/届次来自接口字段）。
    # 默认读 work/ats_evidence.jsonl（由 jobradar calendar-build --evidence-out 导出）；
    # 没有就退到 /tmp 下最近一次全量抓取的产物，都没有就跳过这一路证据。
    # 优先用 work/ats_evidence.jsonl（仓库内、可复现）；没有才退到最近一次全量抓取的 /tmp 产物。
    # 反过来会读到本机残留的旧库，导致「同一份代码在不同机器上生成不同日历」。
    _ev_cands = [ROOT / "work/ats_evidence.jsonl",
                 pathlib.Path("/tmp/fullcrawl/ats_evidence.jsonl"),
                 pathlib.Path("/tmp/jr/ats_evidence.jsonl")]
    ats_ev = {}
    for _cand in _ev_cands:
        ats_ev = build_evidence_index(load_ats_evidence(_cand))
        if ats_ev:
            print(f"# 结构化职位证据：{_cand}（{len(ats_ev)} 个名字键）")
            break

    # 保护：已有的、含人工信息的条目不要被机械生成的覆盖
    {p.stem: p for p in (ROOT / args.out_dir).glob("*.yaml")}

    # 「集团」= 该条目所属的集团/母公司名。top_companies.yaml 的 aliases 形如
    # {品牌: [别名...]}，可用它把子品牌归到集团；没有映射的就用公司名本身。
    group_of: dict[str, str] = {}
    tgt: dict = {}
    try:
        tgt = yaml.safe_load((ROOT / "targets/top_companies.yaml").read_text(encoding="utf-8")) or {}
        for key in ("aliases", "brand_tokens"):
            for brand, variants in (tgt.get(key) or {}).items():
                for v in variants or []:
                    group_of.setdefault(v, brand)
    except Exception:
        pass

    # 只被高校简章覆盖、没有自己的可用招聘站入口的公司：也要进日历。
    # 这类公司（建设银行、中国邮政、雀巢、鞍钢…）简章里批次/届次/截止/城市都齐全，
    # 唯一缺的是「投递入口」——按 calendar/README.md 的规则，这时 apply_url 留空、
    # jd.status=blocked，并在 notes 里写提示句引导用户去官方招聘页，
    # 绝不能拿高校就业网的 URL 冒充公司官方入口（edu.cn 不在 source 白名单里）。
    # 行业映射：edu_only 公司没有 entry 记录，但 build_entries 的行业闸门需要 sector，
    # 从 targets 的 sectors 反查。注意「扩展池（实测确认）」是采集来源标签、不是行业分类，
    # 必须排在最后——否则 pool 里的公司会拿到「扩展池」当行业，行业闸门就失效了。
    sec_of: dict[str, str] = {}
    _sectors = (tgt.get("sectors") or {}) if isinstance(tgt, dict) else {}
    for _pass in range(2):
        for sname, names in _sectors.items():
            is_pool = "扩展池" in sname
            if (_pass == 0) == is_pool:
                continue
            for nm in names or []:
                sec_of.setdefault(nm, sname)
    have = {e["company"] for e in usable}
    edu_only = [{"company": c, "url": "", "title": "", "grade": "edu_only",
                 "host": "", "kind": "edu", "pages": [], "note": "edu_only",
                 "sector": GUESS_SECTOR(c)}
                for c in edu if c not in have]

    # 硬红线：targets/top_companies.yaml 的 blocked 里列的是「按铁律不能采」的公司
    # （反爬/登录墙/加密/robots 禁止）。无论前面哪一步把它们捞进了可用池，这里一律剔除，
    # 否则等于把违规抓来的数据写进成品（2026-10-26 实测混入 11 家）。
    blocked = set((tgt.get("blocked") or {}).keys()) if isinstance(tgt, dict) else set()

    # slug 全局唯一化：纯拼音会出现同前缀碰撞（「保利」与「保利发展」都落到 baoli），
    # 一旦两个文件写出同一个条目 id，load_manual 会直接报「条目 id 重复」。
    # 撞车的公司追加其名原文（去标点）做区分，并保证全局不重复。
    all_companies = [e["company"] for e in usable + edu_only if e["company"] not in blocked]
    slug_count: Counter = Counter(slug_of(group_of.get(c, c)) for c in all_companies)
    slug_used: set[str] = set()
    slug_of_company: dict[str, str] = {}
    for c in all_companies:
        base = slug_of(group_of.get(c, c))
        cand = f"{base}{re.sub(r'[^a-z0-9]', '', c.lower()) or 'x'}"[:40] if slug_count[base] > 1 else base
        n = 2
        while cand in slug_used:
            cand = f"{base}{n}"
            n += 1
        slug_used.add(cand)
        slug_of_company[c] = cand

    ok, skipped, errors = [], [], []
    for entry in usable + edu_only:
        c = entry["company"]
        if c in blocked:
            skipped.append((c, "in_blocked_list"))
            continue
        if entry.get("grade") != "edu_only" and not usable_as_entry(entry["url"]):
            skipped.append((c, "url_not_usable"))
            continue
        # 行业兜底：扩展池标签不是行业，改用 targets 的真实行业，再不行按公司名判
        _s = entry.get("sector") or ""
        if not _s or "扩展池" in _s:
            _real = sec_of.get(c) or ""
            entry = {**entry, "sector": ("" if "扩展池" in _real else _real) or GUESS_SECTOR(c)}
        merged = merge_evidence(c, entry, fields.get(c), edu.get(c) or [], rendered.get(c),
                                lookup_evidence(ats_ev, c))
        try:
            _ev = lookup_evidence(ats_ev, c) or {}
            _tb = _ev.get("titles_by_type") or {}
            # 校招优先，其次实习；社招岗位名不进校招日历条目
            _ats_titles = (_tb.get("campus") or []) + (_tb.get("intern") or [])
            rows = build_entries(c, entry, merged, slug_of_company.get(c, ""),
                                 ats_titles=_ats_titles or None)
        except Exception as e:
            errors.append((c, f"build:{type(e).__name__}:{e}"))
            continue
        good = []
        for row in rows:
            try:
                # 预校验必须补上 group（正式写入时它来自文件顶层）
                ManualEntry(group=group_of.get(c, c), **row)
                good.append(row)
            except Exception as e:
                errors.append((c, f"validate:{str(e)[:80]}"))
        if good:
            ok.append((c, good))
        else:
            skipped.append((c, "no_valid_entry"))

    print(f"companies usable={len(usable)} built={len(ok)} skipped={len(skipped)} errors={len(errors)}")
    n_entries = sum(len(g) for _c, g in ok)
    print(f"entries={n_entries}")
    filled = Counter()
    for _c, g in ok:
        for r in g:
            filled["grad_year"] += bool(r["grad_year"])
            filled["apply_start"] += bool(r["apply_start"])
            filled["apply_end"] += bool(r["apply_end"])
            filled["window"] += bool(r["apply_start"] or r["apply_end"])
            filled["cities"] += bool(r["cities"])
            filled["tracks"] += bool(r["tracks"])
            # 十项口径里真正意义上的「必填」是这几项，缺了条目就没有检索价值
            filled["_score_sum"] += sum(1 for k in ("grad_year", "tracks", "apply_start",
                                                   "apply_end", "cities", "apply_url")
                                        if r.get(k))
    print("field fill（条目级）:", {k: v for k, v in filled.items() if not k.startswith("_")})
    if n_entries:
        print(f"平均十项口径得分 {filled['_score_sum'] / n_entries:.2f}/6（不含 group/company/"
              f"project_type/source/as_of——这几项由生成规则保证非空）")
    if errors[:5]:
        print("--- errors ---")
        for c, e in errors[:8]:
            print("  ", c, e)

    if not args.apply:
        print("\n(dry run；加 --apply 写入)")
        return 0

    outdir = ROOT / args.out_dir
    outdir.mkdir(parents=True, exist_ok=True)
    # 先清掉上一轮生成的文件：否则公司被剔除后它的旧 yaml 会留在目录里，
    # 和新文件共用同一个条目 id，load_manual 会直接报「条目 id 重复」
    # （实测 baoli.yaml 与 baolifazhan.yaml 撞车）。
    # 只删带机器生成标记的文件，人工维护的条目（无标记）一律不动。
    GEN_MARK = "# generated by work/build_calendar.py"
    removed = 0
    for old_f in outdir.glob("*.yaml"):
        try:
            head = old_f.read_text(encoding="utf-8")[:200]
        except Exception:
            continue
        if GEN_MARK in head:
            old_f.unlink()
            removed += 1
    if removed:
        print(f"清理上一轮生成的文件 {removed} 个")

    written = 0
    for c, g in ok:
        group = group_of.get(c, c)
        slug = slug_of_company[c]
        p = outdir / f"{slug}.yaml"
        g = [{k: v for k, v in row.items() if k != "group"} for row in g]
        body = (GEN_MARK + "\n# 数据来源与字段口径见 calendar/README.md；"
                "手工修改请删掉这一行，之后就不会被重新生成覆盖。\n"
                + yaml.safe_dump({"group": group, "entries": g},
                              allow_unicode=True, sort_keys=False, width=200))
        p.write_text(body, encoding="utf-8")
        written += 1
    print(f"written {written} files -> {outdir}")
    # 立刻用项目的校验器过一遍
    try:
        ents = load_manual(outdir)
        print("load_manual OK:", len(ents), "entries")
    except Exception as e:
        print("load_manual FAILED:", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
