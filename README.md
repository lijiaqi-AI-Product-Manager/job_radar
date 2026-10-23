# job_radar

[![CI](https://github.com/lijiaqimun-coder/job_radar/actions/workflows/ci.yml/badge.svg)](https://github.com/lijiaqimun-coder/job_radar/actions/workflows/ci.yml)
[![daily](https://github.com/lijiaqimun-coder/job_radar/actions/workflows/daily.yml/badge.svg)](https://github.com/lijiaqimun-coder/job_radar/actions/workflows/daily.yml)
[![version](https://img.shields.io/badge/version-1.0.0-blue)](CHANGELOG.md)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)

每日自动更新、带历史沉淀的**中国校招 / 实习 / 社招岗位开放数据集**，配 CLI、MCP 与 Skill，让 AI agent 直接回答：

- 复星医药现在有哪些 2027 届校招岗位？
- 腾讯这周新开了什么岗？
- 这几家公司的算法岗 JD 有什么差异？

采集跑在 GitHub Actions，数据发布到 Release，查询在本地完成——**没有服务器，也不需要 API key**。
数据只来自各公司**官方招聘页**的公开内容，低频、不绕过任何限制（见 [COMPLIANCE.md](COMPLIANCE.md)）。

> **当前数据（2026-10-23 发布）**
> **277 个数据源** · **88,630 个在招岗位**（校园 31,975 / 实习 4,990 / 社招 51,665）· **JD 正文 100%**
> 目标公司 **500 家**：日历覆盖 **494 家**（其余 6 家已注明不可合规覆盖），数据源覆盖 **161 家**，共 271 家公司在库。
> 自检：`uv run python scripts/release_check.py --home ~/.jobradar`（7 项门槛全绿）

## 30 秒上手

```bash
pip install "jobradar[mcp] @ git+https://github.com/lijiaqimun-coder/job_radar"
jobradar update                       # 下载最新数据（约 20 MB + 35 MB，压缩传输）
jobradar search --company 复星 --type campus --grad-year 2027 --table
```

国内网络走镜像（失败会自动回退 GitHub）：

```bash
jobradar update --mirror gitee        # 或 export JOBRADAR_MIRROR=gitee
```

## 能问什么

```bash
jobradar search --text "PyTorch 大模型" --type campus    # 全文检索：标题 + JD 原文
jobradar search --company 腾讯 --city 深圳 --category 算法 --table
jobradar diff --days 7 --types open                     # 近 7 天新开的岗位
jobradar compare 公司A 公司B --category 算法            # 取同类岗位 JD 原文对比
jobradar trends 美团 --step-days 7                      # 在招数量随时间变化
jobradar calendar --group 阿里巴巴 --type 秋招           # 批次、网申时间、投递入口、方向、城市
jobradar show <job_id>                                  # 单岗详情（含 JD 原文）
```

`calendar` 是给「官网能看到岗位、但 JD 接口被验证码/签名挡住」的大厂准备的：只发日历信息（届次、项目类型、方向、城市、投递入口、来源、时间戳），末尾带一句 `{公司名}希望你去他们的招聘页逛一逛哦~`。

## 数据

| 文件（Release `data-latest`） | 大小 | 内容 |
|---|---|---|
| `jobs.db.gz` | 20 MB | 岗位、变化事件（13 万条）、抓取记录（SQLite） |
| `jd_text.db.gz` | 35 MB | 岗位职责与要求原文（全文检索用） |
| `calendar.db.gz` | 300 KB | 招聘日历（500 家目标公司） |
| `crawl-summary.json` | 32 KB | 每个源的状态、新增/下架数 |

- 每日 UTC 22:19 采集，采集完成后自动发布新 Release；**Gitee 镜像**同日同步（上行慢，通常比 GitHub 晚 1 小时，同步期间下载自动回退）
- 下架判定：连续 3 次成功抓取中缺席；抓取失败**不会**导致岗位下架
- 字段说明：[skill/jobradar/references/fields.md](skill/jobradar/references/fields.md)

## 覆盖与已知限制（诚实版）

| 维度 | 现状 |
|---|---|
| 目标公司日历 | 494/500；6 家（BOSS直聘/猎聘/智联/前程无忧/微博/招商蛇口）因 robots/登录墙/域名失效不可合规覆盖，逐家证据见 [docs/COVERAGE-PLAN.md](docs/COVERAGE-PLAN.md) |
| 数据源 | 161/500 家能抓到岗位级数据；其余多为自研站、加密平台（Moka/飞书）或 Workday 之外的外企系统 |
| JD 正文 | 100%（抓不到正文的源不进数据集） |
| 日历字段完整度 | 全部条目 **74.9%** 达到「11 个必填字段里 ≥7 个」，按公司 **60.7%**；纯人工条目 38.0%（原因见 [docs/PROGRESS-2026-10-23.md](docs/PROGRESS-2026-10-23.md)） |
| 网申时间 | 仅约 5% 的官网会公开写起止日期；公众号推文是最可靠来源，但微信对数据中心 IP 返回验证页，故不自动化 |

不做的事：不爬第三方聚合站、不绕过验证码/登录/签名、不伪造 UA、不在流水线里用 LLM、不持久化任何凭据。

## 架构

```
GitHub Actions（每日 UTC 22:19）
  ├─ crawl        277 个源 → 适配器（北森 / 大易 / Workday / 自研站）→ SQLite
  ├─ calendar     日历库：人工条目（A/B/C 三档）+ 数据层自动条目
  ├─ release      打包 gzip 上传 Release data-latest（+ 每周归档）
  └─ mirror       同步到 Gitee 发行版（国内加速）

本地
  jobradar update     ← Release / Gitee（自动回退、gzip 与 SQLite 完整性校验）
  jobradar <query>    ← 纯本地 SQLite 查询（CLI / MCP / Skill 共用同一套查询层）
```

## 接入 agent

- **Claude Code**：把 `skill/jobradar/` 复制到 `~/.claude/skills/jobradar/`，agent 会通过 CLI 查询，并遵守回答规则（注明数据时间、附链接、不编造）
- **MCP 客户端**（Claude Desktop / Cursor 等）：命令填 `jobradar-mcp`（stdio）
- 也可以直接当库用：`from jobradar.core import queries`

## 参与贡献

```bash
uv sync --all-extras
uv run pytest          # 255 个测试函数全绿
uv run ruff check src tests scripts
```

- 新增一家北森门户公司：在 [sources/beisen.yaml](sources/beisen.yaml) 加一行（`id/company/params.tenant`）
- 新增其他平台或自研站：先侦察 → [docs/recon/](docs/recon/)，再按 [CLAUDE.md](CLAUDE.md) 的流程写适配器（必须带 fixtures 与专属测试）
- 想看数据是怎么来的：每个源都有 `compliance` 记录（robots/条款/核查日期），每个回填字段都带来源标注

## 文档

[CLAUDE.md](CLAUDE.md)（施工规范）· [ROADMAP](docs/ROADMAP.md) · [发布门槛](docs/RELEASE.md) · [日历字段规范](docs/CALENDAR-FORMAT.md) · [阶段验收](docs/PROGRESS-2026-10-23.md) · [侦察结论](docs/recon/) · [评测集](evals/) · [CHANGELOG](CHANGELOG.md) · [合规](COMPLIANCE.md)

MIT License
