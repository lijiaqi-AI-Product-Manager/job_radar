# job_radar · Open dataset of Chinese campus / intern / experienced-hire jobs

[简体中文](README.md) | English | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Русский](README.ru.md)

[![version](https://img.shields.io/badge/version-1.9.5-blue)](CHANGELOG.md)
[![pypi](https://img.shields.io/pypi/v/jobsearchradar)](https://pypi.org/project/jobsearchradar/)
[![tests](https://img.shields.io/badge/tests-504%20passed-brightgreen)](tests/)
[![data](https://img.shields.io/badge/data-daily-success)](https://github.com/lijiaqimun-coder/job_radar/releases/tag/data-latest)
[![license](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)
[![python](https://img.shields.io/badge/python-3.11%2B-3776ab)](pyproject.toml)

**A job dataset that updates itself every day**: official career sites → daily crawl →
one downloadable SQLite. Ships a CLI, an MCP server and a Skill so AI agents can answer
"who is hiring, for what, until when, where to apply" with no API keys and no server.

![demo](docs/assets/demo-en.gif)

> **Coverage snapshot (2026-10-29)**
> **1,911 sources** (Beisen 1,229 / Dayee 310 / Feishu ATSX 148 / Tupu360 32 / Workday 45 / others) · **1,870 companies** · **23 adapters**
> **1,655 targets** (1,117 in 20 sectors + 808 across 31 provincial regions): **606 covered (37%)**, 12 documented as not compliantly reachable; calendar has **1,383 files / 2,078 entries**
> Job counts and field coverage refresh with each daily crawl — see the latest Release for current numbers.

## What it is / is not

- ✅ Jobs and JD text from **official** career sites (no aggregators)
- ✅ Full re-crawl daily, history kept (open / close / change events)
- ✅ Recruitment calendar: graduation year, programme type, tracks, application window, cities, apply URL, source
- ❌ Not "every company": 577 of the 1,655 targets have a working source; the other 1,078 are listed as pending reconnaissance
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
| `calendar.db.gz` | ~1.1 MB | recruitment calendar, 1,655 targets |
| `crawl-summary.json` | 32 KB | per-source status, opened/closed counts |

- Crawl runs daily at **19:17 UTC** (03:17 Beijing); Gitee mirror syncs the same day
- A job is closed after **3 consecutive successful crawls without it**; crawl failures never close jobs

## Known limits (honest version)

| Area | Reality |
|---|---|
| Target coverage | **606/1,655 (37%)**; 12 are robots/login/encryption-blocked (evidence in `docs/internal/COVERAGE-PLAN.md`) |
| Sources | **1,911 sources / 1,870 companies**: Beisen 1,229, Dayee 310, Feishu ATSX 148, Tupu360 32, legacy Beisen 113, Workday 45, legacy Dayee 15, plus 19 bespoke sites |
| Provincial coverage | Guangdong 18/49 (37%), Zhejiang 13/44 (30%), Jiangsu 9/34 (26%), Sichuan 9/30 (30%), Shandong 7/26 (27%); full table via `scripts/coverage_report.py` |
| Big tech | Alibaba/Tencent/Meituan/NetEase/Baidu/JD/ByteDance/vivo/Chery/CICC/BOE/Hisense/PICC have job data; Huawei is calendar-only (WAF 403) |
| Calendar fields | 2026-10-26 full-crawl snapshot: 74.9% of entries carry ≥7 of 11 required fields; 60.7% by group; 38.0% of hand-curated entries |
| Application windows | weakest field (0.6% full windows on the 2026-10-26 snapshot) — most sites just say "from September"; `apply_end` takes the modal date across requisitions |
| Duplicates | 2026-10-26 snapshot: 9.2% are same company+title+city requisitions; use `--dedupe` |
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
internal process docs (milestones, progress notes, review triage, coverage plan) are under
[docs/internal/](docs/internal/).

## Docs

[FAQ](docs/FAQ.md) · [Release gates](docs/RELEASE.md) · [Calendar format](docs/CALENDAR-FORMAT.md) ·
[Publishing](docs/PUBLISHING.md) · [Data license draft](docs/DATA-LICENSE.md) · [Changelog](CHANGELOG.md) ·
[Docs index](docs/README.md)
