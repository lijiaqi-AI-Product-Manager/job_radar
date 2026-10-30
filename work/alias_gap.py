"""诊断：有多少「已有源但没算进覆盖」是因为公司名写法不同（别名/后缀/地名前缀）。

不写数据，只输出候选对照表 work/_alias_gap.txt，人工核对后才改 targets 的 aliases。
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from jobradar.pipeline.calendar import match_targets, target_names  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

SUFFIX = re.compile(r"(?:股份有限公司|有限责任公司|有限公司|集团有限公司|集团|控股|中国|股份|总公司|公司)$")
CITY = re.compile(r"^(?:中国|北京|上海|天津|重庆|广州|深圳|杭州|南京|苏州|武汉|成都|西安|青岛|大连|厦门|宁波|长沙|郑州|合肥|济南|福州|昆明|南昌|贵阳|太原|石家庄|沈阳|长春|哈尔滨|兰州|银川|西宁|乌鲁木齐|呼和浩特|南宁|海口|拉萨|香港)")


def core(name: str) -> str:
    s = re.sub(r"[\s\u3000（）()]+", "", str(name))
    return SUFFIX.sub("", s)


def strip_city(name: str) -> str:
    return CITY.sub("", core(name))


def main() -> None:
    targets = yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8"))
    sources = load_sources(ROOT / "sources")
    companies = {s.company for s in sources}
    matched = match_targets(targets, companies)

    names = [n for n, _ in target_names(targets)]

    uncovered = [n for n in names if not matched.get(n)]
    by_core: dict[str, set[str]] = {}
    for c in companies:
        by_core.setdefault(core(c), set()).add(c)
        by_core.setdefault(strip_city(c), set()).add(c)

    lines = [f"targets={len(names)} covered={len(names)-len(uncovered)} uncovered={len(uncovered)}", ""]
    hits = 0
    for n in uncovered:
        cands = set()
        for key in (core(n), strip_city(n)):
            if len(key) >= 3:
                for c in companies:
                    if core(c) == key or strip_city(c) == key:
                        cands.add(c)
        if cands:
            hits += 1
            lines.append(f"{n}\t=>\t{', '.join(sorted(cands)[:4])}")
    lines.insert(1, f"别名可直接对上的未覆盖目标: {hits}")
    (ROOT / "work" / "_alias_gap.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"uncovered={len(uncovered)} alias_hits={hits}")


if __name__ == "__main__":
    main()
