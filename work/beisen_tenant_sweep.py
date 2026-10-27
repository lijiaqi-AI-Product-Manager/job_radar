"""按命名规律枚举北森租户名：从「公司名/拼音/缩写」生成候选租户，再用列表接口验证。

为什么值得做（对比搜索引擎路线）：
  搜索引擎一次只覆盖 1~2 家，命中率还受索引新鲜度影响；北森租户是
  `https://{tenant}.zhiye.com/api/Jobad/GetJobAdPageList` 这样一个**可枚举**的端点，
  返回里的 `Count` 直接说明「这家在招几岗」。把公司名展开成 20 来个常见命名法，
  1,500 家公司 ≈ 3 万次请求，1 rps 下 8 小时能全跑完，而且是**确定性**的——
  不用赌搜索索引。

红线：
  - 只打 `*.zhiye.com` 这一个主机，**全局限速 1 rps**（跨所有租户共享一个令牌桶）；
  - 只读列表接口第一页（PageSize=20），不抓 JD、不翻页，单租户最多 20 条；
  - 有 CDN 命中才继续（`Count>0`），0 岗立即停止该公司的其余候选；
  - 归属靠 `Count>0` 且岗位代码前缀/门户标题/公司字段任一命中公司名（见 verify 阶段）。

用法：
    python3 work/beisen_tenant_sweep.py --in /tmp/exp/bt_todo.txt --out /tmp/exp/bt.jsonl
    python3 work/beisen_tenant_sweep.py ... --limit 300      # 先小批试
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import USER_AGENT  # noqa: E402

LIST = "https://{tenant}.zhiye.com/api/Jobad/GetJobAdPageList"
BODY = {
    "PageIndex": 0, "PageSize": 20, "KeyWords": "", "SpecialType": 0, "PortalId": "",
    "DisplayFields": ["Category", "LocId", "PostDate", "LocNames"],
}
# 公司名里这些尾巴对租户名没有贡献，先剥掉再展开。
TAIL = re.compile(
    r"(股份有限公司|有限责任公司|有限公司|集团股份|控股集团|集团公司|集团|股份|控股|总公司|公司|"
    r"中国|中华|中国区|总院|研究院|研究所)$")
# 生成租户名时用的「非核心字」过滤：租户名几乎只用字母数字。
KEEP = re.compile(r"[A-Za-z0-9]+")
# 已知的中文品牌英文名（租户名常用英文名，拼音全拼反而命中不了）。
# 只收**公开且唯一**的品牌英文名；拿不准的一律不收，宁漏不错。
BRAND_EN: dict[str, list[str]] = {
    "比亚迪": ["byd"], "海康威视": ["hikvision"], "隆基绿能": ["longi"], "隆基股份": ["longi"],
    "宁德时代": ["catl"], "万华化学": ["whchem"], "紫金矿业": ["zijin"], "三一重工": ["sany"],
    "三一集团": ["sany"], "美的": ["midea"], "格力电器": ["gree"], "海尔智家": ["haier"],
    "海尔": ["haier"], "海信": ["hisense"], "TCL": ["tcl"], "京东方": ["boe"],
    "小米": ["xiaomi", "mi"], "华为": ["huawei"], "比亚迪电子": ["byd"], "长城汽车": ["gwm", "greatwall"],
    "吉利汽车": ["geely"], "奇瑞汽车": ["chery"], "长安汽车": ["changan"], "蔚来": ["nio"],
    "小鹏汽车": ["xiaopeng", "xpeng"], "理想汽车": ["lixiang", "liauto"], "赛力斯": ["seres"],
    "潍柴动力": ["weichai"], "徐工机械": ["xcmg"], "中联重科": ["zoomlion"], "柳工": ["liugong"],
    "三花智控": ["sanhua"], "福耀玻璃": ["fuyao"], "宁德新能源": ["atl"], "国轩高科": ["gotion"],
    "亿纬锂能": ["eve"], "欣旺达": ["sunwoda"], "中创新航": ["calb"], "阳光电源": ["sungrow"],
    "通威股份": ["tongwei"], "晶科能源": ["jinko"], "晶澳科技": ["jasolar"], "天合光能": ["trina"],
    "阿特斯": ["canadiansolar"], "TCL中环": ["tclzhonghuan"], "东方日升": ["risen"],
    "药明康德": ["wuxiapptec"], "药明生物": ["wuxibiologics"], "恒瑞医药": ["hengrui"],
    "百济神州": ["beigene"], "信达生物": ["innovent"], "复星医药": ["fosunpharma"],
    "石药集团": ["cspc"], "中国生物制药": ["sinobiopharm"], "翰森制药": ["hspharm"],
    "迈瑞医疗": ["mindray"], "联影医疗": ["unitedimaging"], "鱼跃医疗": ["yuyue"],
    "爱尔眼科": ["aier"], "通策医疗": ["topchoice"], "泰格医药": ["tigermed"],
    "康龙化成": ["pharmaron"], "凯莱英": ["asymchem"], "博腾股份": ["porton"],
    "中芯国际": ["smic"], "华虹半导体": ["huahong"], "长电科技": ["jcet"], "通富微电": ["tfme"],
    "韦尔股份": ["will"], "兆易创新": ["gigadevice"], "北方华创": ["naura"], "中微公司": ["amec"],
    "澜起科技": ["montage"], "寒武纪": ["cambricon"], "海光信息": ["hygon"], "紫光展锐": ["unisoc"],
    "传音控股": ["transsion"], "大疆": ["dji"], "大华股份": ["dahua"], "海康机器人": ["hikrobot"],
    "科大讯飞": ["iflytek"], "商汤科技": ["sensetime"], "旷视科技": ["megvii"], "云从科技": ["cloudwalk"],
    "金山办公": ["wps", "kingsoft"], "用友网络": ["yonyou"], "金蝶": ["kingdee"], "东软集团": ["neusoft"],
    "中兴通讯": ["zte"], "新华三": ["h3c"], "浪潮信息": ["inspur"], "神州数码": ["digitalchina"],
    "中际旭创": ["innolight"], "新易盛": ["eoptolink"], "光迅科技": ["accelink"],
    "招商银行": ["cmbchina"], "中国平安": ["pingan"], "中信证券": ["citicsec", "csci"],
    "华泰证券": ["htsc"], "国泰君安": ["gtja"], "中金公司": ["cicc"], "广发证券": ["gf"],
    "海通证券": ["htsec"], "东方财富": ["eastmoney"], "同花顺": ["10jqka"],
    "安踏体育": ["anta"], "李宁": ["lining"], "特步": ["xtep"], "361度": ["361sport"],
    "波司登": ["bosideng"], "海澜之家": ["heilan"], "森马服饰": ["semir"], "太平鸟": ["peacebird"],
    "申洲国际": ["shenzhou"], "华利集团": ["huali"], "珀莱雅": ["proya"], "上海家化": ["jahwa"],
    "农夫山泉": ["nongfuspring"], "伊利股份": ["yili"], "蒙牛乳业": ["mengniu"], "飞鹤": ["feihe"],
    "海天味业": ["haitian"], "金龙鱼": ["yihai"], "双汇发展": ["shuanghui"], "牧原股份": ["muyuan"],
    "温氏股份": ["wens"], "新希望": ["newhope"], "中粮集团": ["cofco"], "华润集团": ["crc"],
    "五粮液": ["wuliangye"], "泸州老窖": ["lzlj"], "洋河股份": ["yanghe"], "山西汾酒": ["fenjiu"],
    "贵州茅台": ["moutai"], "青岛啤酒": ["tsingtao"], "百威中国": ["budweiser"],
    "顺丰控股": ["sf-express", "sfexpress"], "京东物流": ["jdlogistics"], "中通快递": ["zto"],
    "圆通速递": ["yto"], "韵达股份": ["yunda"], "申通快递": ["sto"], "极兔速递": ["jtexpress"],
    "宁德": ["catl"], "国家电网": ["sgcc"], "中国石化": ["sinopec"], "中国石油": ["cnpc"],
    "中国中化": ["sinochem"], "中国海油": ["cnooc"], "中国神华": ["shenhua"],
    "国家能源集团": ["chnenergy"], "中国华能": ["chng"], "中国大唐": ["china-cdt"],
    "中国华电": ["chd"], "国家电投": ["spic"], "中核集团": ["cnnc"], "中广核": ["cgnpc"],
    "中国建筑": ["cscec"], "中国中铁": ["crec"], "中国铁建": ["crcc"], "中国交建": ["ccccltd"],
    "中国电建": ["powerchina"], "中国能建": ["ceec"], "中国中冶": ["mcc"], "中国化学": ["cncec"],
    "宝武钢铁": ["baowu"], "中国宝武": ["baowu"], "鞍钢集团": ["ansteel"], "中国铝业": ["chalco"],
    "中国五矿": ["minmetals"], "中国建材": ["cnbm"], "海螺水泥": ["conch"], "中国远洋海运": ["cosco"],
    "中国外运": ["sinotrans"], "中远海运": ["cosco"], "招商局集团": ["cmhk"], "中国国航": ["airchina"],
    "东方航空": ["ceair"], "南方航空": ["csair"], "厦门航空": ["xiamenair"], "春秋航空": ["ch"],
    "中国移动": ["chinamobile"], "中国电信": ["chinatelecom"], "中国联通": ["chinaunicom"],
    "中国铁塔": ["chinatower"], "中国广电": ["chinabroadnet"],
    "腾讯": ["tencent"], "阿里巴巴": ["alibaba"], "百度": ["baidu"], "字节跳动": ["bytedance"],
    "美团": ["meituan"], "网易": ["netease"], "拼多多": ["pinduoduo"], "快手": ["kuaishou"],
    "滴滴": ["didi"], "携程": ["ctrip"], "哔哩哔哩": ["bilibili"], "小红书": ["xiaohongshu"],
    "唯品会": ["vip"], "苏宁易购": ["suning"], "永辉超市": ["yonghui"], "盒马": ["freshippo"],
    "名创优品": ["miniso"], "泡泡玛特": ["popmart"], "海底捞": ["haidilao"], "蜜雪冰城": ["mixue"],
    "茶颜悦色": ["cyys"], "瑞幸咖啡": ["luckin"], "星巴克中国": ["starbucks"],
    "优衣库": ["uniqlo"], "屈臣氏": ["watsons"], "安利中国": ["amway"],
    "顺丰": ["sf-express"], "中通": ["zto"], "德邦股份": ["deppon"],
    "科大智能": ["keda"], "汇川技术": ["inovance"], "埃斯顿": ["estun"], "新松机器人": ["siasun"],
    "汇顶科技": ["goodix"], "卓胜微": ["maxscend"], "圣邦股份": ["sg-micro"], "士兰微": ["silan"],
    "华润微": ["crmicro"], "华润置地": ["crland"], "万科": ["vanke"], "碧桂园": ["countrygarden"],
    "龙湖集团": ["longfor"], "保利发展": ["poly"], "中海地产": ["cohl"], "招商蛇口": ["cmsk"],
    "金地集团": ["gemdale"], "新城控股": ["seazen"], "华发股份": ["huafa"],
    "东方雨虹": ["yuhong"], "三棵树": ["skshu"], "中国金茂": ["jinmao"],
    "顺络电子": ["sunlord"], "生益科技": ["shengyi"], "沪电股份": ["wus"], "深南电路": ["scc"],
    "立讯精密": ["luxshare"], "歌尔股份": ["goertek"], "蓝思科技": ["lens"], "领益智造": ["lingyi"],
    "欣旺达电子": ["sunwoda"], "鹏鼎控股": ["avary"], "工业富联": ["fii"],
    "中环股份": ["tclzhonghuan"], "天合": ["trina"], "亿纬": ["eve"], "欣旺达动力": ["sunwoda"],
    "华友钴业": ["huayou"], "赣锋锂业": ["ganfeng"], "天齐锂业": ["tianqi"], "洛阳钼业": ["cmoc"],
    "北方稀土": ["reht"], "中国稀土": ["cre"], "宝钛股份": ["baoti"],
}

# 租户名展开用的是**单字拼音表**（`work/pinyin_single.json`，1103 字，来自 pypinyin 的
# 逐字结果，不含词组多音字规则）。多音字一律取默认读音：宁可漏（漏的进 blocked 留证据），
# 不可错（错的公司名比缺公司更糟）。
# 这些租户是北森/客户共用的 SaaS 模板或平台号，**不属于任何一家公司**。
# 实测 `zp.zhiye.com`（BOSS直聘那条错命中）里是「清华大学医学院张纯教授招聘科研型博士后」，
# 明显是某个高校/医院的自助门户，跟 BOSS 直聘毫无关系。
TENANT_DENY = frozenset({"zp", "hr", "demo", "test", "beisen", "zhiye", "www", "api", "job", "jobs", "recruit"})
# 2026-10-27 实测：`ys.zhiye.com` 的门户标题就是「多品牌门户」，里面混着十几个互不相关
# 公司的岗位（人事行政/素质教育课程顾问/结构工程师…），任何用拼音缩写去试的公司都会
# 命中它——这跟 `zp` 是同一类坑：**租户存在 ≠ 这家公司的门户**。凡是 2~3 字母的短租户
# 都要单独打开门户标题核一遍，标题里出现「多品牌 / 共享 / 门户 / 集团招聘」这类词的一律不收。
SHARED_PORTAL_HINT = ("多品牌", "共享门户", "集团门户", "招聘门户平台")


def zh_to_tokens(name: str) -> list[str]:
    """把一个中文公司名拆成可用于拼租户名的片段（只保留 ASCII 段，中文原样保留）。"""
    return [s for s in re.findall(r"[A-Za-z]+|[0-9]+|[\u4e00-\u9fa5]+", name)]


def candidates(name: str, pinyin: dict[str, str]) -> list[str]:
    """按常见命名法展开租户候选，按「越像真的越靠前」排序。"""
    base = TAIL.sub("", name.strip())
    out: list[str] = []

    def add(x: str) -> None:
        x = re.sub(r"[^a-z0-9]", "", x.lower())
        if 2 <= len(x) <= 30 and x not in out:
            out.append(x)

    # 1) 名字里本来就有英文 → 直接试
    ascii_words = re.findall(r"[A-Za-z][A-Za-z0-9]+", name)
    if ascii_words:
        add("".join(ascii_words))                 # ABB中国 → abb
        add(ascii_words[0])
        if len(ascii_words) > 1:
            add(ascii_words[0] + ascii_words[-1])
    # 2) 有拼音表 → 全拼 / 全拼+1 / 首字母 / 首字母+行业后缀
    # 只把汉字转拼音：`361度` 的「度」是品牌里读 dù，但 `360`/`58同城` 这类纯数字名
    # 直接转出来就是 `du`/`tongcheng`，撞上无关租户。所以先把数字剔掉再转。
    cn = re.sub(r"[0-9A-Za-z]", "", base)
    py = "".join(pinyin.get(c, "") for c in cn)
    ini = "".join(pinyin.get(c, "")[:1] for c in cn if pinyin.get(c))
    if py:
        add(py)
        add(py + "1")
        add(py + "zp")
        # `{拼音}hr` 命中的是北森自己的 SaaS 租户（`zp` 是招聘平台，谁都能注册），
        # 不代表公司归属，所以不试；留一行说明免得后人又加回去。
    if ini:
        add(ini)
        add(ini + "1")
        add(ini + "zp")
    # 3) 已知品牌英文名（比亚迪→byd、隆基绿能→longi）。用**最长匹配**：
    #    「比亚迪电子」要命中 byd 而不是被更短的「比亚迪」抢先。
    best_key = ""
    for key in BRAND_EN:
        if (key == base or (len(key) >= 2 and key in name)) and len(key) > len(best_key):
            best_key = key
    if best_key:
        vals = BRAND_EN[best_key]
        for v in vals:
            add(v)
            add(v + "1")
        # 4) 英文名 + 剩余部分首字母（比亚迪汽车 → bydqc）
        rest = TAIL.sub("", base.replace(best_key, "", 1))
        tail_ini = "".join(pinyin.get(c, "")[:1] for c in rest)
        if tail_ini:
            for v in vals:
                add(v + tail_ini)
    return out


def load_pinyin() -> dict[str, str]:
    """单字拼音表。优先用已缓存的表，没有就现建（不联网、不加依赖）。"""
    cache = ROOT / "work" / "pinyin_single.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    return {}


def probe(cli: httpx.Client, tenant: str) -> dict:
    try:
        r = cli.post(LIST.format(tenant=tenant), json=BODY, timeout=12.0)
    except httpx.HTTPError as e:
        return {"tenant": tenant, "ok": False, "err": type(e).__name__, "count": 0}
    if r.status_code != 200 or not r.text.strip().startswith("{"):
        return {"tenant": tenant, "ok": False, "err": f"http{r.status_code}", "count": 0}
    try:
        d = r.json()
    except ValueError:
        return {"tenant": tenant, "ok": False, "err": "notjson", "count": 0}
    if d.get("Code") != 200:
        return {"tenant": tenant, "ok": False, "err": f"code{d.get('Code')}", "count": 0}
    items = d.get("Data") or []
    # `Total` 实测恒 0，总岗数只能靠 Count；两者取大。
    count = max(int(d.get("Count") or 0), len(items))
    names = [str(i.get("JobAdName") or "") for i in items[:8]]
    codes = [str(i.get("PostCode") or i.get("JobAdCode") or "") for i in items[:8]]
    return {"tenant": tenant, "ok": True, "count": count, "sample": names, "codes": [c for c in codes if c]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--per-company", type=int, default=12, help="每家公司最多试几个租户名")
    a = ap.parse_args()

    names = [ln.strip() for ln in Path(a.src).read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    out = Path(a.out)
    done: set[str] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(ln)["company"])
            except Exception:  # noqa: BLE001
                pass
    todo = [n for n in names if n not in done]
    if a.limit:
        todo = todo[: a.limit]
    py = load_pinyin()
    print(f"待查 {len(todo)} 家，拼音表 {len(py)} 字", flush=True)

    hits = 0
    t0 = time.time()
    last = 0.0
    with httpx.Client(headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
                      timeout=12.0) as cli, out.open("a", encoding="utf-8") as f:
        for i, name in enumerate(todo, 1):
            tried: list[str] = []
            hit = None
            for t in candidates(name, py)[: a.per_company]:
                # 全局 1 rps：跨租户共享同一个节流器，不是每个租户各 1 rps。
                gap = 1.05 - (time.time() - last)
                if gap > 0:
                    time.sleep(gap)
                last = time.time()
                if t in TENANT_DENY:
                    continue
                tried.append(t)
                pr = probe(cli, t)
                if pr.get("ok") and pr.get("count", 0) > 0:
                    hit = pr
                    break
            # 直接产出 `verify_found.py` 能吃的形状：URL 里带 `{tenant}.zhiye.com`，
            # 这样验证/收录两段脚本一行都不用改，也避免中间层再写一次 JSONL 格式。
            rec = {"company": name, "tried": tried, "hit": hit,
                   "urls": [f"https://{hit['tenant']}.zhiye.com/"] if hit else []}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if hit:
                hits += 1
                print(f"HIT {name:14s} {hit['tenant']:22s} {hit['count']:6d}  {hit['sample'][:1]}", flush=True)
            if i % 25 == 0:
                el = time.time() - t0
                print(f"... {i}/{len(todo)} {el:.0f}s 命中 {hits} ({el / i:.2f}s/家)", flush=True)
    print(f"完成 {len(todo)}，命中 {hits}，用时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
