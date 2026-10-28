# job_radar · Открытый датасет вакансий в Китае (кампус, стажировки, опытные специалисты)

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | Русский

[![version](https://img.shields.io/badge/version-1.7.2-blue)](CHANGELOG.md)
[![pypi](https://img.shields.io/pypi/v/jobsearchradar)](https://pypi.org/project/jobsearchradar/)
[![tests](https://img.shields.io/badge/tests-504%20passed-brightgreen)](tests/)
[![data](https://img.shields.io/badge/data-daily-success)](https://github.com/lijiaqimun-coder/job_radar/releases/tag/data-latest)
[![license](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

**Датасет, который обновляется сам каждый день**: официальные карьерные сайты → ежедневный сбор →
один SQLite-файл для локальных запросов. В комплекте CLI, MCP-сервер и Skill: ИИ-агент отвечает
«кто нанимает, что, до какого числа, куда откликаться» без API-ключей и без сервера.

![demo](docs/assets/demo-en.gif)

> **Данные (2026-10-29)**: **1 749 источников** · **1 720 компаний** · **23 адаптера**
> (Beisen 1,145 / Dayee 309 / Feishu ATSX 140 / Tupu360 32 / старый Beisen 44 / Workday 45 / старый Dayee 15 / собственные сайты 19)
> Из **1 655 целей** (1 117 в 20 отраслях + 808 в 31 провинциальном регионе) **581 покрыты (35 %)**, ещё 12 недоступны по требованиям комплаенса.
> Число вакансий и покрытие полей обновляются при каждом ежедневном сборе (см. последний релиз).

## Что это и чем не является

- ✅ Вакансии и текст JD с **официальных** сайтов (без сторонних агрегаторов)
- ✅ Ежедневный полный сбор, история сохраняется (открытие, закрытие, изменения)
- ✅ Календарь рекрутинга: год выпуска, тип программы, направления, окно подачи, города, ссылка, источник
- ❌ Это не «все компании»: у 577 из 1 655 целей есть источник, остальные 1 078 — в открытом списке
- ❌ Нет откликов, рефералов, отзывов о собеседованиях и зарплат; обход капчи/логина/подписи запрещён

## Быстрый старт

```bash
pip install "jobsearchradar[mcp]"

jobradar update     # ~20 МБ + 35 МБ; если уже актуально — ничего не скачивается
jobradar search --company 腾讯 --city 深圳 --category 算法 --table
```

Из материкового Китая используйте зеркало Gitee (при сбое автоматически GitHub):

```bash
jobradar update --mirror gitee
```

## Что можно спросить

```bash
jobradar search --text "PyTorch 大模型" --type campus   # полнотекстовый поиск по названию и JD
jobradar search --company 喜茶 --exclude-store          # исключить вакансии магазинов (~8 000)
jobradar search --company 星巴克中国 --dedupe           # схлопнуть дубли requisition (variants)
jobradar diff --days 7 --by category --company 腾讯     # новые вакансии компании по категориям
jobradar calendar --group 阿里巴巴 --type 秋招 --table   # читаемый вывод календаря
```

Если у компании нет вакансий, но есть календарь (ByteDance, Huawei, Xiaomi…), `search`
возвращает блок `calendar` с `jobradar calendar --group <компания> --table` вместо
«нет данных», плюс пометку `{компания}希望你去他们的招聘页逛一逛哦~`.

## Для ИИ-агентов

- **Claude Code**: скопируйте `skill/jobradar/` в `~/.claude/skills/jobradar/`
- **MCP-клиенты** (Claude Desktop, Cursor…): команда `jobradar-mcp` (stdio, 9 инструментов).
  Если данные лежат не в `~/.cache/jobradar`, передайте `JOBRADAR_HOME` в блоке `env` MCP
- Можно использовать как библиотеку: `from jobradar.core import queries`

## Известные ограничения

| Область | Факт |
|---|---|
| Покрытие целей | **577/1 655 (35 %)**; 12 нельзя покрыть в рамках комплаенса (robots/логин/шифрование) |
| Источники | **1 131 источник / 1 099 компаний**, 23 адаптера |
| Крупный тех | Alibaba/Tencent/Meituan/NetEase… с вакансиями; ByteDance/JD/Huawei — только календарь |
| Покрытие провинций | Guangdong 18/49, Zhejiang 13/44, Jiangsu 9/34, Sichuan 9/30, Shandong 7/26 — полная таблица: `scripts/coverage_report.py` |
| Окна подачи | начало и конец заданы лишь у части записей календаря; точное число: jobradar stats |
| Дубли | 9,2 % — та же компания+должность+город; используйте `--dedupe` |
| История | с 2026-10-19, тренды пока покрывают 5–7 дней |

Внутренние процессные документы — в [docs/internal/](docs/internal/).

## Лицензия и комплаенс

Код — MIT. Права на содержимое вакансий принадлежат публикующим; репозиторий только индексирует.
Только публичные страницы, ≤1 запрос/сек, без обхода капчи, логина и подписи
([COMPLIANCE.md](COMPLIANCE.md)).
