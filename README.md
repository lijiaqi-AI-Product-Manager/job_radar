# job_radar

每日自动更新、带历史沉淀的中国校招/实习/社招岗位开放数据集，配套 CLI / MCP / Skill，让 AI agent（Claude Code 等）能直接回答：

- "复星医药现在有哪些 2027 届校招岗位？"
- "腾讯这周新开了什么岗？"
- "这几家公司的算法岗要求有什么差异？"

数据来自各公司官方招聘页（公开接口、低频、不绕过任何限制，见 [COMPLIANCE.md](COMPLIANCE.md)）。零服务器：采集跑在 GitHub Actions，数据发布到 Release，查询在本地完成。

> **状态：0.9.0（发布候选）。** 231 个数据源、**约 68,800 个在招岗位**、JD 正文覆盖 99.9%；目标公司 **500 家**（含智谱/月之暗面/深度求索/百川/阶跃等 AI 公司），其中日历覆盖 205 家、数据源覆盖 104 家，10 家因 robots/验证码/签名/加密不可合规覆盖（[docs/COVERAGE-PLAN.md](docs/COVERAGE-PLAN.md) 逐家有证据）。
> 最近一次采集 221/221 源成功（后续新增了大华、太平保险、光大证券、新华三、传音、中联重科、歌尔等 10 个源）。v1.0 的门槛与当前进度见 [docs/RELEASE.md](docs/RELEASE.md)，自检命令：`uv run python scripts/release_check.py --home ~/.jobradar`。

## 安装与使用

```bash
pip install "jobradar[mcp] @ git+https://github.com/lijiaqimun-coder/job_radar"
jobradar update                      # 下载最新数据（岗位库 + JD 原文库，压缩传输）
jobradar update --mirror gitee       # 国内网络：走 Gitee 镜像（失败会自动换 GitHub）
jobradar search --company 复星 --type campus --grad-year 2027 --table
jobradar search --text "PyTorch 大模型" --type campus   # 全文检索：标题 + JD 原文
jobradar diff --days 7 --types open
jobradar compare 公司A 公司B --category 算法
```

下载源：默认 GitHub，失败自动换 Gitee；`--mirror gitee` 或环境变量 `JOBRADAR_MIRROR=gitee` 优先走 Gitee，
`JOBRADAR_MIRROR` 也可设为任意 GitHub 加速前缀。仓库已公开，可匿名下载；设置 `GITHUB_TOKEN` 可提高 API 限额（私有镜像仓库仍走该方式）。

### 接入 agent

- **Claude Code（推荐）**：把 `skill/jobradar/` 复制到 `~/.claude/skills/jobradar/`。agent 会通过 CLI 查询，并遵守 skill 里的回答规则（注明数据时间、附链接、不编造）。
- **MCP 客户端**（Claude Desktop、Cursor 等）：配置命令 `jobradar-mcp`（stdio）。

## 数据

| 文件（Release `data-latest`） | 内容 |
|---|---|
| `jobs.db`（`.gz`） | 岗位、变化事件、抓取记录（SQLite） |
| `jd_text.db`（`.gz`） | 岗位职责与要求原文（全文检索用） |

同样的文件每天在采集发布后同步到 Gitee 发行版（国内镜像；上传需要较长时间，通常比 GitHub 晚 1 小时左右更新，同步期间下载会自动回退到 GitHub）。

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
