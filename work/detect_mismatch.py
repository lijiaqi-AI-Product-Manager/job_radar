"""入口归属的最后一道校验：检测「挂着别家公司名」的错配。

2026-10-26 实测到的典型错配（都被前几轮规则放过了）：
    一点点     → campus.duxiaoman.com     标题「度小满2027校园招聘」
    东华软件   → neusoft-campus.zhiye.com 标题「东软校招」
    三全食品   → sanyuan.zhiye.com        标题「北京三元食品股份有限公司」
    中国广电   → hr.grgbanking.com        标题「广电运通」
    中航沈飞   → zhaopin.airchina.com.cn  标题「中国航空集团招聘」

做法（纯字符串判定，不再发请求）：
1. 收集全部已知公司名（候选池 1848 家 + 日历已有 group）；
2. 对每个入口的标题 + 主机名 + ATS 租户路径，找出"出现的其他公司名"；
3. 如果本案公司名在其中且是最长匹配 → 通过；
   如果只出现了别家公司名 → 判错配，剔除；
4. 特例：同集团子公司共用入口（中建各局/中核各院/吉利与极氪），
   只要本案名或其主品牌名出现在标题里就保留。

用法：
    python3 work/detect_mismatch.py
"""

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    import yaml

    pool = {}
    for r in csv.reader(open(ROOT / "work/pool.tsv", encoding="utf-8"), delimiter="\t"):
        pool[r[0]] = (r[1], (r[2] if len(r) > 2 else ""))

    # 已知公司名全集（含日历里的人工 group）
    names = set(pool) | {yaml.safe_load(p.read_text(encoding="utf-8")).get("group")
                         for p in (ROOT / "calendar" / "entries").glob("*.yaml")}
    names = {n for n in names if n and len(n) >= 2}
    # 太短的名字（如「一汽」「中粮」）容易误伤，单独放行
    short = {n for n in names if len(n) <= 3}

    rows = [json.loads(s) for s in
            (ROOT / "work/entry_pool.jsonl").read_text(encoding="utf-8").splitlines() if s.strip()]
    brands = json.loads((ROOT / "work/brands.json").read_text(encoding="utf-8"))

    kept, bad = [], []
    # 人工复核过的确定错配（规则难以覆盖的个例）。每条都写明真实归属，便于审计。
    KNOWN_BAD = {
        ("一点点", "duxiaoman.com"): "度小满的校招页，不是一点点",
        ("三全食品", "sanyuan.zhiye.com"): "北京三元食品，不是三全食品",
        ("富国基金", "htffund.zhiye.com"): "汇添富网申系统，不是富国基金",
        ("罗兰贝格", "ronbay.zhiye.com"): "容百集团，不是罗兰贝格",
        ("盛美上海", "sgssemi.zhiye.com"): "盛吉盛（SGSS），不是盛美（ACM Research）",
        ("盼盼食品", "wantwant.zhiye.com"): "旺旺集团，不是盼盼食品",
        ("马钢集团", "mgjs.cn"): "马鞍山钢铁建设集团，不是马钢（马鞍山钢铁股份）",
    }
    for r in rows:
        c, u = r["company"], r["url"]
        for (bad_c, bad_host), why in KNOWN_BAD.items():
            if c == bad_c and bad_host in u:
                bad.append({**r, "why": f"known_bad:{why}"})
                break
        else:
            kept.append(r)
    rows = kept
    kept = []
    for r in rows:
        c, t, u = r["company"], r["title"], r["url"]
        host_path = re.sub(r"^https?://", "", u).lower()
        blob = f"{t} {host_path}"
        # 本案是否出现（公司名 / 主品牌名 / 名字前 4 字）
        own = [c] + brands.get(c, [])
        any(x and len(x) >= 2 and x in blob for x in own)
        if c in short:
            kept.append(r)
            continue
        # 其他公司名是否出现在**标题**里（只看标题，不看域名——域名片段会误伤）
        rivals = []
        for n in names:
            if n == c or len(n) < 3 or n not in t:
                continue
            if any(n in x or x in n for x in own):
                continue
            # 共享中文品牌前缀（≥2 字）视为同一品牌的不同写法：
            #   「宇树Unitree」vs「宇树科技」→ 共享前缀「宇树」
            zh_c, zh_n = re.sub(r"[^\u4e00-\u9fa5]", "", c), re.sub(r"[^\u4e00-\u9fa5]", "", n)
            if len(zh_c) >= 2 and len(zh_n) >= 2 and zh_c[:2] == zh_n[:2]:
                continue
            rivals.append(n)
        # 本案名/品牌是否出现在标题里（仅标题）
        own_in_title = any(x and len(x) >= 2 and x in t for x in own)
        # 同集团子公司共用入口是事实，放行：
        #   国家电网 ↔ 南瑞集团（南瑞是国网直属科研产业单位）
        #   青瓷游戏 ↔ 吉比特、招商工业 ↔ 招商局（母子公司）
        #   中国人寿 ↔ 广银理财（广银理财是中国人寿旗下）
        SAME_GROUP = {
            "招商局": "招商局集团及下属公司共用招聘门户",
            "吉比特": "青瓷游戏为吉比特控股子公司",
            "中建": "中建各工程局共用集团招聘门户",
            "中核": "中核各院所共用集团招聘门户",
            "中船": "中船各研究所共用集团招聘门户",
            "航空工业": "航空工业各厂所共用集团招聘门户",
            "中国电科": "中国电科各研究所共用集团招聘门户",
            "南瑞集团": "南瑞集团是国家电网直属单位",
            "国家电网": "国网下属单位共用招聘门户",
            "中国人寿": "广银理财为中国人寿旗下",
            "吉利": "吉利与极氪/领克共用招聘门户",
            "长城": "长城汽车与蜂巢等子公司共用门户",
            "长安": "长安汽车与长安福特等合资公司共用门户",
            "阿里": "阿里系各业务线共用集团招聘门户",
            "腾讯": "腾讯系各工作室共用集团招聘门户",
            "字节": "字节系各产品线共用集团招聘门户",
            "美团": "美团系各业务线共用集团招聘门户",
            "网易": "网易系各业务线共用集团招聘门户",
        }
        if rivals and not own_in_title:
            grp = next((g for g in SAME_GROUP if any(g in n for n in rivals)), None)
            if grp:
                kept.append({**r, "note": f"same_group:{SAME_GROUP[grp]}"})
                continue
            longest = max(rivals, key=len)
            bad.append({**r, "why": f"title_names_other:{longest}"})
            continue
        if rivals and own_in_title:
            # 两边都出现在标题：本案更长的那个说了算（「中国建材总院」> 「中国建筑」）
            own_len = max((len(x) for x in own if x and x in t), default=0)
            if max(len(n) for n in rivals) > own_len:
                bad.append({**r, "why": f"longer_rival:{max(rivals, key=len)}"})
                continue
        kept.append(r)

    (ROOT / "work/entry_pool.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in kept), encoding="utf-8")
    (ROOT / "work/entry_mismatch.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in bad), encoding="utf-8")

    print("kept", len(kept), "mismatch", len(bad))
    for x in bad[:40]:
        print("  MISMATCH", x["company"], "|", x["url"][:56], "|", x["title"][:26], "|", x["why"][:30])


if __name__ == "__main__":
    main()
