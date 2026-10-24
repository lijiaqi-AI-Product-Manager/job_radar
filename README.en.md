# job_radar · Open dataset of Chinese campus / intern / experienced-hire jobs

[简体中文](README.md) | English | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Русский](README.ru.md)

[![version](https://img.shields.io/badge/version-1.1.1-blue)](CHANGELOG.md)
[![pypi](https://img.shields.io/pypi/v/jobsearchradar)](https://pypi.org/project/jobsearchradar/)
[![tests](https://img.shields.io/badge/tests-504%20passed-brightgreen)](tests/)
[![data](https://img.shields.io/badge/data-daily-success)](https://github.com/lijiaqimun-coder/job_radar/releases/tag/data-latest)
[![license](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)
[![python](https://img.shields.io/badge/python-3.11%2B-3776ab)](pyproject.toml)

**A job dataset that updates itself every day**: official career sites → daily crawl →
one downloadable SQLite. Ships a CLI, an MCP server and a Skill so AI agents can answer
"who is hiring, for what, until when, where to apply" with no API keys and no server.

![demo](docs/assets/demo-en.gif)

> **Data snapshot (2026-10-24)**
> **279 sources** · **~88.6k open jobs** (campus ~32k / intern ~5k / experienced ~52k) · **99.8% with full JD text**
> **500 target companies**: 494 have calendar or job coverage (490 with calendar entries, 4 job-data only,
> 6 documented as not compliantly reachable); 161 have job-level data.

## What it is / is not

- ✅ Jobs and JD text from **official** career sites (no aggregators)
- ✅ Full re-crawl daily, history kept (open / close / change events)
- ✅ Recruitment calendar: graduation year, programme type, tracks, application window, cities, apply URL, source
- ❌ Not "every company": only 161 of the 500 targets expose job-level data
- ❌ No applications, referrals, interview reports or salary data; no captcha/login/signature bypass

## Quick start

```bash
pip install "jobsearchradar[mcp]"

jobradar update                        # ~20 MB + 35 MB; instant/no-op downloads when already current
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
| `jobs.db.gz` | 20 MB | jobs, companies, events, source status |
| `jd_text.db.gz` | 35 MB | JD responsibilities & requirements (full-text) |
| `calendar.db.gz` | 300 KB | recruitment calendar, 500 targets |
| `crawl-summary.json` | 32 KB | per-source status, opened/closed counts |

- Crawl runs daily at **19:17 UTC** (03:17 Beijing); Gitee mirror syncs the same day
- A job is closed after **3 consecutive successful crawls without it**; crawl failures never close jobs

## Known limits (honest version)

| Area | Reality |
|---|---|
| Calendar coverage | 494/500; the other 6 are robots/login/DNS-blocked (evidence in `docs/internal/COVERAGE-PLAN.md`) |
| Job-level coverage | 161/500 targets; the rest are bespoke sites or encrypted platforms (Moka, Feishu ATSX) |
| Big tech | Alibaba/Tencent/Meituan/NetEase/vivo/Chery/CICC/BOE have job data; ByteDance/JD/PDD/Huawei are calendar-only (captcha/signature) |
| Calendar fields | 74.9% of entries carry ≥7 of 11 required fields; 60.7% by group; 38.0% of hand-curated entries |
| Application windows | only 8/1372 entries (0.6%) have a full window — most sites just say "from September" |
| Duplicates | 9.2% are same company+title+city requisitions; use `--dedupe` |
| History | accumulating since 2026-10-19, so trend answers are currently 5–7 days long |

Never done: third-party aggregators, captcha/login/signature bypass, UA spoofing, LLMs in the pipeline,
persisted credentials. See [COMPLIANCE.md](COMPLIANCE.md).

## Contributing

```bash
uv sync --all-extras
uv run pytest                              # 504 tests
uv run ruff check .
uv run python scripts/check_docs_links.py  # docs links / version / install-claim consistency
uv run python scripts/release_check.py --home ~/.jobradar   # 8 release gates
```

Architecture, naming rules and the adapter workflow live in [CLAUDE.md](CLAUDE.md);
internal process docs (handover, milestones, review triage, coverage plan) are under
[docs/internal/](docs/internal/).

## Docs

[FAQ](docs/FAQ.md) · [Release gates](docs/RELEASE.md) · [Calendar format](docs/CALENDAR-FORMAT.md) ·
[Publishing](docs/PUBLISHING.md) · [Data license draft](docs/DATA-LICENSE.md) · [Changelog](CHANGELOG.md) ·
[Docs index](docs/README.md)
