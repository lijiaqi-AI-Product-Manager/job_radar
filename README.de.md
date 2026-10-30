# job_radar · Offener Datensatz zu Jobs in China (Campus, Praktika, Berufserfahrene)

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | Deutsch | [Русский](README.ru.md)

[![version](https://img.shields.io/badge/version-1.12.1-blue)](CHANGELOG.md)
[![pypi](https://img.shields.io/pypi/v/jobsearchradar)](https://pypi.org/project/jobsearchradar/)
[![tests](https://img.shields.io/badge/tests-504%20passed-brightgreen)](tests/)
[![data](https://img.shields.io/badge/data-daily-success)](https://github.com/lijiaqimun-coder/job_radar/releases/tag/data-latest)
[![license](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

**Ein Datensatz, der sich täglich selbst aktualisiert**: offizielle Karriereseiten → täglicher Crawl →
eine lokal abfragbare SQLite-Datei. Mit CLI, MCP-Server und Skill kann ein KI-Agent
„wer stellt ein, was, bis wann, wo bewerben" ohne API-Key und ohne Server beantworten.

![demo](docs/assets/demo-en.gif)

> **Datenstand (2026-10-29)**: **2,229 Quellen** · **2,188 Unternehmen** · **26 Adapter**
> (Beisen 1,229 / Dayee 310 / Feishu ATSX 148 / Tupu360 32 / Alt-Beisen 113 / Workday 45 / Alt-Dayee 15 / eigene Seiten 19)
> Von den **1.655 Zielen** (1.117 in 20 Branchen + 808 in 31 Provinzregionen) sind **906 abgedeckt (55 %)**, 12 sind aus Compliance-Gründen nicht erreichbar.
> Stellenzahlen und Feldabdeckung werden bei jedem täglichen Crawl aktualisiert (siehe neuestes Release).

## Was es ist / was nicht

- ✅ Stellen und JD-Text von **offiziellen** Karriereseiten; ohne konformen offiziellen Zugang nutzen wir öffentliche Aggregator-Kanäle, stets als grade C markiert und getrennt gezählt
- ✅ Täglicher Voll-Crawl, Historie bleibt erhalten (neu, geschlossen, geändert)
- ✅ Rekrutierungskalender: Jahrgang, Programmtyp, Fachrichtungen, Bewerbungsfenster, Städte, Link, Quelle
- ❌ Nicht „alle Unternehmen": 577 der 1.655 Ziele haben eine Quelle; die übrigen 1.078 stehen auf der offenen Liste
- ❌ Keine Bewerbungen, Empfehlungen, Interviewberichte oder Gehälter; keine Captcha-/Login-/Signatur-Umgehung

## Schnellstart

```bash
pip install "jobsearchradar[mcp]"

jobradar update     # ~20 MB + 35 MB; kein Download, wenn bereits aktuell
jobradar search --company 腾讯 --city 深圳 --category 算法 --table
```

Aus Festlandchina das Gitee-Mirror nutzen (fällt automatisch auf GitHub zurück):

```bash
jobradar update --mirror gitee
```

## Mögliche Fragen

```bash
jobradar search --text "PyTorch 大模型" --type campus   # Volltextsuche über Titel + JD
jobradar search --company 喜茶 --exclude-store          # Filialstellen ausblenden (~8.000)
jobradar search --company 星巴克中国 --dedupe           # doppelte Requisitionen bündeln (variants)
jobradar diff --days 7 --by category --company 腾讯     # Neuzugänge je Unternehmen und Fachbereich
jobradar calendar --group 阿里巴巴 --type 秋招 --table   # lesbarer Kalender
```

Hat ein Unternehmen keine Stellen, aber Kalendereinträge (ByteDance, Huawei, Xiaomi…), liefert
`search` einen `calendar`-Block mit `jobradar calendar --group <Name> --table` statt „keine Daten",
inklusive des Hinweises `{Name}希望你去他们的招聘页逛一逛哦~`.

## Für KI-Agenten

- **Claude Code**: `skill/jobradar/` nach `~/.claude/skills/jobradar/` kopieren
- **MCP-Clients** (Claude Desktop, Cursor…): Befehl `jobradar-mcp` (stdio, 9 Tools).
  Liegen die Daten nicht in `~/.cache/jobradar`, `JOBRADAR_HOME` im MCP-`env`-Block setzen
- Auch als Bibliothek nutzbar: `from jobradar.core import queries`

## Bekannte Grenzen

| Bereich | Realität |
|---|---|
| Zielabdeckung | **577/1.655 (35 %)**; 12 Ziele sind wegen robots/Login/Verschlüsselung nicht konform erreichbar |
| Quellen | **1.310 Quellen / 1.281 Unternehmen** über 26 Adapter |
| Große Tech-Firmen | Alibaba/Tencent/Meituan/NetEase… mit Stellen; ByteDance/JD/Huawei nur Kalender |
| Provinzabdeckung | Guangdong 18/49, Zhejiang 13/44, Jiangsu 9/34, Sichuan 9/30, Shandong 7/26 — vollständige Tabelle: `scripts/coverage_report.py` |
| Bewerbungsfenster | Beginn und Ende sind nur bei einem Teil der Kalendereinträge gesetzt; genaue Zahl: jobradar stats |
| Duplikate | 9,2 % gleiches Unternehmen+Titel+Stadt; `--dedupe` nutzen |
| Historie | seit 2026-10-19, Trends derzeit 5–7 Tage |

Interne Prozessdokumente liegen unter [docs/internal/](docs/internal/).

## Lizenz und Compliance

Code MIT. Rechte an Stelleninhalten liegen bei den Veröffentlichern; dieses Repo indexiert nur.
Nur öffentliche Seiten, ≤1 Anfrage/Sekunde, keine Umgehung von Captcha, Login oder Signatur
([COMPLIANCE.md](COMPLIANCE.md)).
