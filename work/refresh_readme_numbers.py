"""把 8 个 README 的口径数字统一刷新到 2026-10-30 实测值。

替换只针对本次真的变了的数字，逐条统计命中次数，便于核对有没有漏改或误改。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = sorted(ROOT.glob("README*.md"))

PAIRS: list[tuple[str, str]] = [
    # 版本徽章
    ("version-1.10.0-blue", "version-1.11.0-blue"),
    # 规模
    ("1,911", "2,124"),
    ("1,870", "2,083"),
    # 23 -> 25 个适配器（中/英/日/德/西/法/俄/韩各自的写法）
    ("**23 adapters**", "**25 adapters**"),
    ("**23 个适配器**", "**25 个适配器**"),
    ("**23 アダプタ**", "**25 アダプタ**"),
    ("23 Adapter", "25 Adapter"),
    ("23 adaptadores", "25 adaptadores"),
    ("23 adaptateurs", "25 adaptateurs"),
    ("23 адаптера", "25 адаптера"),
    ("23 어댑터", "25 어댑터"),
    # 覆盖率
    ("**606/1,655（37%）**", "**814/1,655（49%）**"),
    ("**606/1,655 (37%)**", "**814/1,655 (49%)**"),
    ("**606 covered (37%)**", "**814 covered (49%)**"),
    ("606 社（37%）", "814 社（49%）"),
    ("**606 家（37%）**", "**814 家（49%）**"),
    ("**606 社（37%）**", "**814 社（49%）**"),
    # 待侦察家数
    ("579 家已建源", "814 家已建源"),
    ("其余 1,064 家", "其余 841 家"),
    ("577 of the 1,655 targets", "814 of the 1,655 targets"),
    ("the other 1,078", "the other 841"),
    # 分省
    ("18/49（37%）", "34/49（69%）"),
    ("13/44（30%）", "21/44（48%）"),
    ("9/34（26%）", "14/34（41%）"),
    ("9/30（30%）", "13/30（43%）"),
    ("7/26（27%）", "14/26（54%）"),
    ("18/49 (37%)", "34/49 (69%)"),
    ("13/44 (30%)", "21/44 (48%)"),
    ("9/34 (26%)", "14/34 (41%)"),
    ("9/30 (30%)", "13/30 (43%)"),
    ("7/26 (27%)", "14/26 (54%)"),
    ("広東 18/49（37%）", "広東 34/49（69%）"),
    ("浙江 13/44（30%）", "浙江 21/44（48%）"),
    ("江蘇 9/34（26%）", "江蘇 14/34（41%）"),
    ("四川 9/30（30%）", "四川 13/30（43%）"),
    ("山東 7/26（27%）", "山東 14/26（54%）"),
]


def main() -> int:
    total = {}
    for path in FILES:
        text = path.read_text(encoding="utf-8")
        before = text
        hits = {}
        for old, new in PAIRS:
            n = text.count(old)
            if n:
                text = text.replace(old, new)
                hits[old] = n
        if text != before:
            path.write_text(text, encoding="utf-8")
        total[path.name] = hits
    for name, hits in total.items():
        changed = ", ".join(f"{k}×{v}" for k, v in hits.items()) or "-"
        print(f"{name}: {changed}")
    # 剩下的可疑数字
    for path in FILES:
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"(1,911|1,870|\b606\b)", text):
            line = text[: m.start()].count("\n") + 1
            print(f"  ! {path.name}:{line} 残留 {m.group(1)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
