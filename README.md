# job_radar

每日自动更新、带历史沉淀的中国校招/实习/社招岗位开放数据集，配套 CLI / MCP / Skill，让 AI agent（Claude Code 等）能直接回答：

- "复星医药现在有哪些 2027 届校招岗位？"
- "腾讯这周新开了什么岗？"
- "这几家公司的算法岗要求有什么差异？"

数据来自各公司官方招聘页（公开接口、低频、不绕过任何限制，见 [COMPLIANCE.md](COMPLIANCE.md)）。零服务器：采集跑在 GitHub Actions，数据发布到 Release，查询在本地完成。

> **状态：早期。** 覆盖北森招聘门户上的 131 家公司（中金、招商局、中国人寿、长鑫存储、药明康德、奇瑞、汇川、中国兵器工业、摩尔线程……）与腾讯社招；2026-10-20 实测 104 个源一次抓取 3.3 万岗位、0 失败。覆盖范围见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## 安装与使用

```bash
pip install "jobradar[mcp] @ git+https://github.com/lijiaqimun-coder/job_radar"
jobradar update --with-text          # 下载最新数据（JD 原文库用于岗位对比）
jobradar search --company 复星 --type campus --grad-year 2027 --table
jobradar diff --days 7 --types open
jobradar compare 公司A 公司B --category 算法
```

国内下载慢：设置 `JOBRADAR_MIRROR` 为 GitHub 加速前缀。仓库未公开期间：设置 `GITHUB_TOKEN`（有仓库读权限的 token）后 `update` 会走 API 带鉴权下载。

### 接入 agent

- **Claude Code（推荐）**：把 `skill/jobradar/` 复制到 `~/.claude/skills/jobradar/`。agent 会通过 CLI 查询，并遵守 skill 里的回答规则（注明数据时间、附链接、不编造）。
- **MCP 客户端**（Claude Desktop、Cursor 等）：配置命令 `jobradar-mcp`（stdio）。

## 数据

| 文件（Release `data-latest`） | 内容 |
|---|---|
| `jobs.db` | 岗位、变化事件、抓取记录（SQLite） |
| `jd_text.db` | 岗位描述与要求原文 |

字段说明见 [skill/jobradar/references/fields.md](skill/jobradar/references/fields.md)。下架判定：连续 3 次成功抓取中缺席。

## 参与贡献

新增一家北森门户公司：在 [sources/beisen.yaml](sources/beisen.yaml) 加一行。新增其他来源：先侦察（[docs/recon/](docs/recon/)），再按 [CLAUDE.md](CLAUDE.md) 的流程写适配器。

```bash
uv sync --all-extras
uv run pytest
```

## 文档

[CLAUDE.md](CLAUDE.md)（施工规范）· [ROADMAP](docs/ROADMAP.md) · [侦察](docs/recon/) · [合规](COMPLIANCE.md) · [评测集](evals/)

MIT License
