"""把「不含第三方聚合站」的旧说法改成实际口径：官方直连为主，聚合渠道单列 grade C。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PAIRS = {
    "README.md": (
        "- ✅ 各公司**官方**招聘页的岗位与 JD 原文（不含第三方聚合站）",
        "- ✅ 各公司**官方**招聘页的岗位与 JD 原文；没有合规官方入口的公司另走公开聚合渠道（实习僧 / 高校就业网），一律标 grade C 并与官方口径分开计数",
    ),
    "README.en.md": (
        "- ✅ Jobs and JD text from **official** career sites (no aggregators)",
        "- ✅ Jobs and JD text from **official** career sites; for companies without a compliant official portal we also read public aggregator channels (Shixiseng, university career boards), always marked grade C and counted separately",
    ),
    "README.ja.md": (
        "- ✅ 各社**公式**採用ページの求人と JD 原文（第三者の集約サイトは使いません）",
        "- ✅ 各社**公式**採用ページの求人と JD 原文。公式入口が無い企業は公開集約チャネル（実習生・大学就職サイト）も使い、いずれも grade C として区別して集計します",
    ),
    "README.ko.md": (
        "- ✅ 각 기업 **공식** 채용 페이지의 채용 정보와 JD 원문(제3자 집계 사이트는 사용하지 않음)",
        "- ✅ 각 기업 **공식** 채용 페이지의 채용 정보와 JD 원문. 합법적 공식 입구가 없는 기업은 공개 집계 채널(실습생·대학 취업 사이트)도 사용하며, 모두 grade C로 별도 집계합니다",
    ),
    "README.de.md": (
        "- ✅ Stellen und JD-Text von **offiziellen** Karriereseiten (keine Aggregatoren)",
        "- ✅ Stellen und JD-Text von **offiziellen** Karriereseiten; ohne konformen offiziellen Zugang nutzen wir öffentliche Aggregator-Kanäle, stets als grade C markiert und getrennt gezählt",
    ),
    "README.es.md": (
        "- ✅ Vacantes y texto del JD de portales **oficiales** (sin agregadores de terceros)",
        "- ✅ Vacantes y texto del JD de portales **oficiales**; cuando no hay portal oficial conforme usamos canales agregadores públicos, siempre marcados grade C y contados aparte",
    ),
    "README.fr.md": (
        "- ✅ Offres et texte du JD issus des sites **officiels** (aucun agrégateur tiers)",
        "- ✅ Offres et texte du JD issus des sites **officiels** ; à défaut de portail officiel conforme, nous lisons des canaux agrégateurs publics, toujours marqués grade C et comptés séparément",
    ),
    "README.ru.md": (
        "- ✅ Вакансии и текст JD с **официальных** сайтов (без сторонних агрегаторов)",
        "- ✅ Вакансии и текст JD с **официальных** сайтов; если конформного официального портала нет, используем публичные каналы-агрегаторы, всегда с пометкой grade C и отдельным учётом",
    ),
}

for name, (old, new) in PAIRS.items():
    p = ROOT / name
    t = p.read_text(encoding="utf-8")
    if old in t:
        p.write_text(t.replace(old, new), encoding="utf-8")
        print(f"{name}: ok")
    else:
        print(f"{name}: MISS")
