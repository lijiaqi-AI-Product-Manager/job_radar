![job_radar](docs/assets/hero-en.svg)

[![Release](https://img.shields.io/badge/release-v2.2.2-58bfa5)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/v2.2.2) [![PyPI](https://img.shields.io/pypi/v/jobsearchradar?color=58bfa5)](https://pypi.org/project/jobsearchradar/) [![CI](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml/badge.svg)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml) [![Python](https://img.shields.io/badge/python-3.11%2B-7bb7ff)](pyproject.toml) [![MIT](https://img.shields.io/badge/license-MIT-7bb7ff)](LICENSE)

[简体中文](README.md) · [English](README.en.md) · Deutsch

**Geben Sie Ihrem gewohnten KI-Assistenten eine Fähigkeit zur Jobsuche.**

Nennen Sie Städte, Tätigkeit und Bedingungen. Ihr Assistent durchsucht Einstiegsstellen, Praktika, Stellen für Berufserfahrene und Recruiting-Kalender in China, liest Anforderungen und liefert Quellenlinks. Empfohlen wird ein Agent-Modus mit Skills oder lokalen Werkzeugen.

## Schnellstart

Senden Sie diese Anfrage an einen kompatiblen Assistenten. Folgen Sie einmalig den Einrichtungshinweisen und suchen Sie danach im Gespräch.

```text
Verbinde den jobradar-Skill zur Jobsuche aus diesem Repository. Prüfe
zuerst, ob diese Umgebung ihn unterstützt. Suche danach
Produktpraktika in Shanghai und nenne Anforderungen, Originalquellen
und angegebene Fristen. Führe unbekannte Angaben gesondert auf.
https://github.com/lijiaqi-AI-Product-Manager/job_radar
```

Falls eine Datei benötigt wird, importieren Sie jobradar-skill.zip aus dem neuesten Release. Werkzeuge und Daten müssen danach weiterhin eingerichtet werden. Ein gewöhnlicher Webchat kann lokale Werkzeuge nicht zwangsläufig ausführen.

[Platform routes / 平台接入](docs/PLATFORMS.md) · [Skill download](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/latest)

<details>
<summary><strong>Manuelle Einrichtung (für die einrichtende Person oder den Assistenten)</strong></summary>

Das PyPI-Paket heißt `jobsearchradar`, der installierte Befehl `jobradar`. Erfordert Python 3.11+. Unterstützt Windows, macOS und Linux.

```bash
pip install --upgrade "jobsearchradar==2.2.2"
jobradar update
jobradar search --company 复星医药 --type campus --grad-year 2027 --table
```

</details>

![job_radar demo](docs/assets/demo-en.gif)

<sub>Die Animation zeigt Auszüge echter Abfragen. Die Wiedergabedauer entspricht keiner Laufzeitmessung. Aktuellen Status und Fristen auf der Originalseite prüfen.</sub>

## Abfragebeispiele

```bash
jobradar search --text "PyTorch 大模型" --type campus --limit 3 --table
jobradar search --city 上海 --category 算法 --type intern --dedupe --table
jobradar calendar --group 阿里巴巴 --grad-year 2027 --table
jobradar diff --days 7 --types open --table
jobradar doctor
```

`--table` → table · default → JSON · `JOBRADAR_HOME` → data directory

## Daten und Abdeckung

2026-11-03 · [Methodology / 统计口径](docs/COVERAGE.md)

| Kennzahl | Wert |
| :--- | ---: |
| Aktivierte Quellen | 2,262 |
| Konfigurierte Unternehmen | 2,223 |
| Adapter | 27 |
| Konfigurationsabdeckung der festen Zielliste | 950 / 1,655 · 57.40% |

Der geprüfte Stand vom 2. November 2026 (UTC) enthält 298.458 Datensätze, davon 277.482 offene Einträge. Für 97,3 % der offenen Einträge liegt der Originaltext vor. Eine konfigurierte Quelle bedeutet nicht, dass heute eingestellt wird. Eine Sammelanzeige kann mehrere Stellen beschreiben.

[Latest data release](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/data-latest) · `jobradar stats`

## MCP verbinden

```bash
pip install --upgrade "jobsearchradar[mcp]==2.2.2"
jobradar update
```

```json
{
  "mcpServers": {
    "jobradar": {
      "command": "jobradar-mcp"
    }
  }
}
```

`jobradar-mcp` als stdio-Dienst eintragen. Neun Werkzeuge bieten Suche, Details, Änderungen, Vergleiche, Trends, Kalender und Statistiken. Für einen anderen Datenordner `JOBRADAR_HOME` im Feld `env` des Dienstes setzen.

## Dokumentation und Beiträge

Erlaubte öffentliche Quellen ergänzen, Termine berichtigen, reproduzierbare Fehler melden oder Übersetzungen verbessern. Ein Star oder das Teilen des Projekts hilft anderen bei der Entdeckung.

[English guide](README.en.md) · [文档 / Docs](docs/README.md) · [FAQ](docs/FAQ.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

Der Code steht unter MIT. Rechte an Stellenbeschreibungen und sonstigen Inhalten Dritter verbleiben bei den jeweiligen Rechteinhabern; die Code-Lizenz gewährt dafür keine zusätzlichen Rechte.
