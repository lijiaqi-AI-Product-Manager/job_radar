"""把 8 个 README 的统计口径刷到 2026-10-30 云就业落库后的实测值。

zh：2,218 源 / 2,177 公司 / 26 适配器 / 覆盖 906（55%），官方 606（37%）+ 聚合 300（18%）
    行业池 391/983（40%）、365 行有覆盖 268（73%）、两池 1,003/2,224（45%）
    分省：广东 35/49（71%）、浙江 24/44（55%）、江苏 15/34（44%）、四川 14/30（47%）、山东 15/26（58%）
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

COMMON = [
    ("2,124", "2,218"),
    ("2.124", "2.218"),
    ("2,083", "2,177"),
    ("2.083", "2.177"),
    # 版本徽章
    ("version-1.11.0-blue", "version-1.12.0-blue"),
    # 聚合/官方
    ("814", "906"),
    ("49%", "55%"),
    ("49 %", "55 %"),
    ("49 %)", "55 %)"),
    ("208 家（13%）", "300 家（18%）"),
    ("208 (13%)", "300 (18%)"),
    ("208 社（13%）", "300 社（18%）"),
    ("208 empresas (13%)", "300 empresas (18%)"),
    ("208 entreprises (13%)", "300 entreprises (18%)"),
    ("208 компаний (13%)", "300 компаний (18%)"),
    ("208개(13%)", "300개(18%)"),
    # 适配器
    ("25 个适配器", "26 个适配器"),
    ("25 adapters", "26 adapters"),
    ("25 アダプタ", "26 アダプタ"),
    ("25 Adapter", "26 Adapter"),
    ("25 adaptadores", "26 adaptadores"),
    ("25 adaptateurs", "26 adaptateurs"),
    ("25 адаптера", "26 адаптера"),
    ("25개 어댑터", "26개 어댑터"),
    # 行业池
    ("360 家有源（37%）", "391 家有源（40%）"),
    ("262 行有覆盖（72%）", "268 行有覆盖（73%）"),
    ("909 家有源（41%）", "1,003 家有源（45%）"),
    # 分省（中文全角括号）
    ("34/49（69%）", "35/49（71%）"),
    ("21/44（48%）", "24/44（55%）"),
    ("14/34（41%）", "15/34（44%）"),
    ("13/30（43%）", "14/30（47%）"),
    ("14/26（54%）", "15/26（58%）"),
    # 分省（英文半角）
    ("34/49 (69%)", "35/49 (71%)"),
    ("21/44 (48%)", "24/44 (55%)"),
    ("14/34 (41%)", "15/34 (44%)"),
    ("13/30 (43%)", "14/30 (47%)"),
    ("14/26 (54%)", "15/26 (58%)"),
    ("広東 34/49（69%）", "広東 35/49（71%）"),
    ("浙江 21/44（48%）", "浙江 24/44（55%）"),
    ("江蘇 14/34（41%）", "江蘇 15/34（44%）"),
    ("四川 13/30（43%）", "四川 14/30（47%）"),
    ("山東 14/26（54%）", "山東 15/26（58%）"),
    # 待侦察
    ("814 家已建源", "906 家已建源"),
    ("其余 841 家", "其余 737 家"),
    ("814 of the 1,655 targets", "906 of the 1,655 targets"),
    ("the other 841", "the other 737"),
]

# 云就业渠道加进平台明细（各语言）
EXTRA = {
    "README.md": ("实习僧 104 / 其余平台与自研站", "实习僧 104 / 云就业 94 / 其余平台与自研站"),
    "README.en.md": ("Dayee 310 / Feishu ATSX 148 / Tupu360 32 / Workday 45 / others",
                     "Dayee 310 / Feishu ATSX 148 / Tupu360 32 / Workday 45 / 94 yun-campus / others"),
}


def main() -> int:
    for path in sorted(ROOT.glob("README*.md")):
        text = path.read_text(encoding="utf-8")
        before = text
        hits = []
        for old, new in COMMON:
            if old in text:
                text = text.replace(old, new)
                hits.append(old)
        if path.name in EXTRA:
            old, new = EXTRA[path.name]
            if old in text:
                text = text.replace(old, new)
                hits.append("platforms")
        if text != before:
            path.write_text(text, encoding="utf-8")
        print(f"{path.name}: {len(hits)} 处")
    # 官方直连那半句单独修（之前批量替换把 606 也改成了 814）
    zh = ROOT / "README.md"
    t = zh.read_text(encoding="utf-8")
    t = t.replace("官方直连 **814 家（55%）**", "官方直连 **606 家（37%）**")
    zh.write_text(t, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
