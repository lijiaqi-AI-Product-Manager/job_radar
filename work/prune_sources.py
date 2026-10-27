"""按 source id 从 sources/*.yaml 里删条目（保留注释与其余内容）。

同名公司挂了两个同岗位门户时（比如潍柴的 weichai / weichaidongli 实测 100% 重合），
用这个脚本删掉多余的那条，避免日报重复抓取。用法：

    python work/prune_sources.py beisen-weichaidongli beisen-campuske
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

COMPACT = re.compile(r"^\s*-\s*\{id:\s*(?P<id>[A-Za-z0-9_-]+)")
BLOCK = re.compile(r"^(?P<indent>\s*)-\s+id:\s*(?P<id>[A-Za-z0-9_-]+)\s*$")


def prune(path: Path, ids: set[str]) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    removed: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = COMPACT.match(line)
        if m and m.group("id") in ids:
            removed.append(m.group("id"))
            i += 1
            continue
        m = BLOCK.match(line)
        if m and m.group("id") in ids:
            removed.append(m.group("id"))
            base = len(m.group("indent"))
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip():
                    i += 1
                    continue
                indent = len(nxt) - len(nxt.lstrip())
                if indent <= base and nxt.lstrip().startswith("- "):
                    break
                if indent <= base and not nxt.startswith(" " * (base + 1)):
                    break
                i += 1
            continue
        out.append(line)
        i += 1
    if removed:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return removed


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    ids = set(argv)
    total: list[str] = []
    for path in sorted((ROOT / "sources").glob("*.yaml")):
        removed = prune(path, ids)
        if removed:
            print(f"{path.name}: 删除 {', '.join(removed)}")
            total += removed
    missing = ids - set(total)
    if missing:
        print(f"没找到：{', '.join(sorted(missing))}")
        return 1

    sys.path.insert(0, str(ROOT / "src"))
    from jobradar.sources import load_sources

    sources = load_sources(ROOT / "sources")
    print(f"删除 {len(total)} 条，剩余 {len(sources)} 源 / {len({s.company for s in sources})} 公司")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
