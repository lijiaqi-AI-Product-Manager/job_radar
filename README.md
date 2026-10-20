# job_radar

每日自动更新、带历史沉淀的中国校招/实习/社招岗位开放数据集，并配套 CLI / MCP / Skill，让 AI agent（Claude Code 等）能直接回答：

- "腾讯这周新开了什么岗？"
- "阿里和字节的算法岗要求有什么差异？"

零服务器：采集跑在 GitHub Actions，数据发布到 Release，用户在本地查询。

> **状态：工程底座完成，数据采集与 agent 接口尚在建设中。** 见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## 文档

- [CLAUDE.md](CLAUDE.md) — 施工规范（用 Claude Code 开发请先读）
- [docs/ROADMAP.md](docs/ROADMAP.md) — 路线图
- [docs/recon/](docs/recon/) — 数据源侦察
- [COMPLIANCE.md](COMPLIANCE.md) — 合规政策
- [evals/](evals/) — 评测集

## 开发

```bash
uv sync
uv run pytest
```

在 Claude Code 中：`/recon <name> <url>` 侦察数据源；`/new-adapter <id>` 新增适配器。
