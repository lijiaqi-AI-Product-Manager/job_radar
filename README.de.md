![job_radar](docs/assets/hero-en.svg)

[![PyPI](https://img.shields.io/pypi/v/jobsearchradar?color=58bfa5)](https://pypi.org/project/jobsearchradar/) [![CI](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml/badge.svg)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml) [![Python](https://img.shields.io/badge/python-3.11%2B-7bb7ff)](pyproject.toml) [![MIT](https://img.shields.io/badge/license-MIT-7bb7ff)](LICENSE)

[简体中文](README.md) · [English](README.en.md) · Deutsch

**Stellenangebote in China. Als lokale Datenbank, mit nachvollziehbaren Quellen.**

Öffentliche Angebote für Berufseinstieg, Praktika und Berufserfahrene sowie Recruiting-Kalender in SQLite. Nach Unternehmen, Stadt und Abschlussjahr filtern, Originalbeschreibungen durchsuchen und zur Bewerbungsseite wechseln. CLI und MCP, ohne API-Schlüssel oder eigenen Server.

## Schnellstart

Das PyPI-Paket heißt `jobsearchradar`, der installierte Befehl `jobradar`. Erfordert Python 3.11+. Unterstützt Windows, macOS und Linux.

```bash
pip install jobsearchradar
jobradar update
jobradar search --company 复星医药 --type campus --grad-year 2027 --table
```

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

2026-10-31 · [Methodology / 统计口径](docs/COVERAGE.md)

| Kennzahl | Wert |
| :--- | ---: |
| Aktivierte Quellen | 2,242 |
| Konfigurierte Unternehmen | 2,201 |
| Adapter | 27 |
| Konfigurationsabdeckung der festen Zielliste | 931 / 1,655 · 56.25% |

Der geprüfte Stand vom 29. Oktober 2026 enthält 294.483 Datensätze, davon 276.008 offene Einträge. Für 97,3 % der offenen Einträge liegt der Originaltext vor. Eine konfigurierte Quelle bedeutet nicht, dass heute eingestellt wird. Eine Sammelanzeige kann mehrere Stellen beschreiben.

[Latest data release](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/data-latest) · `jobradar stats`

## MCP verbinden

```bash
pip install "jobsearchradar[mcp]"
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
