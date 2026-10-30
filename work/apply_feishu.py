"""把 subdomain.center 枚举到的飞书招聘门户探活后写成单公司 source 文件。

飞书门户的 `<title>` 就是门户名，但一半是「欢迎加入X / 我在X等你来 / Join us」这类口号，
所以这里保留一张人工核准表（slug → 公司名），只写有岗位（count>0）且能定归属的门户。

用法：python work/apply_feishu.py [--write]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.feishu_atsx import recruit_type_of  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}
CORE = re.compile(r"(股份有限公司|有限责任公司|有限公司|集团控股|集团|控股|公司)$")
SLOGAN = re.compile(r"(欢迎加入|加入我们|加入|诚聘|招聘中|等你来|Join us|JOIN US|我们|一起|冠军|匠心|精品|首页|官网)")
BADC = re.compile(r"[！!，,、。；;：:？?~～|｜]")

# 人工核准：slug → 公司名（只收能确定归属的；口号型标题不自动猜）
NAMES = {
    "aibee": "爱笔智能", "asensing": "导远电子", "autratech": "千挂科技",
    "b9nhtlfpd3": "零洞科技", "bambulab": "拓竹科技", "bggc": "标果",
    "bio-germ": "伯杰医疗", "blacklake": "黑湖科技", "bluefocus": "蓝色光标",
    "bluepha": "蓝晶微生物", "chilun": "齿轮易创", "coconutisland": "椰岛游戏",
    "cu4wl7ik89": "Ping++", "dedao": "得到", "ealklohoih0": "湖北三宁化工",
    "ecoflow": "正浩创新", "enjoymove": "映驰科技", "epropulsion": "逸动科技",
    "flexivrobotics": "非夕科技", "forchangesz": "风变科技", "fpq5u8xh3h": "万集科技",
    "geg7eg8cyc": "芯耀辉科技", "global-intco": "英科再生", "gv0lundj7f": "优复医疗",
    "h9f4zz91q9": "帆书", "hellotalk": "HelloTalk", "heygears": "黑格科技",
    "honycapital": "弘毅投资", "icleague": "芯盟科技", "jzyxgames": "极致游戏",
    "k34w0rqi63": "我要去哪", "k74u68pb5x": "赞意", "leoao-inc": "乐刻运动",
    "liangdao-intelligence": "亮道智能", "lizhi2021": "荔枝集团", "maimai": "脉脉",
    "meidengtech": "美登科技", "merico": "思码逸", "micoworld": "米可世界",
    "moonton": "沐瞳科技", "mshare": "萌想科技", "mthreads": "摩尔线程",
    "mzefbq5kzr": "合见工软", "nor7qsazs0": "星际悦动", "o31ogeuo36": "元旭半导体",
    "onepiece-group": "万皮思", "pinfire": "圈量科技", "qimaitech": "企迈科技",
    "quvideo": "小影科技", "realai": "瑞莱智慧", "refiregroup": "重塑能源",
    "rivergame": "河流游戏", "rv6kcivzwf": "弈芯科技", "srzivpfqpa": "保碧新能源",
    "uq1h428xyc": "蓝箭航天", "utopilot": "友道智途", "vnet": "世纪互联",
    "webeye": "WebEye", "westwell": "西井科技", "yeepay": "易宝支付",
    "yekk33cgru": "南讯股份", "yftech2012": "远峰科技", "yimiandata": "一面数据",
    "ying-dao": "分叉智能", "yizhisec": "一知安全", "z1zgmci7a8s": "桂林啄木鸟医疗",
    "zva7hqcdq1o": "江苏丽王新材料",
    # 2026-10-28 Wayback 批次：标题是口号/英文品牌，按公开信息核准
    "aez5tpi4f5": "深知未来", "babycare": "Babycare", "dptechnology": "深势科技",
    "houmo": "后摩智能", "huanle": "欢乐互娱", "iairnznqr8": "懂球帝",
    "iwhih7is28": "北京发那科", "juzihudong": "句子互动", "leiniao-ibg": "雷鸟创新",
    "mediastorm": "影视飓风", "phigentai": "鉴智机器人", "sii-czxy": "上海创智学院",
    "tigertech": "老虎国际", "w0bmksui7q": "顽岩资产", "xingyun": "行云集团",
    "xxx0an5xw1s": "江波龙",
}


def core(name: str) -> str:
    return CORE.sub("", (name or "").strip())


def pick_company(slug: str, raw: str) -> str:
    """人工核准表优先；其次用门户 <title> 清洗出来的名字，口号型标题一律不收。"""
    if slug in NAMES:
        return NAMES[slug]
    name = (raw or "").strip()
    if len(name) < 2 or SLOGAN.search(name) or BADC.search(name):
        return ""
    return name


def _posts(c: httpx.Client, base: str, token: str, pt: int, path: str | None) -> tuple[int, list]:
    """按适配器的头部规则取一页：`path=None` 不发 website-path（门店挂在 /index 时的口径）。"""
    hdrs = {"x-csrf-token": token, "Content-Type": "application/json",
            "Accept": "application/json", "Referer": base + "/" + (path or "index")}
    if path:
        hdrs["website-path"] = path
    payload = {"portal_type": pt, "limit": 100, "offset": 0, "portal_entrance": 1,
               "keyword": "", "job_category_id_list": [], "location_code_list": [],
               "subject_id_list": [], "recruitment_id_list": []}
    rr = c.post(base + "/api/v1/search/job/posts", json=payload, headers=hdrs, timeout=25)
    data = rr.json().get("data") or {}
    return int(data.get("count") or 0), data.get("job_post_list") or []


def probe(c: httpx.Client, slug: str) -> dict | None:
    base = f"https://{slug}.jobs.feishu.cn"
    try:
        r = c.get(base + "/", timeout=20)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    m = re.search(r"<title>(.*?)</title>", r.text, re.S)
    title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    try:
        tok = c.post(base + "/api/v1/csrf/token", json={"portal_entrance": 1}, timeout=20)
        token = (tok.json().get("data") or {}).get("token")
    except Exception:
        token = None
    if not token:
        return None
    best = 0
    campus = 0
    ptype = 3
    path: str | None = None
    # `website_path: campus` 的门户必须带 `website-path: campus` 头；挂在 `/index` 的门户带了就
    # 回 `{"code": -9000003, "message": "site not exist"}`（2026-10-28 度小满等 21 个门户实测）。
    # 选口径按「校招岗数优先」：蔚来用 campus 口径是 863 条全校招，用 index 口径是 2050 条混排
    # 但第一页 0 条校招——只看总数会选错口径。纯社招门户入不了库（2026-10-28 删过 57 个）。
    for cand_path in ("campus", None):
        for pt in (3, 2):
            try:
                n, posts = _posts(c, base, token, pt, cand_path)
            except Exception:
                continue
            n_campus = sum(1 for p in posts if recruit_type_of(p) in ("campus", "intern"))
            if (n_campus, n) > (campus, best):
                best, campus, ptype, path = n, n_campus, pt, cand_path
    return {"title": title, "count": best, "portal_type": ptype, "campus": campus,
            "website_path": path or "index"}


def load_hits() -> list[dict]:
    """三路发现结果：subdomain.center / 公开代码搜索 / Wayback CDX 主机枚举。"""
    rows: list[dict] = []
    seen: set[str] = set()
    for name in ("sd_hits.jsonl", "code_hits.jsonl", "wayback_hits.jsonl"):
        p = WORK / name
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            d = json.loads(ln)
            if d.get("platform") != "feishu_atsx" or not d.get("slug"):
                continue
            if d["slug"] in seen:
                continue
            seen.add(d["slug"])
            rows.append(d)
    return rows


def main() -> None:
    write = "--write" in sys.argv
    refresh = "--refresh" in sys.argv
    hits = load_hits()
    names: dict[str, str] = {}
    for h in hits:
        s = h["slug"]
        co = pick_company(s, h.get("company") or "")
        if len(co) >= 2:
            names[s] = co
    slugs = list(names)
    existing = load_sources(ROOT / "sources")
    have_co = {core(s.company) for s in existing}
    have_id = {s.id for s in existing}

    # --refresh：上一轮由本脚本写过、但门户其实挂在 /index 而错写成 campus 的那批，重探覆盖
    prev: set[str] = set()
    if refresh:
        p = WORK / "feishu_counts.jsonl"
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    d = json.loads(ln)
                    if d.get("campus", 0) > 0:
                        prev.add(d["slug"])

    todo = [s for s in slugs
            if (s not in have_id and core(names[s]) not in have_co) or s in prev]
    print(f"候选飞书门户 {len(slugs)} 个，去重后待探活 {len(todo)} 个")
    rows = []
    with httpx.Client(headers=UA, follow_redirects=True, timeout=25) as c:
        for i, s in enumerate(todo, 1):
            info = probe(c, s)
            if info:
                rows.append({"slug": s, "company": names[s], **info})
                if i % 10 == 0:
                    print(f"  ... {i}/{len(todo)} 有岗 {sum(1 for x in rows if x['count'] > 0)}")
    open(WORK / "feishu_counts.jsonl", "w", encoding="utf-8").write(
        "".join(json.dumps({"platform": "feishu_atsx", **r}, ensure_ascii=False) + "\n" for r in rows))
    live = [r for r in rows if r["campus"] > 0]
    print(f"存活 {len(rows)} 个，其中有校招/实习岗 {len(live)} 个（纯社招门户不入库）")
    for r in live[:12]:
        print(f"  {r['slug']:<24} {r['company']:<14} {r['campus']:>4}/{r['count']:<5} {r['title'][:24]}")
    if not write:
        print("（dry-run，加 --write 落盘）")
        return

    for r in live:
        slug = r["slug"]
        body = f"""id: {slug}
