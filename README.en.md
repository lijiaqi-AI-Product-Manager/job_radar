# job_radar · Open dataset of Chinese campus / intern / experienced-hire jobs

[简体中文](README.md) | English | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Русский](README.ru.md)

[![version](https://img.shields.io/badge/version-1.12.1-blue)](CHANGELOG.md)
[![pypi](https://img.shields.io/pypi/v/jobsearchradar)](https://pypi.org/project/jobsearchradar/)
[![ci](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml/badge.svg)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml)
[![data](https://img.shields.io/badge/data-daily-success)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/data-latest)
[![license](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)
[![python](https://img.shields.io/badge/python-3.11%2B-3776ab)](pyproject.toml)

**A job dataset that updates itself every day**: official career sites → daily crawl →
one downloadable SQLite. Ships a CLI, an MCP server and a Skill so AI agents can answer
"who is hiring, for what, until when, where to apply" with no API keys and no server.

![demo](docs/assets/demo-en.gif)

> **Coverage snapshot (2026-10-31)**
> **2,230 enabled sources** (Beisen 1,229 / Dayee 310 / Feishu ATSX 148 / Tupu360 32 / Workday 45 / university boards 109 / Shixiseng 104 / Yunjiuye 107 / others) · **2,189 configured companies** · **26 adapters**
> **1,655 targets** (1,117 in 20 sectors + 808 across 31 provincial regions): **919 covered (55.53%)**, 12 documented as not compliantly reachable; calendar has **1,383 files / 2,078 entries**
> Job counts and field coverage refresh with each daily crawl — see the latest Release for current numbers.
> Counts reflect enabled source configurations, not live hiring. The 80% goal remains open; see [delivery progress](docs/internal/DELIVERY-PROGRESS.md).

## What it is / is not

- ✅ Jobs and JD text from **official** career sites; for companies without a compliant official portal we also read public aggregator channels (Shixiseng, university career boards), always marked grade C and counted separately
- ✅ Full re-crawl daily, history kept (open / close / change events)
- ✅ Recruitment calendar: graduation year, programme type, tracks, application window, cities, apply URL, source
- ❌ Not "every company": 919 of 1,655 targets have an enabled source configuration; 724 await further verification and 12 have documented access restrictions
- ❌ No applications, referrals, interview reports or salary data; no captcha/login/signature bypass

## Quick start

```bash
pip install "jobsearchradar[mcp]"

jobradar update                        # ~67 MB + 100 MB; instant/no-op downloads when already current
jobradar search --company 复星 --type campus --grad-year 2027 --table
```

Behind the Great Firewall, use the Gitee mirror (falls back to GitHub automatically):

```bash
jobradar update --mirror gitee
```

## What you can ask

```bash
jobradar search --text "PyTorch 大模型" --type campus    # full-text search over title + JD
jobradar search --company 腾讯 --city 深圳 --category 算法 --table
jobradar search --company 喜茶 --exclude-store           # drop retail/store roles (~8k rows)
jobradar search --company 星巴克中国 --dedupe            # collapse duplicate requisitions, keeps `variants`
jobradar diff --days 7 --types open
jobradar diff --days 7 --by category --company 腾讯      # company-scoped, not global
jobradar compare 公司A 公司B --category 算法            # side-by-side JD text
jobradar trends 美团 --step-days 7
jobradar show <job_id>
jobradar calendar --group 阿里巴巴 --type 秋招 --table    # readable calendar output
```

If a company has no job rows but does have calendar entries (ByteDance, Huawei, Xiaomi…),
`search` returns a `calendar` block pointing at `jobradar calendar --group <name> --table`
instead of just "no data", plus the required `{company}希望你去他们的招聘页逛一逛哦~` note.

## For AI agents

- **Claude Code**: copy `skill/jobradar/` into `~/.claude/skills/jobradar/`; the agent queries via CLI and
  follows the answer rules (cite `data_as_of`, attach URLs, never claim "not hiring" when `company_match=none`).
- **MCP clients** (Claude Desktop, Cursor…): command `jobradar-mcp` (stdio), 9 tools.
  If your data lives outside `~/.cache/jobradar`, pass `JOBRADAR_HOME` in the MCP `env` block.
- Or use it as a library: `from jobradar.core import queries`.

## Files & freshness

| Asset (Release `data-latest`) | Size | Content |
|---|---|---|
| `jobs.db.gz` | ~67 MB | jobs, companies, events, source status |
| `jd_text.db.gz` | ~100 MB | JD responsibilities & requirements (full-text) |
| `calendar.db.gz` | ~1.1 MB | recruitment calendar, 1,655 targets |
| `crawl-summary.json` | 32 KB | per-source status, opened/closed counts |

- Crawl runs daily at **19:17 UTC** (03:17 Beijing); Gitee mirror syncs the same day
- Explicit deadlines use the Beijing calendar date; otherwise a job closes after **3 consecutive successful crawls without it**. Failed crawls never close jobs
- The first upgrade builds FTS5 indexes automatically. A local 294k-job snapshot took about one minute and added about 199 MB across the databases; two-character terms still use LIKE. See [validation details](docs/internal/DELIVERY-PROGRESS.md)

## Known limits (honest version)

| Area | Reality |
|---|---|
| Target coverage | **919/1,655 (55.53%)**; 12 are robots/login/encryption-blocked (evidence in `docs/internal/COVERAGE-PLAN.md`) |
| Sources | **2,230 sources / 2,189 companies**: Beisen 1,229, Dayee 310, Feishu ATSX 148, Tupu360 32, legacy Beisen 113, Workday 45, legacy Dayee 15, plus university boards, aggregators and bespoke sites |
| Provincial configuration coverage | Guangdong 35/49 (71%), Zhejiang 25/44 (57%), Jiangsu 16/34 (47%), Sichuan 15/30 (50%), Shandong 15/26 (58%); full table via `scripts/coverage_report.py` |
| Big tech | Alibaba/Tencent/Meituan/NetEase/Baidu/JD/ByteDance/vivo/Chery/CICC/BOE/Hisense/PICC have job data; Huawei is calendar-only (WAF 403) |
| JD text | Release data as of 2026-10-29T23:17:25Z: 97.3% of 276,008 open jobs have text |
| Calendar fields | Same Release: 93.0% of entries carry ≥7 of 11 fields; 94.0% by group; 85.2% of hand-curated entries |
| Application windows | 45.1% of campus activities have at least one date endpoint (39.2% across all entries); this does not measure complete windows. Missing dates remain missing |
| Duplicates | 2026-10-26 snapshot: 9.2% are same company+title+city requisitions; use `--dedupe` |
| History | accumulating since 2026-10-19; trend answers use the actual span in the database |

Never done: collection prohibited by robots, terms, or access controls; mislabeling aggregators as official; captcha/login/signature bypass, UA spoofing, LLMs in the pipeline,
persisted credentials. See [COMPLIANCE.md](COMPLIANCE.md).

## Contributing

```bash
uv sync --all-extras
uv run pytest                              # regression suite
uv run ruff check .
uv run python scripts/check_docs_links.py  # docs links / version / install-claim consistency
uv run python scripts/check_compliance.py  # offline source / fixture / evidence checks
uv run python scripts/coverage_report.py --json --min-coverage 0.8  # goal gate, currently fails
uv run python scripts/release_check.py --home ~/.jobradar   # 11 legacy release gates
```

Architecture, naming rules and the adapter workflow live in [CLAUDE.md](CLAUDE.md);
internal process docs (milestones, progress notes, review triage, coverage plan) are under
[docs/internal/](docs/internal/).

## Docs

[FAQ](docs/FAQ.md) · [Release gates](docs/RELEASE.md) · [Calendar format](docs/CALENDAR-FORMAT.md) ·
[Publishing](docs/PUBLISHING.md) · [Data license draft](docs/DATA-LICENSE.md) · [Changelog](CHANGELOG.md) ·
[Docs index](docs/README.md)
