![job_radar](docs/assets/hero-en.svg)

[![PyPI](https://img.shields.io/pypi/v/jobsearchradar?color=58bfa5)](https://pypi.org/project/jobsearchradar/) [![CI](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml/badge.svg)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml) [![Python](https://img.shields.io/badge/python-3.11%2B-7bb7ff)](pyproject.toml) [![MIT](https://img.shields.io/badge/license-MIT-7bb7ff)](LICENSE)

[简体中文](README.md) · [English](README.en.md) · Español

**Empleo en China, calendarios de selección y una base de datos que puedes consultar localmente.**

Reúne ofertas públicas para recién graduados, prácticas y profesionales en SQLite. Filtra por empresa, ciudad o promoción, busca en las descripciones originales y accede al enlace de candidatura. CLI y MCP, sin clave de API ni servidor que desplegar.

## Inicio rápido

El paquete de PyPI se llama `jobsearchradar`; el comando instalado es `jobradar`. Requiere Python 3.11+ y funciona en Windows, macOS y Linux.

```bash
pip install jobsearchradar
jobradar update
jobradar search --company 复星医药 --type campus --grad-year 2027 --table
```

![job_radar demo](docs/assets/demo-en.gif)

<sub>La animación muestra extractos de consultas reales. Su duración no representa la latencia. Comprueba el estado y los plazos en la página original.</sub>

## Ejemplos de consulta

```bash
jobradar search --text "PyTorch 大模型" --type campus --limit 3 --table
jobradar search --city 上海 --category 算法 --type intern --dedupe --table
jobradar calendar --group 阿里巴巴 --grad-year 2027 --table
jobradar diff --days 7 --types open --table
jobradar doctor
```

`--table` → table · default → JSON · `JOBRADAR_HOME` → data directory

## Datos y cobertura

2026-10-31 · [Methodology / 统计口径](docs/COVERAGE.md)

| Métrica | Valor |
| :--- | ---: |
| Fuentes habilitadas | 2,242 |
| Empresas configuradas | 2,201 |
| Adaptadores | 27 |
| Cobertura del conjunto fijo de empresas objetivo | 931 / 1,655 · 56.25% |

La instantánea verificada del 29 de octubre de 2026 contiene 294.483 registros, de los cuales 276.008 figuran abiertos. El 97,3 % de los registros abiertos tiene descripción original. Una fuente configurada no implica contratación activa hoy. Un anuncio de un agregador puede incluir varios puestos.

[Latest data release](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/data-latest) · `jobradar stats`

## Conectar MCP

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

Registra `jobradar-mcp` como servicio stdio. Ofrece nueve herramientas para búsquedas, detalles, cambios, comparaciones, tendencias, calendarios y estadísticas. Si cambias la carpeta de datos, pasa `JOBRADAR_HOME` en el campo `env` del servicio.

## Documentación y contribuciones

Puedes añadir fuentes públicas permitidas, corregir fechas, informar de errores reproducibles o mejorar traducciones. Si te resulta útil, una Star o compartirlo ayuda a otros a descubrirlo.

[English guide](README.en.md) · [文档 / Docs](docs/README.md) · [FAQ](docs/FAQ.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

El código usa la licencia MIT. Los textos de ofertas y demás contenido de terceros conservan los derechos de sus titulares; la licencia del código no concede derechos adicionales sobre ese contenido.
