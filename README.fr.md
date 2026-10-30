![job_radar](docs/assets/hero-en.svg)

[![PyPI](https://img.shields.io/pypi/v/jobsearchradar?color=58bfa5)](https://pypi.org/project/jobsearchradar/) [![CI](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml/badge.svg)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml) [![Python](https://img.shields.io/badge/python-3.11%2B-7bb7ff)](pyproject.toml) [![MIT](https://img.shields.io/badge/license-MIT-7bb7ff)](LICENSE)

[简体中文](README.md) · [English](README.en.md) · Français

**Les offres d’emploi en Chine, dans une base de données que vous interrogez chez vous.**

Offres publiques pour jeunes diplômés, stages, postes expérimentés et calendriers de recrutement, réunis dans SQLite. Filtrez par entreprise, ville et promotion, recherchez dans les descriptions originales et retrouvez le lien de candidature. CLI et MCP, sans clé API ni serveur à déployer.

## Démarrage rapide

Le paquet PyPI s’appelle `jobsearchradar` ; la commande installée est `jobradar`. Python 3.11+ est requis. Compatible avec Windows, macOS et Linux.

```bash
pip install jobsearchradar
jobradar update
jobradar search --company 复星医药 --type campus --grad-year 2027 --table
```

![job_radar demo](docs/assets/demo-en.gif)

<sub>L’animation présente des extraits de résultats réels. Sa durée ne mesure pas la latence. Vérifiez l’état et les dates sur la page de recrutement d’origine.</sub>

## Exemples de recherche

```bash
jobradar search --text "PyTorch 大模型" --type campus --limit 3 --table
jobradar search --city 上海 --category 算法 --type intern --dedupe --table
jobradar calendar --group 阿里巴巴 --grad-year 2027 --table
jobradar diff --days 7 --types open --table
jobradar doctor
```

`--table` → table · default → JSON · `JOBRADAR_HOME` → data directory

## Données et couverture

2026-10-31 · [Methodology / 统计口径](docs/COVERAGE.md)

| Indicateur | Valeur |
| :--- | ---: |
| Sources actives | 2,242 |
| Entreprises configurées | 2,201 |
| Adaptateurs | 27 |
| Couverture du périmètre fixe d’entreprises cibles | 931 / 1,655 · 56.25% |

L’instantané vérifié du 29 octobre 2026 contient 294 483 enregistrements, dont 276 008 ouverts. Le texte original est disponible pour 97,3 % des enregistrements ouverts. Une source configurée ne signifie pas que l’entreprise recrute aujourd’hui. Une annonce d’agrégateur peut décrire plusieurs postes.

[Latest data release](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/data-latest) · `jobradar stats`

## Connexion MCP

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

Ajoutez `jobradar-mcp` comme service stdio. Neuf outils couvrent recherche, détail, changements, comparaison, tendances, calendriers et statistiques. Pour un répertoire personnalisé, transmettez `JOBRADAR_HOME` dans le champ `env` du service.

## Documentation et contributions

Ajoutez des sources publiques autorisées, corrigez des dates, signalez un problème reproductible ou améliorez les traductions. Une Star ou un partage aide d’autres personnes à découvrir le projet.

[English guide](README.en.md) · [文档 / Docs](docs/README.md) · [FAQ](docs/FAQ.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

Le code est sous licence MIT. Les droits sur les offres et les contenus tiers restent à leurs titulaires ; la licence du code n’accorde aucun droit supplémentaire sur ces contenus.