company: {r['company']}
adapter: feishu_atsx
recruit_types: [campus, intern]
rate_limit_rps: 1
params:
  base_url: "https://{slug}.jobs.feishu.cn"
  website_path: {r['website_path']}
  portal_type: {r['portal_type']}
  page_size: 100
  job_url: "https://{slug}.jobs.feishu.cn/{r['website_path']}/position/{{id}}/detail"
compliance:
  checked_on: 2026-10-28
  robots: "none"            # robots.txt 404（平台层无站点级规则）；只读公开职位列表，不触达 /referral
  terms: "飞书招聘 ATSX 门户：匿名 csrf token + 公开职位列表 JSON，无登录、无验证码、无签名校验。会话 token 只在内存中使用（docs/DEVELOPMENT.md 铁律 1）。用户协议待人工复核"
  notes: "2026-10-28 子域枚举（subdomain.center）与公开代码搜索发现 {slug} 门户；门户 <title> 为「{r['title'][:40]}」，portal_type={r['portal_type']} 时公开职位 {r['count']} 条（其中校招/实习 {r['campus']} 条）。"
"""
        open(ROOT / "sources" / f"{slug}.yaml", "w", encoding="utf-8").write(body)
    after = load_sources(ROOT / "sources")
    print(f"写入 {len(live)} 个飞书门户：{len(existing)} → {len(after)} 源、"
          f"{len({core(s.company) for s in after})} 家公司")


if __name__ == "__main__":
    main()
