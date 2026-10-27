"""把公司名变成北森 slug 候选，再去让 probe_beisen_tenants.py 校验。

为什么需要这一步：`blocked.jsonl` 里 835 条全是 `no_entry`——「北森/大易/旧版三套平台各
6-14 个 slug 组合均无命中」。但那个「6-14 个」是**人工凭感觉**敲的（`byd` / `byd1` /
`byd2` / `bydauto`…），既不可复现也不成体系，最要命的是**漏掉了大量本该命中的写法**：
拼音全拼（`biyadi`）、去掉行业词（`changanqiche` → `changan`）、英文品牌名（`nio` / `xpeng`）、
品牌+集团（`maotai` / `moutai`）。

本脚本只做「生成候选」，不联网。`--top` 控制每个公司给几个，配合 probe 的 1 req/s
可以精确控制抓取量。

用法：
    uv run python scripts/gen_slug_candidates.py --in blocked.jsonl --top 8 > /tmp/slugs.txt
    uv run python scripts/probe_beisen_tenants.py --file /tmp/slugs.txt
"""

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from pypinyin import Style, lazy_pinyin
except ImportError:  # 没装 pypinyin 时退化成「只出英文品牌名 + 手工表」
    Style = lazy_pinyin = None

# 行业后缀：租户 slug 里经常被省掉（`changanqiche` → `changan`）。
# 只放**确实是行业通用词**的，别把公司名本身吃掉。
INDUSTRY = ("集团", "股份", "控股", "科技", "技术", "汽车", "电子", "电器", "医药", "药业",
            "生物", "食品", "银行", "证券", "保险", "地产", "置业", "能源", "电力", "钢铁",
            "化工", "材料", "重工", "机械", "信息", "网络", "软件", "通信", "传媒", "教育",
            "医疗", "健康", "环保", "新材", "光电", "半导体", "微电子", "智能", "新能源",
            "有限公司", "有限责任公司", "公司")


def slugify(name: str) -> str:
    """只留 a-z0-9，其余全去掉。北森 slug 全部小写无分隔（实测 400 个租户无一例外）。"""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def pinyin(name: str, style="full") -> str:
    if lazy_pinyin is None:
        return ""
    han = "".join(ch for ch in name if "\u4e00" <= ch <= "\u9fff")
    if not han:
        return ""
    if style == "full":
        return slugify("".join(lazy_pinyin(han)))
    return slugify("".join(lazy_pinyin(han, style=Style.FIRST_LETTER)))


def candidates(name: str, brand: str | None, top: int) -> list[str]:
    """按「命中概率从高到低」返回候选，去重、去空、去太短的。"""
    out: list[str] = []

    def add(*vals: str) -> None:
        for v in vals:
            v = slugify(v or "")
            if 2 < len(v) <= 30 and v not in out:
                out.append(v)

    # ① 英文品牌名最优先：外企/新势力/A股英文简称的租户基本就是品牌名
    add(brand)
    # ② 中文名全拼；再去掉行业后缀来一次（长安汽车 → changan）
    full = pinyin(name)
    add(full)
    stripped = name
    for w in INDUSTRY:
        stripped = stripped.replace(w, "")
    if stripped and stripped != name:
        add(pinyin(stripped))
    # ③ 首字母缩写（中金公司 → zjgs；用得少但有的租户就是缩写）
    add(pinyin(name, "first"))
    # ④ 品牌名去空格/连字符的紧凑写法（`SAIC Motor` → `saicmotor`）
    if brand:
        add(brand.replace(" ", "").replace("-", ""))
    return out[:top]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="blocked.jsonl")
    ap.add_argument("--top", type=int, default=8, help="每家公司最多给几个候选")
    ap.add_argument("--out", help="写到文件（默认 stdout，一行一个 slug）")
    ap.add_argument("--map", help="同时写 slug->公司名 的映射 JSON，probe 命中后填 company 用")
    args = ap.parse_args()

    rows = [json.loads(ln) for ln in Path(args.src).read_text(encoding="utf-8").splitlines() if ln.strip()]
    seen: set[str] = set()
    slugs: list[str] = []
    mapping: dict[str, str] = {}
    for r in rows:
        # 已经 all-good 的公司名（`blocked.jsonl` 的 company 字段是标准中文名）
        for s in candidates(r.get("company", ""), r.get("brand"), args.top):
            if s in mapping:
                continue
            mapping[s] = r.get("company", "")
            if s not in seen:
                seen.add(s)
                slugs.append(s)

    text = "\n".join(slugs) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"{len(slugs)} 个候选 -> {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    if args.map:
        Path(args.map).write_text(json.dumps(mapping, ensure_ascii=False, indent=0), encoding="utf-8")
        print(f"{len(mapping)} 条映射 -> {args.map}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
