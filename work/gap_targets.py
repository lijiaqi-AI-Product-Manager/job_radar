"""缺口定向发现：把 1974 家未覆盖公司按「它最可能用什么 ATS」分桶，而不是一律盲目猜拼音。

为什么换路子：2026-10-27 实测，1444 家全国缺口跑北森/大易/飞书三引擎拼音穷举，命中率 0.2%；
全省份缺口 158 家只中 1 家（还是共享门户误收）。**拼音穷举的召回已经到底**，
再跑同样的管道只会浪费请求。真正决定命中率的是「这家公司的招聘站由谁托管」：

  - 国有企业 / 央企      → 多用自建站或北森，且**名字里常带「集团/股份」**，slug 是短拼音
  - 民营制造业           → 大易自定义域名 `{slug}.hotjob.cn`（本轮 43 个候选里 6 个真命中）
  - 互联网 / 新消费       → 飞书 ATSX 或 Moka
  - 券商 / 银行           → 大易
  - 外企                 → Workday（但必须知道 Tenant+Site，猜不出来）

本脚本只做**分桶与排序**，不做请求：输出一份「先打谁」的清单，让下一轮的火力集中。
分桶依据是公司名 + 已在库的同行业样本，纯规则，不引入 LLM。

用法：
    python3 work/gap_targets.py                 # 打印四个桶的规模与前 20 家
    python3 work/gap_targets.py --out /tmp/x    # 每桶一个 txt，喂给对应探测器
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "work"))

from coverage_lib import db_companies, source_companies  # noqa: E402

# 名字后缀 → 组织类型。顺序有意义：先判「银行/证券/保险」，再判「集团/股份」。
RULES: list[tuple[str, tuple[str, ...]]] = [
    ("finance", ("银行", "证券", "保险", "基金", "信托", "期货", "资产", "理财", "人寿", "财险",
                 "农商", "农信", "信用社", "投控", "投资控股", "金控", "交易所")),
    ("internet", ("科技", "软件", "网络", "数据", "智能", "信息", "云", "数字", "电商", "传媒",
                  "游戏", "文化", "在线", "互联", "计算", "算法", "芯片", "半导体", "微电子")),
    ("foreign", ("中国区", "（中国）", "(中国)", "中国有限公司", "亚太")),
    ("soe", ("集团", "股份", "控股", "总公司", "局", "院", "所", "厂", "矿", "钢", "电力",
             "能源", "石化", "石油", "铁路", "航空", "港口", "建设", "建工", "交投", "城投")),
    ("consumer", ("食品", "饮料", "乳业", "酒", "餐饮", "咖啡", "茶", "服饰", "服装", "鞋",
                  "家居", "美妆", "日化", "超市", "零售", "商贸", "物流", "快递")),
]


def bucket(name: str) -> str:
    for key, words in RULES:
        if any(w in name for w in words):
            return key
    return "other"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/tmp/fc2/jobs.db")
    ap.add_argument("--out", default="")
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()

    tgt = yaml.safe_load((ROOT / "targets/mega_companies.yaml").read_text(encoding="utf-8")) or {}
    nat = list(dict.fromkeys(tgt.get("national") or []))
    covered = set(source_companies()) | db_companies(a.db)
    gap = [n for n in nat if n not in covered]

    groups: dict[str, list[str]] = {}
    for n in gap:
        groups.setdefault(bucket(n), []).append(n)

    print(f"目标 {len(nat)} 家，已覆盖 {len(set(nat) & covered)}，缺口 {len(gap)}")
    labels = {"finance": "金融（券商/银行/保险 → 大易 or 自建）",
              "internet": "科技互联网（飞书/Moka/自建）",
              "foreign": "外企中国（Workday/自建）",
              "soe": "国企央企（北森/自建，slug 常为短拼音）",
              "consumer": "消费零售（飞书/大易）",
              "other": "其它"}
    for k in ["soe", "finance", "internet", "consumer", "foreign", "other"]:
        names = groups.get(k) or []
        if not names:
            continue
        print(f"\n[{k}] {len(names):4d} 家 —— {labels[k]}")
        print("  " + "、".join(names[: a.top]))
        if a.out:
            p = Path(a.out)
            p.mkdir(parents=True, exist_ok=True)
            (p / f"gap_{k}.txt").write_text("\n".join(names), encoding="utf-8")
    if a.out:
        print(f"\n已写 {a.out}/gap_*.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
