"""合并 targets 里的「同一主体两种写法」。

为什么必须修：`ABB` 与 `ABB中国`、`宝洁` 与 `宝洁中国`、`微软` 与 `微软中国` 这类重复
会让同一家公司在发布物里出现两次——
  - `stats` 的 targets 分母虚高（1021 里至少有 10 对是同一主体）；
  - 日历被拆成两个 group，用户在「ABB」下只看到半条；
  - 两个写法还经常分到不同行业（ABB→外资在华 / ABB中国→新能源与先进制造），
    行业分布统计直接失真。

合并规则（保守，可人工复核）：
  1. 只有「候选核心名完全相同」才考虑合并，不做模糊匹配；
  2. 必须一方是另一方的**严格前缀且只多了「中国」**（或反过来），
     即 X / X中国、X / 中国X 这种纯修饰差异；
  3. 保留**行业标注更具体、且不在扩展池里**的那一个作为主名，另一个写入 aliases，
     让 `match_targets` 仍能把两个写法都归到同一集团；
  4. 扩展池里的一方合并进主表后从扩展池移除（它已经算覆盖了）。

用法：python3 work/merge_duplicate_targets.py [--apply]
"""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ROOT / "targets/top_companies.yaml"

# 「中国」「（中国）」是同一主体的区域后缀，不是不同公司
DECOR = ("（中国）", "(中国)", "中国")


def base(n: str) -> str:
    for d in DECOR:
        if n.endswith(d) and len(n) > len(d):
            return n[: -len(d)]
        if n.startswith(d) and len(n) > len(d):
            return n[len(d):]
    return n


def main() -> int:
    apply = "--apply" in sys.argv
    doc = yaml.safe_load(TARGETS.read_text(encoding="utf-8"))
    sectors: dict[str, list[str]] = doc["sectors"]
    aliases: dict[str, list[str]] = doc.get("aliases") or {}

    # name -> sector（同一名字只出现一次，前面已验证 1021 唯一）
    where = {n: s for s, ns in sectors.items() for n in (ns or [])}
    by_base: dict[str, list[str]] = {}
    for n in where:
        by_base.setdefault(base(n), []).append(n)

    merges: list[tuple[str, str]] = []   # (保留, 合并掉)
    for core, group in by_base.items():
        if len(group) < 2 or not core:
            continue
        # 只处理两两之间是「纯中国后缀」关系的情况
        kept = group[0]
        for other in group[1:]:
            if base(other) != base(kept):
                continue
            # 选主名，优先级（高→低）：
            #   1. 不在扩展池里（扩展池是「采集时发现的额外租户」，不是人工选定名单）；
            #   2. 带「中国」后缀的（在华招聘的主体是「微软中国」，不是母公司「微软」）；
            #   3. 行业标注更具体（非「外资在华」这种泛分类）。
            # 只按长度会选成「ABB」，而 ABB 那一条其实是外资泛称，行业标注也更粗。
            def score(n: str) -> tuple[int, int, int]:
                is_pool = "扩展池" in where.get(n, "")
                has_cn = 1 if n != base(n) else 0
                generic = 1 if where.get(n) in ("外资在华",) else 0
                return (0 if is_pool else 1, has_cn, -generic)
            a, b = sorted([kept, other], key=score, reverse=True)
            merges.append((a, b))
            kept = a

    print(f"待合并 {len(merges)} 对：")
    for a, b in merges:
        print(f"  {b:<14}({where[b]})  ->  {a}({where[a]})")

    if not apply:
        print("（dry-run，加 --apply 才写回）")
        return 0

    for a, b in merges:
        s_b = where[b]
        if s_b in sectors and b in (sectors[s_b] or []):
            sectors[s_b] = [x for x in sectors[s_b] if x != b]
            if not sectors[s_b]:
                del sectors[s_b]
        aliases.setdefault(a, [])
        if b not in aliases[a]:
            aliases[a].append(b)
        # 原有 aliases 指向被合并名的，改指向主名
        for k, vs in list(aliases.items()):
            if k == b:
                for v in vs:
                    if v not in aliases[a]:
                        aliases[a].append(v)
                del aliases[k]
            elif k != a and b in vs:
                vs.remove(b)
                if a not in vs:
                    vs.append(a)

    doc["sectors"] = sectors
    doc["aliases"] = aliases
    header = TARGETS.read_text(encoding="utf-8").split("sectors:")[0]
    body = yaml.safe_dump({"sectors": sectors, "aliases": aliases, **{
        k: v for k, v in doc.items() if k not in ("sectors", "aliases")}},
        allow_unicode=True, sort_keys=False, width=1000)
    TARGETS.write_text(header + body, encoding="utf-8")
    total = sum(len(v or []) for v in sectors.values())
    print(f"写回完成：{total} 家 / {len(sectors)} 个行业；aliases {sum(len(v) for v in aliases.values())} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
