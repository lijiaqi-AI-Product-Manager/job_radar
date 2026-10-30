"""补改五份非中文 README 里剩下的覆盖率数字（语言各自的分隔符不同，单独处理）。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PAIRS: dict[str, list[tuple[str, str]]] = {
    "README.de.md": [
        ("**606 abgedeckt (37 %)**", "**814 abgedeckt (49 %)**"),
        ("**23 Adapter**", "**25 Adapter**"),
    ],
    "README.es.md": [
        ("**606 están cubiertas (37 %)**", "**814 están cubiertas (49 %)**"),
    ],
    "README.fr.md": [
        ("**606 sont couvertes (37 %)**", "**814 sont couvertes (49 %)**"),
    ],
    "README.ru.md": [
        ("**606 покрыты (37 %)**", "**814 покрыты (49 %)**"),
    ],
    "README.ko.md": [
        ("**606개(37%)**", "**814개(49%)**"),
        ("**606/1,655(37%)**", "**814/1,655(49%)**"),
        ("**23개 어댑터**", "**25개 어댑터**"),
    ],
}

for name, pairs in PAIRS.items():
    path = ROOT / name
    text = path.read_text(encoding="utf-8")
    hits = []
    for old, new in pairs:
        if old in text:
            text = text.replace(old, new)
            hits.append(old)
        else:
            hits.append(f"MISS:{old}")
    path.write_text(text, encoding="utf-8")
    print(name, hits)
