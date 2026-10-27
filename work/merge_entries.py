"""把三轮发现的入口合并、清洗、定型（唯一真源）。

输入：work/careers_final.jsonl（主流程确认）+ work/careers_rescued.jsonl（专项复核）
输出：work/entry_pool.jsonl  —— 每家公司一条，字段：
    company / sector / url / title / conf(high|low|rescue) / host / source_round

清洗规则（宁缺毋滥，上架标准）：
1. 硬拒：应用商店、内容农场、问答聚合、招聘中介、高校就业网、政府就业平台、财经门户、
   网盘/文档站、短链、以及任何第三方招聘平台域名；
2. 归属：必须能证明这个入口属于这家公司——标题含公司名，或域名/路径含公司拼音/英文 token，
   或 ATS 租户路径含 token，或该 URL 在「已被官网首页反查确认」的链接集合里；
3. 同一 URL 被不同集团认领且标题写的是别家名 → 判冲突，全部剔除；
4. 同集团子公司共用入口（如中建各局都用 recruit.cscec.com）→ 保留，这是事实，不是错配。

用法：
    python3 work/merge_entries.py
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hostrules import usable_as_entry  # noqa: E402

ATS = ("zhiye.com", "hotjob.cn", "mokahr.com", "myworkdayjobs.com", "myworkday.cn", "feishu.cn",
       "f.mioffice.cn", "italent.cn", "dayee.com", "hcmcloud.cn", "career.site")

# 硬拒域名（主机级）
# 注意：只能拒「门户/媒体」主机，不能连坐它的招聘子域。
# 例：www.163.com 是网易新闻门户（拒），但 campus.163.com 是网易官方招聘站（要留）；
#     jobs.bytedance.com / careers.ctrip.com / campus.jd.com 同理。
# 所以下面把「媒体域名」一律限定为 www./m./news. 前缀，而不是整个域。
REJECT_HOST = re.compile(
    r"("
    r"\.edu\.cn$|\.edu$|"                                    # 高校
    r"^career\.(uibe|nankai|muc|cup|xidian|xujc|ynu|sdu|buct|shiep|neuq)\.|"
    r"^job\.(sjtu|hdu|xidian|ynu|nankai)\.|"
    r"(^|\.)zhaopin\.com$|(^|\.)51job\.com$|(^|\.)liepin\.com$|(^|\.)zhipin\.com$|boss直聘|"
    r"(^|\.)nowcoder\.com$|(^|\.)kanzhun\.com$|(^|\.)yingjiesheng\.com$|(^|\.)shixiseng\.com$|"
    r"(^|\.)jobui\.com$|(^|\.)dajie\.com$|(^|\.)chinahr\.com$|(^|\.)gaoxiaojob\.com$|"
    r"(^|\.)ejob\.|(^|\.)chinajob\.|(^|\.)gxrc\.|(^|\.)offcn\.|(^|\.)gwy\.com$|"
    r"(^|\.)aiqicha\.baidu\.com$|(^|\.)baike\.|(^|\.)zhuanlan\.|(^|\.)zhihu\.com$|"
    r"(^|\.)douban\.com$|(^|\.)toutiao\.com$|(^|\.)csdn\.net$|(^|\.)jianshu\.com$|"
    r"(^|\.)wikipedia\.|(^|\.)wikiwand\.|(^|\.)eastmoney\.com$|(^|\.)10jqka\.com$|"
    r"(^|\.)hexun\.com$|(^|\.)cnstock\.com$|(^|\.)stcn\.com$|(^|\.)cls\.cn$|"
    r"(^|\.)autohome\.com\.cn$|(^|\.)pcauto\.com\.cn$|(^|\.)yiche\.com$|(^|\.)dongchedi\.com$|"
    r"(^|\.)eet-china\.com$|(^|\.)smm\.cn$|(^|\.)qianzhan\.com$|(^|\.)chyxx\.com$|"
    r"(^|\.)askci\.com$|(^|\.)huxiu\.com$|(^|\.)tmtpost\.com$|(^|\.)donews\.com$|"
    r"(^|\.)techweb\.com\.cn$|(^|\.)cnbeta\.com$|(^|\.)ithome\.com$|(^|\.)pconline\.com\.cn$|"
    r"(^|\.)zol\.com\.cn$|(^|\.)docin\.com$|(^|\.)doc88\.com$|(^|\.)renrendoc\.com$|"
    r"(^|\.)360doc\.com$|(^|\.)baijiahao\.baidu\.com$|(^|\.)ifeng\.com$|(^|\.)thepaper\.cn$|"
    r"(^|\.)jiemian\.com$|(^|\.)yicai\.com$|(^|\.)guancha\.cn$|"
    r"hahazhao|ykof\.|gxbys\.|deizao\.|zhaopinbao|15386\.cn|zhidianmijin|shanganclaw|hicv\.cn|"
    r"sj\.qq\.com|appdetail|^apps\.|itunes\.apple|play\.google|"
    r"baike\.|zidian\.|hanyu|hgcha|chagushici|gushici\.|iciba\.com|kdocs\.cn$|"
    r"jinliqiuzhi|mianlingai|qcc\.com|tianyancha\.com$|qichacha|aiqicha|"
    r"(^|\.)sm\.ziroom|beijing\.anjuke|"
    r"\.gov\.cn$|rc\.qingdao\.gov|"
    # —— 媒体门户：只拒门户主体，不连坐招聘子域 ——
    r"^mp\.weixin\.qq\.com$|"
    r"^(?:m|www|wap|news|ent|sports|tech|finance|money|auto|house|edu|games?|sports|mil|"
    r"astro|book|reads|health|baby|diy|travel|fashion|digi|it|home|cul|gd|view|comment|"
    r"blog|video|photo|pic|slide|topic|special|zt|live|v|f|t|k)\.(sohu|sina|163|qq|ifeng|"
    r"thepaper|toutiao|baidu)\.(com|cn|com\.cn)$"
    r")", re.I)

REJECT_PATH = re.compile(
    r"(/(square|wenda|zhidao|baike|wiki|article|news|blog|p)/|"
    r"/20\d{2}[-/]\d{2}/|"
    r"\.(pdf|doc|docx|xls|xlsx|zip|rar)$)", re.I)


def host_of(u: str) -> str:
    try:
        return (urlsplit(u).hostname or "").lower()
    except Exception:
        return ""


def flat(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main() -> None:
    rows = []
    for name, conf_default in (("work/careers_final.jsonl", None), ("work/careers_rescued.jsonl", "rescue")):
        p = ROOT / name
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            b = r.get("best")
            if not b:
                continue
            rows.append({
                "company": r["company"], "sector": r.get("sector") or "",
                "url": b["url"], "title": b.get("title") or "",
                "snippet": b.get("snippet") or "", "directions": b.get("directions") or [],
                "tokens": r.get("tokens") or [], "conf": r.get("conf") or conf_default or "low",
                "origin": name.split("/")[-1].replace(".jsonl", ""),
            })

    owners: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        owners[r["url"]].add(r["company"])

    kept, dropped = [], []
    by_company: dict[str, list] = defaultdict(list)
    for r in rows:
        u, t, c = r["url"], r["title"], r["company"]
        h = host_of(u)
        # 统一用 hostrules 判据：聚合站/媒体门户/高校站不能当入口；ATS 与招聘子域放行
        if not h or not usable_as_entry(u) or REJECT_PATH.search(urlsplit(u).path or ""):
            dropped.append({**r, "why": "third_party"})
            continue
        f = flat(u)
        name_hit = bool(c) and (c in t or (len(c) >= 3 and c[:3] in t))
        token_hit = any(tok and tok in f for tok in r["tokens"])
        ats = any(h == a or h.endswith("." + a) for a in ATS)
        strong = name_hit or (ats and token_hit) or token_hit
        others = owners[u] - {c}
        if others and not name_hit and not (ats and token_hit):
            dropped.append({**r, "why": "conflict:" + ",".join(sorted(others))[:40]})
            continue
        by_company[c].append({**r, "strong": strong})

    # 每家公司只保留一个最佳入口：强证据优先，标题带"校园/校招"优先，路径短优先
    for c, lst in by_company.items():
        lst.sort(key=lambda r: (
            0 if r["strong"] else 1,
            0 if re.search(r"校园|校招|campus", r["title"] + r["url"], re.I) else 1,
            0 if re.search(r"招聘|career|job|join|zhaopin", r["title"] + r["url"], re.I) else 1,
            len(urlsplit(r["url"]).path or "/"),
            r["url"],
        ))
        best = lst[0]
        kept.append({
            "company": c, "sector": best["sector"], "url": best["url"], "title": best["title"],
            "snippet": best["snippet"], "directions": best["directions"],
            "tokens": best["tokens"], "conf": "high" if best["strong"] else "low",
            "alts": [x["url"] for x in lst[1:4]], "origin": best["origin"],
        })

    kept.sort(key=lambda r: r["company"])
    out = ROOT / "work/entry_pool.jsonl"
    out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in kept), encoding="utf-8")
    rej = ROOT / "work/entry_rejected.jsonl"
    rej.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in dropped), encoding="utf-8")

    print("kept", len(kept), Counter(r["conf"] for r in kept), Counter(r["sector"] for r in kept).most_common(5))
    print("dropped", len(dropped), Counter(r["why"].split(":")[0] for r in dropped))
    print("--- 抽查 low ---")
    for r in [x for x in kept if x["conf"] == "low"][:20]:
        print("  ", r["company"], "|", r["url"][:70], "|", r["title"][:30])


if __name__ == "__main__":
    main()
