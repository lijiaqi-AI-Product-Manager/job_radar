# job_radar · Dataset abierto de empleo en China (campus, prácticas y experiencia)

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | Español | [Français](README.fr.md) | [Deutsch](README.de.md) | [Русский](README.ru.md)

[![version](https://img.shields.io/badge/version-1.9.4-blue)](CHANGELOG.md)
[![pypi](https://img.shields.io/pypi/v/jobsearchradar)](https://pypi.org/project/jobsearchradar/)
[![tests](https://img.shields.io/badge/tests-504%20passed-brightgreen)](tests/)
[![data](https://img.shields.io/badge/data-daily-success)](https://github.com/lijiaqimun-coder/job_radar/releases/tag/data-latest)
[![license](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

**Un dataset de empleo que se actualiza solo cada día**: portales de empleo oficiales → rastreo diario →
un SQLite listo para consultar. Incluye CLI, servidor MCP y Skill para que un agente de IA responda
«quién contrata, qué, hasta cuándo y dónde aplicar» sin claves de API ni servidor.

![demo](docs/assets/demo-en.gif)

> **Datos (2026-10-29)**: **1,911 fuentes** · **1,870 empresas** · **23 adaptadores**
> (Beisen 1,229 / Dayee 310 / Feishu ATSX 148 / Tupu360 32 / Beisen antiguo 113 / Workday 45 / Dayee antiguo 15 / sitios propios 19)
> De las **1.655 empresas objetivo** (1.117 en 20 sectores + 808 en 31 regiones provinciales), **606 están cubiertas (37 %)** y 12 no son accesibles por cumplimiento.
> Las cifras de vacantes y cobertura de campos se actualizan en cada rastreo diario (ver última versión).

## Qué es y qué no es

- ✅ Vacantes y texto del JD de portales **oficiales** (sin agregadores de terceros)
- ✅ Rastreo completo diario con historial (apertura, cierre, cambios)
- ✅ Calendario de reclutamiento: promoción, tipo de programa, áreas, ventana de solicitud, ciudades, enlace y fuente
- ❌ No cubre «todas las empresas»: 577 de las 1.655 objetivo tienen fuente; las otras 1.078 están en la lista abierta
- ❌ No gestiona solicitudes, referidos, entrevistas ni salarios; no evade captchas, logins ni firmas

## Inicio rápido

```bash
# Aún no está en PyPI (el pipeline está listo, ver docs/PUBLISHING.md): instala desde el código
pip install "jobsearchradar[mcp]"

jobradar update     # ~20 MB + 35 MB; si ya está al día no descarga nada
jobradar search --company 腾讯 --city 深圳 --category 算法 --table
```

Desde China continental, usa el espejo de Gitee (vuelve a GitHub si falla):

```bash
jobradar update --mirror gitee
```

## Qué puedes preguntar

```bash
jobradar search --text "PyTorch 大模型" --type campus   # búsqueda en título + JD
jobradar search --company 喜茶 --exclude-store          # excluye puestos de tienda (~8.000)
jobradar search --company 星巴克中国 --dedupe           # agrupa requisiciones duplicadas (variants)
jobradar diff --days 7 --by category --company 腾讯     # novedades por empresa y área
jobradar calendar --group 阿里巴巴 --type 秋招 --table   # calendario legible
```

Si una empresa no tiene vacantes pero sí calendario (ByteDance, Huawei, Xiaomi…), `search`
devuelve un bloque `calendar` con `jobradar calendar --group <empresa> --table` en lugar de
«no hay datos», más la nota `{empresa}希望你去他们的招聘页逛一逛哦~`.

## Para agentes de IA

- **Claude Code**: copia `skill/jobradar/` en `~/.claude/skills/jobradar/`
- **Clientes MCP** (Claude Desktop, Cursor…): comando `jobradar-mcp` (stdio, 9 herramientas).
  Si tus datos no están en `~/.cache/jobradar`, pasa `JOBRADAR_HOME` en el bloque `env` de MCP
- También como librería: `from jobradar.core import queries`

## Límites conocidos

| Área | Realidad |
|---|---|
| Cobertura de objetivos | **577/1.655 (35 %)**; 12 no se pueden cubrir de forma conforme (robots/login/cifrado) |
| Fuentes | **1.310 fuentes / 1.281 empresas** con 23 adaptadores |
| Grandes tecnológicas | Alibaba/Tencent/Meituan/NetEase… con vacantes; ByteDance/JD/Huawei solo calendario |
| Cobertura provincial | Guangdong 18/49, Zhejiang 13/44, Jiangsu 9/34, Sichuan 9/30, Shandong 7/26 — tabla completa: `scripts/coverage_report.py` |
| Ventanas de solicitud | solo una parte de las entradas de calendario tiene inicio y fin; cifra exacta: jobradar stats |
| Duplicados | 9,2% son misma empresa+título+ciudad; usa `--dedupe` |
| Historial | desde 2026-10-19, las tendencias cubren 5–7 días |

Los documentos internos están en [docs/internal/](docs/internal/).

## Licencia y cumplimiento

Código MIT. El contenido de las vacantes pertenece a quien lo publica; este repositorio solo indexa.
Solo se acceden páginas públicas, ≤1 petición/segundo, sin evadir captchas, logins ni firmas
([COMPLIANCE.md](COMPLIANCE.md)).
