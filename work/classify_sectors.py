#!/usr/bin/env python3
"""给「扩展池（实测确认）」里没有行业标注的公司补行业。

策略：按公司名里的强特征词判，判不出的列出来人工/联网核，绝不硬塞。
输出的映射写回 targets/top_companies.yaml 的 sectors，并把该公司从扩展池里摘掉。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
POOL_KEY = "扩展池（实测确认）"

# 顺序有意义：先判更强的特征（「汽车金融」优先判汽车，不是金融）。
# 每条是 (行业, 正则)。正则只匹配公司名，不匹配正文，所以可以写得很具体。
RULES: list[tuple[str, str]] = [
    # —— 金融（放在前面：银行/证券/保险/基金的名字里常有「中国」「国际」等泛词）
    ("银行", r"银行|农商|信用社|农信|村镇银行"),
    ("保险", r"保险|人寿|财险|寿险|再保险|保险资产"),
    ("证券基金与资管", r"证券|基金|资管|资产管理|期货|信托|投资管理|理财|投顾|私募|公募"),
    # —— 医药医疗（放在消费前：「大药房」是医药零售）
    # 「生物」不能裸用：「丸美生物技术」是化妆品、「巨子生物」是医美，后缀「生物技术」
    # 在国内公司名里几乎等于「高科技」，判不出行业。只认明确医药形态。
    # （需要「生物」时按「生物医药」「生物制药」「生物制品」这类组合判）
    ("医药医疗", r"药|制药|医药|医科|医疗|医院|基因|疫苗|诊断|器械|医学|口腔|眼科|牙科|"
                 r"血液制品|生物医药|生物制药|生物制品|生物工程|生物疫苗|血制品"),
    # —— 教育
    ("教育", r"教育|学校|学院|幼儿园|网校|学堂|培训|留学|考研|公考|职教"),
    # —— 半导体（先于电子硬件：「芯片」「晶圆」是半导体）
    ("半导体", r"半导体|芯片|晶圆|集成电路|微电子|光刻|封测|硅片|存储器|IC设计|射频"),
    # —— 汽车与出行（先于制造：「汽车」「整车」）
    ("汽车与出行", r"汽车|整车|车联|轮胎|零部件|出行|物流车|新能源车|商用车|乘用车|"
                   r"航空|机场|航运|港口|船|铁路|轨道|地铁|速递|快递|货运|物流"),
    # —— 新能源与先进制造
    ("新能源与先进制造", r"新能源|光伏|锂|储能|风电|风能|氢能|电池|能源|电力|核电|"
                         r"钢铁|冶金|铝业|铜业|钼业|矿业|水泥|建材|化工|化学|材料|"
                         r"机械|重工|装备|电气|电机|电缆|变压器|股份有限.*制造"),
    # —— 通信与电子硬件
    ("通信与电子硬件", r"通信|电子|光电|显示|面板|声学|传感器|连接器|网络设备|"
                       r"手机|电脑|消费电子|家电|空调|冰箱|电视"),
    # —— 人工智能与机器人（「智能」太泛：明阳智能是风电、志高空调是家电，
    #     所以这里只认强特征词，不认裸「智能」。「AI」必须带词边界，
    #     否则 NEIWAI（内外内衣）会因为结尾的 AI 被判成人工智能）
    ("人工智能与机器人", r"人工智能|机器人|自动驾驶|大模型|机器视觉|计算机视觉|"
                         r"语音识别|(?<![A-Za-z])AI(?![A-Za-z])|算法"),
    # —— 互联网与软件（「科技」太泛：中材科技是建材、中天科技是电缆，
    #     所以不再用裸「科技」和裸「网络」，只认明确的互联网/软件特征）
    ("互联网与软件", r"互联网|软件|信息技术|数据|云计算|数字|电子商务|电商|在线|"
                     r"游戏|传媒|文化|视频|音乐|阅读|社区|平台|网络科技|信息科技"),
    # —— 企业服务（「招聘」「办公」这类词在招聘页标题里到处都是，
    #     绝不能拿裸词判行业，只认明确的企业服务形态）
    ("企业服务", r"企业服务|人力资源服务|财税服务|法务服务|SaaS|管理咨询|外包服务|猎头"),
    # —— 咨询会计与专业服务
    ("咨询会计与专业服务", r"会计师|会计事务所|律所|律师|评估|审计|认证|检测|设计院|研究院"),
    # —— 消费零售与食品
    ("消费零售与食品", r"食品|饮料|乳业|酒业|啤酒|白酒|餐饮|零售|超市|百货|商超|"
                       r"零食|茶|咖啡|水|农牧|饲料|种业|农业|渔业|肉|粮油|调味"),
    # —— 央企与国企（名字里直接带国字头；必须放在具体行业之后判，
    #     否则「中国黄金集团」会被「黄金」抢走判成美妆）
    ("央企与国企", r"中国.*集团|中[国央].*控股|国家.*集团|国网|中铁|中交|中建|中冶|中化|中粮|中远"),
    # —— 美妆与服饰
    ("美妆与服饰", r"美妆|化妆|护肤|日化|个人护理|服饰|服装|纺织|珠宝|钟表|眼镜|箱包"),
    # —— 地产建筑与物流（「工程」太泛：生物工程、化学工程、软件工程都会命中，
    #     只认「建设工程」「建筑工程」这类明确的建筑形态）
    ("地产建筑与物流", r"地产|置业|房地产|建筑|建设工程|建筑工程|工程建设|装饰|物业|"
                       r"家居|仓储|供应链"),
    # —— 央企与国企（名字里直接带「集团」「控股」且带国字头）
    ("央企与国企", r"中国.*集团|中[国央].*控股|国家.*集团|国网|中铁|中交|中建|中冶|中化|中粮|中远"),
    # —— 外资在华
    ("外资在华", r"\(中国\)|（中国）|中国区|亚太"),
]


# 招聘页标题里的招聘用语：每一篇公告都带，不能当行业特征。
# 注意只剥「招聘行为」相关的词，保留「科技」「网络」「电子」这些真正的行业语素。
GENERIC = re.compile(
    r"校园招聘|社会招聘|招聘|校招|社招|秋招|春招|实习|公告|简章|启动|正式|"
    r"人才|职位|岗位|欢迎|加入")


def strip_generic(text: str) -> str:
    """去掉页面信号里的通用词，只留可能有行业含义的部分。"""
    return GENERIC.sub(" ", text or "")


def classify(name: str) -> str | None:
    for sector, pat in RULES:
        if re.search(pat, name):
            return sector
    return None


def load_signals() -> dict[str, str]:
    """公司 -> 附加文本信号（招聘页标题 + 岗位名 + URL 主体）。

    很多公司的名字本身不带行业词（「阿维塔」「海能达」「ACCOTEST」），
    但它们的招聘页标题是全称（「海能达通信股份有限公司」），足以判行业。
    这比联网逐家查快得多，也不引入猜测——用的是已经抓到的真实页面标题。

    **一致性校验**：只收「页面标题里含该公司名前 2 字」的信号。
    实测有抓到 URL 张冠李戴的情况（「上海家化六神」的入口指向某律所），
    不过滤就会按别人的行业分类。
    """
    import json

    sig: dict[str, list[str]] = {}
    p = ROOT / "companies.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            name = r.get("company")
            if not name:
                continue
            title = r.get("evidence", {}).get("page_title") or ""
            key = name[:2]
            if key and key not in title and name not in title:
                continue  # 页面标题跟公司名对不上，信号不可信
            parts = [title]
            parts += r.get("evidence", {}).get("sample_jobs") or []
            parts.append(r.get("host") or "")
            sig.setdefault(name, []).extend(p for p in parts if p)
    return {k: " ".join(v) for k, v in sig.items()}


def classify_with_signal(name: str, signal: str = "") -> tuple[str | None, str]:
    """先按公司名判（信号强），判不出再按页面标题/岗位名判。

    返回 (行业, 依据)。依据用于人工复核时追溯。
    """
    s = classify(name)
    if s:
        return s, "name"
    if signal:
        s = classify(strip_generic(signal))
        if s:
            return s, "signal"
    return None, ""


def main() -> int:
    apply = "--apply" in sys.argv
    p = ROOT / "targets" / "top_companies.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    pool = list(doc["sectors"].get(POOL_KEY) or [])

    real = set()
    for s, names in doc["sectors"].items():
        if s != POOL_KEY:
            real.update(names or [])

    need = [n for n in pool if n not in real]
    sig = load_signals()
    hit, miss = {}, []
    by_name = by_signal = by_manual = 0
    try:
        from sector_manual import MANUAL
    except ImportError:
        MANUAL = {}
    for n in need:
        if n in MANUAL:
            hit.setdefault(MANUAL[n][0], []).append(n)
            by_manual += 1
            continue
        s, how = classify_with_signal(n, sig.get(n, ""))
        if s:
            hit.setdefault(s, []).append(n)
            if how == "name":
                by_name += 1
            else:
                by_signal += 1
        else:
            miss.append(n)

    print(f"待分类 {len(need)}｜判出 {by_name + by_signal + by_manual}"
          f"（公司名 {by_name} / 页面信号 {by_signal} / 人工核对 {by_manual}）｜判不出 {len(miss)}")
    for s, names in sorted(hit.items(), key=lambda x: -len(x[1])):
        print(f"  {s:16s} {len(names):4d}  {'、'.join(names[:6])}")
    print(f"\n判不出（需联网/人工核）：{len(miss)} 家")
    print("、".join(miss[:40]))

    if apply:
        for s, names in hit.items():
            doc["sectors"].setdefault(s, [])
            for n in names:
                if n not in doc["sectors"][s]:
                    doc["sectors"][s].append(n)
        left = [n for n in pool if n not in {x for names in hit.values() for x in names}]
        doc["sectors"][POOL_KEY] = left
        # 保持 YAML 可读：手写而不是 dump（原文件是人工排版的）
        text = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=1000)
        p.write_text(text, encoding="utf-8")
        print(f"\n已写入：扩展池剩 {len(left)} 家")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
