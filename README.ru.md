![job_radar](docs/assets/hero-en.svg)

[![Release](https://img.shields.io/badge/release-v2.0.0-58bfa5)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/v2.0.0) [![PyPI](https://img.shields.io/pypi/v/jobsearchradar?color=58bfa5)](https://pypi.org/project/jobsearchradar/) [![CI](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml/badge.svg)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml) [![Python](https://img.shields.io/badge/python-3.11%2B-7bb7ff)](pyproject.toml) [![MIT](https://img.shields.io/badge/license-MIT-7bb7ff)](LICENSE)

[简体中文](README.md) · [English](README.en.md) · Русский

**Вакансии в Китае и календарь набора — в вашей локальной базе данных.**

Публичные вакансии для выпускников, стажёров и опытных специалистов собраны в SQLite. Фильтруйте по компании, городу и году выпуска, ищите в оригинальных описаниях и переходите к исходной странице отклика. CLI и MCP без API-ключа и собственного сервера.

## Быстрый старт

Пакет PyPI называется `jobsearchradar`, установленная команда — `jobradar`. Нужен Python 3.11+. Поддерживаются Windows, macOS и Linux.

```bash
pip install jobsearchradar
jobradar update
jobradar search --company 复星医药 --type campus --grad-year 2027 --table
```

![job_radar demo](docs/assets/demo-en.gif)

<sub>Анимация показывает фрагменты реальных результатов. Её длительность не отражает скорость поиска. Статус и сроки проверяйте на исходной странице работодателя.</sub>

## Примеры запросов

```bash
jobradar search --text "PyTorch 大模型" --type campus --limit 3 --table
jobradar search --city 上海 --category 算法 --type intern --dedupe --table
jobradar calendar --group 阿里巴巴 --grad-year 2027 --table
jobradar diff --days 7 --types open --table
jobradar doctor
```

`--table` → table · default → JSON · `JOBRADAR_HOME` → data directory

## Данные и охват

2026-10-31 · [Methodology / 统计口径](docs/COVERAGE.md)

| Показатель | Значение |
| :--- | ---: |
| Активные источники | 2,242 |
| Настроенные компании | 2,201 |
| Адаптеры | 27 |
| Охват фиксированного списка целевых компаний | 931 / 1,655 · 56.25% |

Проверенный снимок от 29 октября 2026 года содержит 294 483 записи, из них 276 008 открытых. Оригинальный текст есть у 97,3 % открытых записей. Настроенный источник не означает, что компания нанимает сегодня. Объявление агрегатора может описывать несколько должностей.

[Latest data release](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/data-latest) · `jobradar stats`

## Подключение MCP

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

Добавьте `jobradar-mcp` как службу stdio. Девять инструментов обеспечивают поиск, просмотр деталей, изменений, сравнений, динамики, календаря и статистики. При смене каталога данных передайте `JOBRADAR_HOME` через поле `env` службы.

## Документация и участие

Приветствуются разрешённые публичные источники, исправления дат, воспроизводимые сообщения об ошибках и переводы. Если проект полезен, Star или рекомендация помогут другим его найти.

[English guide](README.en.md) · [文档 / Docs](docs/README.md) · [FAQ](docs/FAQ.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

Код распространяется по MIT. Права на тексты вакансий и другой сторонний контент остаются у правообладателей; лицензия кода не предоставляет дополнительных прав на этот контент.
