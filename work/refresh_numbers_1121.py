"""1.12.1：把口径刷到「云就业补采后」的实测值。

906→917 覆盖、2,218→2,229 源、2,177→2,188 公司、聚合 300→311、yunjiuye 94→105。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PAIRS = [
    ("version-1.12.0-blue", "version-1.12.1-blue"),
    ("2,218", "2,229"),
    ("2,177", "2,188"),
    ("**906/1,655（55%）**", "**917/1,655（55%）**"),
    ("**906/1,655 (55%)**", "**917/1,655 (55%)**"),
    ("**906 covered (55%)**", "**917 covered (55%)**"),
    ("906 社（55%）", "917 社（55%）"),
    ("**906 家（55%）**", "**917 家（55%）**"),
    ("906 家已建源", "917 家已建源"),
    ("其余 737 家", "其余 726 家"),
    ("917 of the 1,655 targets", "917 of the 1,655 targets"),
    ("the other 737", "the other 726"),
    # 聚合渠道 300 → 311
    ("聚合渠道 **300 家（18%）**", "聚合渠道 **311 家（19%）**"),
    ("300 家（18%）", "311 家（19%）"),
    ("300 (18%)", "311 (19%)"),
    ("300 社（18%）", "311 社（19%）"),
    ("300 empresas (18%)", "311 empresas (19%)"),
    ("300 entreprises (18%)", "311 entreprises (19%)"),
    ("300 компаний (18%)", "311 компаний (19%)"),
    ("300개(18%)", "311개(19%)"),
    # 云就业源数
    ("云就业 94", "云就业 105"),
]


def main() -> int:
    total = 0
    for path in sorted(ROOT.glob("README*.md")):
        text = path.read_text(encoding="utf-8")
        before = text
        n = 0
        for old, new in PAIRS:
            if old in text:
                n += text.count(old)
                text = text.replace(old, new)
        if text != before:
            path.write_text(text, encoding="utf-8")
        total += n
        print(f"{path.name}: {n} 处")
    print("total", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
