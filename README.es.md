# job_radar · Dataset abierto de empleo en China (campus, prácticas y experiencia)

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | Español | [Français](README.fr.md) | [Deutsch](README.de.md) | [Русский](README.ru.md)

[![version](https://img.shields.io/badge/version-1.1.1-blue)](CHANGELOG.md)
[![pypi](https://img.shields.io/pypi/v/jobradar)](https://pypi.org/project/jobradar/)
[![tests](https://img.shields.io/badge/tests-504%20passed-brightgreen)](tests/)
[![data](https://img.shields.io/badge/data-daily-success)](https://github.com/lijiaqimun-coder/job_radar/releases/tag/data-latest)
[![license](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

**Un dataset de empleo que se actualiza solo cada día**: portales de empleo oficiales → rastreo diario →
un SQLite listo para consultar. Incluye CLI, servidor MCP y Skill para que un agente de IA responda
«quién contrata, qué, hasta cuándo y dónde aplicar» sin claves de API ni servidor.

![demo](docs/assets/demo-en.gif)

> **Datos (2026-10-24)**: **279 fuentes** · **~88.600 vacantes abiertas** · **99,8% con texto completo del JD**
> De las **500 empresas objetivo**, 494 tienen calendario o vacantes (solo 161 con datos a nivel de vacante).

## Qué es y qué no es

- ✅ Vacantes y texto del JD de portales **oficiales** (sin agregadores de terceros)
- ✅ Rastreo completo diario con historial (apertura, cierre, cambios)
- ✅ Calendario de reclutamiento: promoción, tipo de programa, áreas, ventana de solicitud, ciudades, enlace y fuente
- ❌ No cubre «todas las empresas»: solo 161 de las 500 objetivo publican datos por vacante
- ❌ No gestiona solicitudes, referidos, entrevistas ni salarios; no evade captchas, logins ni firmas

## Inicio rápido

```bash
# Aún no está en PyPI (el pipeline está listo, ver docs/PUBLISHING.md): instala desde el código
pip install "jobradar[mcp]"

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
| Cobertura de calendario | 494/500; las otras 6 están bloqueadas por robots/login/DNS |
| Cobertura por vacante | 161/500; el resto son portales propios o plataformas cifradas (Moka, Feishu ATSX) |
| Grandes tecnológicas | Alibaba/Tencent/Meituan/NetEase… con vacantes; ByteDance/JD/Huawei solo calendario |
| Ventanas de solicitud | solo 8/1372 entradas (0,6%) con inicio y fin |
| Duplicados | 9,2% son misma empresa+título+ciudad; usa `--dedupe` |
| Historial | desde 2026-10-19, las tendencias cubren 5–7 días |

Los documentos internos están en [docs/internal/](docs/internal/).

## Licencia y cumplimiento

Código MIT. El contenido de las vacantes pertenece a quien lo publica; este repositorio solo indexa.
Solo se acceden páginas públicas, ≤1 petición/segundo, sin evadir captchas, logins ni firmas
([COMPLIANCE.md](COMPLIANCE.md)).
