"""未覆盖目标 × 已有源公司名 的模糊比对：找「同一家但名字写法不同」的漏配。

不改变分母，只修正匹配——如果目标「华为技术有限公司」和源里的「华为」其实是
同一家，那是匹配器的问题，不是覆盖缺口。输出候选供人工确认，确认后才写别名。
"""

from __future__ import annotations

import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from jobradar.pipeline.calendar import match_targets, target_names  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402

CORE = re.compile(
    r"(?:股份有限公司|有限责任公司|有限公司|集团有限公司|集团|控股|中国|股份|总公司|公司|科技|技术|"
    r"（中国）|\(中国\)|中国区)$"
)
CITY = re.compile(r"^(北京|上海|天津|重庆|广州|深圳|杭州|南京|武汉|成都|西安|苏州|青岛|宁波|厦门|"
                  r"长沙|郑州|合肥|济南|福州|大连|沈阳|哈尔滨|昆明|南昌|贵阳|南宁|兰州|太原|石家庄|"
                  r"乌鲁木齐|呼和浩特|银川|西宁|拉萨|海口|长春)$")


def core(name: str) -> str:
    prev = None
    s = name.strip()
    while s != prev:
        prev = s
        s = CORE.sub("", s).strip()
    return s


def strip_city(name: str) -> str:
    m = CITY.match(name)
    return name[m.end():] if m else name


def main() -> None:
    targets = yaml.safe_load((ROOT / "targets" / "top_companies.yaml").read_text(encoding="utf-8"))
    sources = load_sources(ROOT / "sources")
    companies = {s.company for s in sources}
    matched = match_targets(targets, companies)
    uncovered = [n for n, _ in target_names(targets) if not matched.get(n)]

    src_core: dict[str, set[str]] = {}
    for c in companies:
        src_core.setdefault(core(c), set()).add(c)

    rows = []
    for name in uncovered:
        c = core(strip_city(name))
        cands = []
        for sc, originals in src_core.items():
            if not sc or not c:
                continue
            if sc == c or (len(c) >= 2 and (c in sc or sc in c)):
                cands.append((1.0, sc, sorted(originals)[0]))
                continue
            r = difflib.SequenceMatcher(None, c, sc).ratio()
            if r >= 0.85:
                cands.append((round(r, 3), sc, sorted(originals)[0]))
        if cands:
            cands.sort(reverse=True)
            rows.append({"target": name, "core": c, "cands": cands[:3]})

    out = ROOT / "work" / "_name_fuzzy.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"uncovered={len(uncovered)} fuzzy={len(rows)}"]
    for r in rows:
        lines.append(f"{r['target']}\t{r['core']}\t" + " | ".join(f"{s}({sc})" for s, sc, _ in r["cands"]))
    (ROOT / "work" / "_name_fuzzy.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:60]))


if __name__ == "__main__":
    main()
