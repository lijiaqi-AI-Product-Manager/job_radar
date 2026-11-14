![job_radar](docs/assets/hero-en.svg)

[![Release](https://img.shields.io/github/v/release/lijiaqi-AI-Product-Manager/job_radar?cacheSeconds=300&color=58bfa5)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/latest) [![PyPI](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fpypi.org%2Fpypi%2Fjobsearchradar%2Fjson&query=%24.info.version&label=PyPI&prefix=v&color=58bfa5&cacheSeconds=300)](https://pypi.org/project/jobsearchradar/) [![CI](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml/badge.svg)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml) [![Python](https://img.shields.io/badge/python-3.11%2B-7bb7ff)](pyproject.toml) [![MIT](https://img.shields.io/badge/license-MIT-7bb7ff)](LICENSE)

[简体中文](README.md) · [English](README.en.md) · Русский

**Добавьте навык поиска работы своему привычному ИИ-помощнику.**

Назовите города, направление и условия. Помощник ищет вакансии для выпускников, стажёров и опытных специалистов в Китае, читает требования и даёт ссылки на источники и календарь набора. Рекомендуется агентный режим с навыками или локальными инструментами.

## Быстрый старт

Отправьте этот запрос совместимому помощнику. Выполните первоначальное подключение по подсказкам платформы, затем ищите в обычном диалоге.

```text
Подключи навык поиска работы jobradar из этого репозитория. Сначала
проверь совместимость текущей среды. После подключения найди
стажировки в продуктовом направлении в Шанхае, укажи требования,
исходные ссылки и опубликованные сроки. Неизвестные сведения перечисли
отдельно.
https://github.com/lijiaqi-AI-Product-Manager/job_radar
```

Если нужен файл, импортируйте jobradar-skill.zip из последнего Release. После импорта ещё требуется подготовить инструменты и данные. Обычный веб-чат не обязательно умеет запускать локальные инструменты.

[Platform routes / 平台接入](docs/PLATFORMS.md) · [Skill download](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/latest)

<details>
<summary><strong>Ручная настройка (для помощника или того, кто его настраивает)</strong></summary>

Пакет PyPI называется `jobsearchradar`, установленная команда — `jobradar`. Нужен Python 3.11+. Поддерживаются Windows, macOS и Linux.

```bash
pip install --upgrade "jobsearchradar"
jobradar update
jobradar search --company 复星医药 --type campus --grad-year 2027 --table
```

</details>

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

2026-11-14 · [Methodology / 统计口径](docs/COVERAGE.md)

| Показатель | Значение |
| :--- | ---: |
| Активные источники | 2,230 |
| Настроенные компании | 2,199 |
| Адаптеры | 27 |
| Охват фиксированного списка целевых компаний | 944 / 1,655 · 57.04% |

Проверенный снимок от 14 ноября 2026 года (UTC) содержит 354 560 записи, из них 320 124 открытых. Оригинальный текст есть у 97,6 % открытых записей. Настроенный источник не означает, что компания нанимает сегодня. Объявление агрегатора может описывать несколько должностей.

[Latest data release](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/data-latest) · `jobradar stats`

## Подключение MCP

```bash
pip install --upgrade "jobsearchradar[mcp]"
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

<!-- project-growth:start -->

## Динамика проекта

История Stars обновляется ежедневно. Даты обновления указаны в UTC, а даты Stars следуют агрегатам GitHub. Также показаны ежедневные запросы на скачивание из PyPI.

<a href="https://github.com/lijiaqi-AI-Product-Manager/job_radar/stargazers">
<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/stars-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/stars-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/stars-dark.svg">
  <img src="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/stars-light.svg" width="960" alt="job_radar · История GitHub Stars">
</picture>
</a>

<a href="https://pypistats.org/packages/jobsearchradar">
<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/downloads-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/downloads-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/downloads-dark.svg">
  <img src="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/downloads-light.svg" width="960" alt="job_radar · Ежедневные запросы на скачивание">
</picture>
</a>

Запросы включают повторные и автоматические обращения и не равны числу уникальных или активных пользователей.

[Источники данных и определения показателей](https://github.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/blob/main/docs/growth.md)

<!-- project-growth:end -->
