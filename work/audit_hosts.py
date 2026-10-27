"""主机级体检：把「一个域名服务很多家公司」的招聘中介站全部揪出来。

2026-10-26 实测到的灾难：campus.niuqizp.com（牛企直聘）被当成 54 家公司的「官方入口」——
它是聚合站，不是任何公司的官网。同类还有 upcv.tech / fenbi.com / qiuzhaowang.com / jrzp.com。

注意区分两类"一域多司"：
- **聚合中介**：域名不含任何一家公司的品牌词 → 一律剔除（它服务所有公司，服务不了"官方"）；
- **ATS 平台**：zhiye.com / hotjob.cn / mokahr.com / feishu.cn 等，租户路径里带公司标识 → 保留，
  这是公司自己在 ATS 上开的招聘门户，是官方入口；
- **集团共用**：recruit.cscec.com（中建各局）、cnnc.zhiye.com（中核各院）→ 保留，
  只要标题确实是该集团/该子公司的招聘页。

输出：work/entry_pool.jsonl 覆盖写入（已剔除聚合站） + work/host_audit.json 供人工复核
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent

ATS = ("zhiye.com", "hotjob.cn", "mokahr.com", "myworkdayjobs.com", "myworkday.cn", "feishu.cn",
       "f.mioffice.cn", "italent.cn", "dayee.com", "hcmcloud.cn", "career.site")

# 已知招聘聚合/中介平台（主机级），不是任何公司的官方站
AGGREGATOR = re.compile(
    r"(niuqizp|upcv|fenbi|qiuzhaowang|jrzp|zhaopin\.com|51job|liepin|zhipin|nowcoder|kanzhun|"
    r"yingjiesheng|shixiseng|jobui|dajie|chinahr|gaoxiaojob|gxrc|ejob|chinajob|offcn|gwy\.com|"
    r"jobui|zhaopinbao|qiuzhi|liebiao|hahazhao|ykof|gxbys|deizao|uhouzz|zhaopinhu|"
    r"chinacareer|jobcn|myjob|528|ganji|58\.com)", re.I)


def host(u: str) -> str:
    return (urlsplit(u).hostname or "").lower()


def main() -> None:
    rows = [json.loads(s) for s in
            (ROOT / "work/entry_pool.jsonl").read_text(encoding="utf-8").splitlines() if s.strip()]
    per_host: dict[str, list] = defaultdict(list)
    for r in rows:
        per_host[host(r["url"])].append(r)

    audit = {}
    keep, drop = [], []
    for h, lst in per_host.items():
        companies = sorted({r["company"] for r in lst})
        is_ats = any(h == a or h.endswith("." + a) for a in ATS)
        is_agg = bool(AGGREGATOR.search(h))
        audit[h] = {"n": len(companies), "companies": companies[:8], "ats": is_ats, "aggregator": is_agg}
        if is_agg:
            drop.extend({"company": r["company"], "url": r["url"], "why": "aggregator_host"} for r in lst)
            continue
        if len(companies) >= 3 and not is_ats:
            # 非 ATS 域名却服务 ≥3 家公司：一定是聚合/集团门户。集团门户看标题是否含公司名
            for r in lst:
                c = r["company"]
                if c in r["title"] or (len(c) >= 3 and c[:3] in r["title"]):
                    keep.append(r)
                else:
                    drop.append({"company": c, "url": r["url"], "why": f"shared_host:{h}"})
            continue
        keep.extend(lst)

    (ROOT / "work/entry_pool.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in keep), encoding="utf-8")
    (ROOT / "work/host_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "work/host_dropped.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in drop), encoding="utf-8")

    print("keep", len(keep), "drop", len(drop), Counter(x["why"].split(":")[0] for x in drop))
    print("--- 一域多司（未剔除的）---")
    for h, a in sorted(audit.items(), key=lambda x: -x[1]["n"])[:15]:
        if a["n"] >= 2:
            print(f"  {h:42s} {a['n']:3d} 家 ats={a['ats']} 例:{','.join(a['companies'][:4])}")


if __name__ == "__main__":
    main()
