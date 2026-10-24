# job_radar · Offener Datensatz zu Jobs in China (Campus, Praktika, Berufserfahrene)

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | Deutsch | [Русский](README.ru.md)

[![version](https://img.shields.io/badge/version-1.1.0-blue)](CHANGELOG.md)
[![tests](https://img.shields.io/badge/tests-504%20passed-brightgreen)](tests/)
[![data](https://img.shields.io/badge/data-daily-success)](https://github.com/lijiaqimun-coder/job_radar/releases/tag/data-latest)
[![license](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

**Ein Datensatz, der sich täglich selbst aktualisiert**: offizielle Karriereseiten → täglicher Crawl →
eine lokal abfragbare SQLite-Datei. Mit CLI, MCP-Server und Skill kann ein KI-Agent
„wer stellt ein, was, bis wann, wo bewerben" ohne API-Key und ohne Server beantworten.

![demo](docs/assets/demo-en.gif)

> **Datenstand (2026-10-24)**: **279 Quellen** · **~88.600 offene Stellen** · **99,8 % mit vollständigem JD-Text**
> Von den **500 Zielunternehmen** haben 494 Kalender- oder Stellendaten (nur 161 auf Stellenebene).

## Was es ist / was nicht

- ✅ Stellen und JD-Text von **offiziellen** Karriereseiten (keine Aggregatoren)
- ✅ Täglicher Voll-Crawl, Historie bleibt erhalten (neu, geschlossen, geändert)
- ✅ Rekrutierungskalender: Jahrgang, Programmtyp, Fachrichtungen, Bewerbungsfenster, Städte, Link, Quelle
- ❌ Nicht „alle Unternehmen": nur 161 der 500 Ziele liefern Stellenebene
- ❌ Keine Bewerbungen, Empfehlungen, Interviewberichte oder Gehälter; keine Captcha-/Login-/Signatur-Umgehung

## Schnellstart

```bash
# Noch nicht auf PyPI (Pipeline fertig, siehe docs/PUBLISHING.md) — Installation aus dem Quellcode:
pip install "jobradar[mcp] @ git+https://github.com/lijiaqimun-coder/job_radar"

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
| Kalenderabdeckung | 494/500; die übrigen 6 sind durch robots/Login/DNS blockiert |
| Abdeckung je Stelle | 161/500; Rest sind eigene Portale oder verschlüsselte Plattformen (Moka, Feishu ATSX) |
| Große Tech-Firmen | Alibaba/Tencent/Meituan/NetEase… mit Stellen; ByteDance/JD/Huawei nur Kalender |
| Bewerbungsfenster | nur 8 von 1372 Einträgen (0,6 %) mit Beginn und Ende |
| Duplikate | 9,2 % gleiches Unternehmen+Titel+Stadt; `--dedupe` nutzen |
| Historie | seit 2026-10-19, Trends derzeit 5–7 Tage |

Interne Prozessdokumente liegen unter [docs/internal/](docs/internal/).

## Lizenz und Compliance

Code MIT. Rechte an Stelleninhalten liegen bei den Veröffentlichern; dieses Repo indexiert nur.
Nur öffentliche Seiten, ≤1 Anfrage/Sekunde, keine Umgehung von Captcha, Login oder Signatur
([COMPLIANCE.md](COMPLIANCE.md)).
