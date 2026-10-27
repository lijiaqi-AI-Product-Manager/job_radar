"""日历条目的「具体公司/产品」字段回填。

为什么：十项口径里 `company`（具体公司/产品）只填了 90.8%，剩下 151 条是 `company: null`，
但同一个文件的 `group:` 明明白白写着「360集团」「58同城」「白云山」——不是缺数据，
是人工条目只填了集团没填公司。用户按公司筛的时候，这 151 条既筛不到集团也筛不到公司。

规则（只用文件里已有的信息，不新造）：
  - `company` 为空，且 `group` 本身就是一个具体公司/品牌名（不是「字节系」这种虚指）
    → 用 `group` 填上；
  - `group` 是虚指（「XX系」「XX集团旗下」）或为空 → 不动，留空让报告把它统计成缺口。

用法：
    python3 work/fill_company.py --apply
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ENTRIES = ROOT / "calendar" / "entries"
# 这些字样说明 group 是「系/族群」而不是一家公司，不能当公司名用
VAGUE = ("系", "旗下", "品牌", "等", "各", "相关")


def main() -> int:
    apply = "--apply" in sys.argv
    filled = 0
    files = 0
    for p in sorted(ENTRIES.glob("*.yaml")):
        text = p.read_text(encoding="utf-8")
        d = yaml.safe_load(text) or {}
        g = (d.get("group") or "").strip()
        if not g or any(v in g for v in VAGUE):
            continue
        rows = d.get("entries") or []
        need = [i for i, e in enumerate(rows) if not e.get("company")]
        if not need:
            continue
        files += 1
        filled += len(need)
        if not apply:
            print(f"{p.name}: {len(need)} 条 company←{g}")
            continue
        # 用 yaml 回写会丢注释，所以只做**行级**替换：把每条 entry 里第一个
        # `  company: null` 换成 `  company: <group>`。entry 以 `- id:` 开头，
        # 顺序稳定，不会串行。
        lines = text.splitlines()
        idx = 0
        for i, ln in enumerate(lines):
            if ln.strip() == "company: null":
                lines[i] = f"  company: {g}"
                idx += 1
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert idx >= len(need), f"{p.name}: 只替换了 {idx} 行，少于 {len(need)}"
    print(f"{'已写入' if apply else '将写入'} {files} 个文件、{filled} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
