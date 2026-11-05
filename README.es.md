![job_radar](docs/assets/hero-en.svg)

[![Release](https://img.shields.io/github/v/release/lijiaqi-AI-Product-Manager/job_radar?cacheSeconds=300&color=58bfa5)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/latest) [![PyPI](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fpypi.org%2Fpypi%2Fjobsearchradar%2Fjson&query=%24.info.version&label=PyPI&prefix=v&color=58bfa5&cacheSeconds=300)](https://pypi.org/project/jobsearchradar/) [![CI](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml/badge.svg)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml) [![Python](https://img.shields.io/badge/python-3.11%2B-7bb7ff)](pyproject.toml) [![MIT](https://img.shields.io/badge/license-MIT-7bb7ff)](LICENSE)

[简体中文](README.md) · [English](README.en.md) · Español

**Añade una habilidad para buscar empleo a tu asistente de IA habitual.**

Dile las ciudades, el puesto y tus condiciones. El asistente consulta empleo en China para recién graduados, prácticas y profesionales, lee los requisitos y presenta enlaces a las fuentes. Recomendamos un modo agente con habilidades o herramientas locales.

## Inicio rápido

Envía esta petición a un asistente compatible. Sigue las indicaciones de conexión inicial y después busca conversando.

```text
Conecta la habilidad de búsqueda de empleo jobradar de este
repositorio. Comprueba primero si este entorno es compatible. Después
busca prácticas de producto en Shanghái y muestra requisitos, enlaces
originales y plazos indicados. Separa la información desconocida.
https://github.com/lijiaqi-AI-Product-Manager/job_radar
```

Si pide un archivo, importa jobradar-skill.zip de la última Release. Después de importarlo aún hay que preparar las herramientas y los datos. Un chat web normal no siempre puede ejecutar herramientas locales.

[Platform routes / 平台接入](docs/PLATFORMS.md) · [Skill download](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/latest)

<details>
<summary><strong>Configuración manual (para quien configure el asistente)</strong></summary>

El paquete de PyPI se llama `jobsearchradar`; el comando instalado es `jobradar`. Requiere Python 3.11+ y funciona en Windows, macOS y Linux.

```bash
pip install --upgrade "jobsearchradar"
jobradar update
jobradar search --company 复星医药 --type campus --grad-year 2027 --table
```

</details>

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

2026-11-05 · [Methodology / 统计口径](docs/COVERAGE.md)

| Métrica | Valor |
| :--- | ---: |
| Fuentes habilitadas | 2,230 |
| Empresas configuradas | 2,199 |
| Adaptadores | 27 |
| Cobertura del conjunto fijo de empresas objetivo | 944 / 1,655 · 57.04% |

La instantánea verificada del 5 de noviembre de 2026 (UTC) contiene 346.273 registros, de los cuales 320.353 figuran abiertos. El 97,6 % de los registros abiertos tiene descripción original. Una fuente configurada no implica contratación activa hoy. Un anuncio de un agregador puede incluir varios puestos.

[Latest data release](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/data-latest) · `jobradar stats`

## Conectar MCP

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

Registra `jobradar-mcp` como servicio stdio. Ofrece nueve herramientas para búsquedas, detalles, cambios, comparaciones, tendencias, calendarios y estadísticas. Si cambias la carpeta de datos, pasa `JOBRADAR_HOME` en el campo `env` del servicio.

## Documentación y contribuciones

Puedes añadir fuentes públicas permitidas, corregir fechas, informar de errores reproducibles o mejorar traducciones. Si te resulta útil, una Star o compartirlo ayuda a otros a descubrirlo.

[English guide](README.en.md) · [文档 / Docs](docs/README.md) · [FAQ](docs/FAQ.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

El código usa la licencia MIT. Los textos de ofertas y demás contenido de terceros conservan los derechos de sus titulares; la licencia del código no concede derechos adicionales sobre ese contenido.

<!-- project-growth:start -->

## Evolución del proyecto

El historial de Stars se actualiza a diario. Las fechas de actualización usan UTC; las fechas de Stars siguen los agregados de GitHub. También se muestran las solicitudes diarias de descarga de PyPI.

<a href="https://github.com/lijiaqi-AI-Product-Manager/job_radar/stargazers">
<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/stars-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/stars-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/stars-dark.svg">
  <img src="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/stars-light.svg" width="960" alt="job_radar · Historial de Stars de GitHub">
</picture>
</a>

<a href="https://pypistats.org/packages/jobsearchradar">
<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/downloads-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/downloads-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/downloads-dark.svg">
  <img src="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/downloads-light.svg" width="960" alt="job_radar · Solicitudes diarias de descarga">
</picture>
</a>

Las solicitudes incluyen accesos repetidos y automatizados; no equivalen a usuarios únicos o activos.

[Fuentes de datos y definición de métricas](https://github.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/blob/main/docs/growth.md)

<!-- project-growth:end -->
