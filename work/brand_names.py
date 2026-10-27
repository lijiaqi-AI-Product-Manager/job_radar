"""给候选池补上「主品牌名 / 官方英文名」——搜索时用得上。

为什么：必应会把长公司名拆成单个汉字去搜——「歌尔股份 官网」返回一堆音乐网站，
「绿联科技 官网」返回「绿」字的字典页，「芯原股份 官网」返回「芯」字的字典页。
换成「歌尔 招聘官网」「绿联 招聘官网」就正常了。

这里只用两种办法取品牌名（都不猜造词）：
1. 去掉地域/后缀：中国石油天然气集团 → 中国石油，北京汽车集团 → 北京汽车，广州汽车集团 → 广州汽车；
2. pool.tsv 第三列里人工录过的品牌名（如 Temu / TME / NetEase Games）直接用。

输出：work/brands.json  {"公司名": ["品牌1", "品牌2", ...]}
"""

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REGION = re.compile(r"^(中国|中华|国家|中央|上海|北京|天津|重庆|广东|广州|深圳|浙江|杭州|江苏|南京|苏州|山东|"
                    r"青岛|四川|成都|湖北|武汉|福建|厦门|河南|郑州|河北|石家庄|湖南|长沙|安徽|合肥|陕西|西安|"
                    r"江西|南昌|云南|昆明|贵州|贵阳|广西|南宁|山西|太原|辽宁|沈阳|大连|吉林|长春|黑龙江|哈尔滨|"
                    r"内蒙古|新疆|甘肃|兰州|宁夏|青海|西藏|海南)")
SUFFIX = re.compile(
    r"(股份有限公司|有限责任公司|有限公司|集团公司|控股集团|集团控股|控股|集团|股份|公司|"
    r"实业|投资|发展|控股有限公司)$")
INDUSTRY = re.compile(
    r"(科技|技术|电子|电气|汽车|银行|证券|基金|保险|地产|置业|医药|药业|食品|"
    r"网络|信息|软件|数据|智能|能源|电力|化工|钢铁|建材|机械|重工|工业|控股|"
    r"新材料|生物|医疗|健康|传媒|文化|旅游|航空|物流|建筑|工程|环保|新能源|半导体|微电子)$")


def variants(name: str) -> list[str]:
    out = [name]
    s = name
    for _ in range(3):
        s2 = SUFFIX.sub("", s)
        if s2 == s:
            break
        s = s2
        out.append(s)
    if s[:2] in ("中国", "中华"):
        s3 = s[2:]
        if len(s3) >= 2:
            out.append(s3)
            s = s3
    else:
        s3 = REGION.sub("", s)
        if s3 and s3 != s:
            out.append(s3)
            s = s3
    if INDUSTRY.search(s):
        s4 = INDUSTRY.sub("", s)
        if len(s4) >= 3:
            out.append(s4)
    # 只保留长度合适、不重复的
    seen, res = set(), []
    for v in out:
        v = v.strip()
        if 2 <= len(v) <= 20 and v not in seen:
            seen.add(v)
            res.append(v)
    return res


def main() -> None:
    rows = list(csv.reader(open(ROOT / "work/pool.tsv", encoding="utf-8"), delimiter="\t"))
    brands = {}
    for r in rows:
        name = r[0]
        brand = (r[2] if len(r) > 2 else "").strip()
        vs = variants(name)
        if brand:
            vs = [brand] + vs
        brands[name] = vs[:4]
    (ROOT / "work/brands.json").write_text(json.dumps(brands, ensure_ascii=False, indent=1), encoding="utf-8")
    for k in ("歌尔股份", "绿联科技", "芯原股份", "广汽集团", "中国石油天然气集团", "中国石油"):
        print(k, "->", brands.get(k))


if __name__ == "__main__":
    main()
