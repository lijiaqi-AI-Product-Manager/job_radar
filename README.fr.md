# job_radar · Jeu de données ouvert sur l'emploi en Chine (campus, stages, expérimentés)

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | Français | [Deutsch](README.de.md) | [Русский](README.ru.md)

[![version](https://img.shields.io/badge/version-1.3.0-blue)](CHANGELOG.md)
[![pypi](https://img.shields.io/pypi/v/jobsearchradar)](https://pypi.org/project/jobsearchradar/)
[![tests](https://img.shields.io/badge/tests-504%20passed-brightgreen)](tests/)
[![data](https://img.shields.io/badge/data-daily-success)](https://github.com/lijiaqimun-coder/job_radar/releases/tag/data-latest)
[![license](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

**Un jeu de données qui se met à jour chaque jour** : sites carrières officiels → collecte quotidienne →
un SQLite interrogeable localement. CLI, serveur MCP et Skill inclus : un agent IA répond
« qui recrute, quoi, jusqu'à quand, où postuler » sans clé API ni serveur.

![demo](docs/assets/demo-en.gif)

> **Données (2026-10-26)** : **370 sources** · **97 607 offres ouvertes** · **99,8 % avec le texte complet du JD**
> Sur les **1 014 entreprises cibles**, 891 ont un calendrier (264 au niveau de l'offre), 895 au total.

## Ce que c'est / ce que ce n'est pas

- ✅ Offres et texte du JD issus des sites **officiels** (aucun agrégateur tiers)
- ✅ Recollecte complète quotidienne, historique conservé (ouverture, fermeture, changement)
- ✅ Calendrier de recrutement : promotion, type de programme, domaines, fenêtre de candidature, villes, lien, source
- ❌ Pas « toutes les entreprises » : 264 des 1 014 cibles exposent des données par offre
- ❌ Pas de candidature, cooptation, retours d'entretien ni salaires ; aucun contournement de captcha/login/signature

## Démarrage

```bash
# Pas encore sur PyPI (pipeline prêt, voir docs/PUBLISHING.md) — installation depuis les sources :
pip install "jobsearchradar[mcp]"

jobradar update     # ~20 Mo + 35 Mo ; aucun téléchargement si déjà à jour
jobradar search --company 腾讯 --city 深圳 --category 算法 --table
```

Depuis la Chine continentale, utilisez le miroir Gitee (retour automatique vers GitHub en cas d'échec) :

```bash
jobradar update --mirror gitee
```

## Questions possibles

```bash
jobradar search --text "PyTorch 大模型" --type campus   # recherche plein texte titre + JD
jobradar search --company 喜茶 --exclude-store          # exclut les postes en boutique (~8 000)
jobradar search --company 星巴克中国 --dedupe           # regroupe les requisitions en double (variants)
jobradar diff --days 7 --by category --company 腾讯     # nouveautés par entreprise et métier
jobradar calendar --group 阿里巴巴 --type 秋招 --table   # calendrier lisible
```

Si une entreprise n'a pas d'offres mais un calendrier (ByteDance, Huawei, Xiaomi…), `search`
renvoie un bloc `calendar` avec `jobradar calendar --group <entreprise> --table` au lieu de
« aucune donnée », plus la mention `{entreprise}希望你去他们的招聘页逛一逛哦~`.

## Pour les agents IA

- **Claude Code** : copiez `skill/jobradar/` dans `~/.claude/skills/jobradar/`
- **Clients MCP** (Claude Desktop, Cursor…) : commande `jobradar-mcp` (stdio, 9 outils).
  Si vos données ne sont pas dans `~/.cache/jobradar`, passez `JOBRADAR_HOME` dans le bloc `env` MCP
- Utilisable comme bibliothèque : `from jobradar.core import queries`

## Limites connues

| Domaine | Réalité |
|---|---|
| Couverture calendrier | 891/1 014 ; les 17 autres sont bloquées (robots/login/DNS) |
| Couverture par offre | 264/1 014 ; le reste : sites maison ou plateformes chiffrées (Moka, Feishu ATSX) |
| Grandes technologiques | Alibaba/Tencent/Meituan/NetEase… avec offres ; ByteDance/JD/Huawei : calendrier seulement |
| Fenêtres de candidature | 8 entrées sur 1372 (0,6 %) seulement avec début et fin |
| Doublons | 9,2 % même entreprise+titre+ville ; utilisez `--dedupe` |
| Historique | depuis 2026-10-19, les tendances couvrent 5 à 7 jours |

Les documents de processus internes sont dans [docs/internal/](docs/internal/).

## Licence et conformité

Code MIT. Le contenu des offres appartient à leurs auteurs ; ce dépôt ne fait qu'indexer.
Accès aux pages publiques uniquement, ≤1 requête/seconde, sans contourner captcha, login ou signature
([COMPLIANCE.md](COMPLIANCE.md)).
