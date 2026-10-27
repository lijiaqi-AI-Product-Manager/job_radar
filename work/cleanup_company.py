"""收录前的公司名清洗：去掉「XX集团/XX股份/XX有限公司」这类后缀，并与已有源名归一。

为什么单独一步：YAML 里的 `company` 是用户「按公司筛」的键，`通用技术集团` 和 `通用技术`
会被当成两家。归一规则只用**确定性字符串规则 + 显式别名表**，不做任何模糊匹配：

  1. 去括号注释：`中化集团（中国中化）` → `中化集团`
  2. 去尾部冗余后缀（按长度从长到短，避免先删「公司」留下「有限」）：有限公司/股份/集团/控股…
  3. 若 `sources/` 里已存在同名前缀的规范名，用已有名（`中国中化` 已在库里 → 沿用它）

改名只影响 `company` 字段，不动 `id`。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

# 顺序重要：长后缀先删
SUFFIX = ("股份有限公司", "有限责任公司", "有限公司", "集团股份", "股份", "控股", "集团",
          "总公司", "公司", "企业", "中国区")

# 只对「明显是同一实体」的写法做归一；不确定的不动
FORCE = {
    "中国汽研": "中国汽研",
    "通用技术": "通用技术",
    "中化": "中国中化",
    "中国中化": "中国中化",
    "士兰微": "士兰微",
    "中汇": "中汇",
    "隆基": "隆基绿能",
    "金龙鱼": "金龙鱼",
}


def known_companies() -> set[str]:
    out: set[str] = set()
    for p in (ROOT / "sources").glob("*.yaml"):
        if p.name == "_example.yaml":
            continue
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for s in (d.get("sources") or ([d] if d.get("id") else [])):
            if s.get("company"):
                out.add(s["company"])
    tgt = yaml.safe_load((ROOT / "targets/top_companies.yaml").read_text(encoding="utf-8")) or {}
    for v in (tgt.get("sectors") or {}).values():
        out.update(v)
    return out


def short(name: str) -> str:
    """去掉括号注释和尾部企业后缀。"""
    n = re.sub(r"[（(][^）)]{0,20}[）)]", "", name).strip()
    changed = True
    while changed:
        changed = False
        for s in SUFFIX:
            if n.endswith(s) and len(n) - len(s) >= 2:
                n = n[: -len(s)]
                changed = True
    return n


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/exp/to_add.json")
    dst = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/exp/to_add2.json")
    data = json.loads(src.read_text(encoding="utf-8"))
    known = known_companies()

    def fix(name: str) -> str:
        if name in FORCE:
            return FORCE[name]
        s = short(name)
        if name in known:
            return name
        if s in known:
            return s
        return s or name

    for key in ("beisen", "hotjob"):
        for r in data[key]:
            old = r["company"]
            # id 用公司名尾段拼，避免 hotjob 租户后 8 位撞车（SU612f55…/SU612f5c… 只差 2 位）
            r["id"] = (f"beisen-{r['tenant']}" if key == "beisen"
                       else f"hotjob-{r['tenant'][-6:].lower()}")
            new = fix(old)
            if new != old:
                r["renamed_from"] = old
            r["company"] = new
    dst.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print("重命名：")
    for key in ("beisen", "hotjob"):
        for r in data[key]:
            if r.get("renamed_from"):
                print(f"  {r['renamed_from']} -> {r['company']}")
    print(f"beisen {len(data['beisen'])} hotjob {len(data['hotjob'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
