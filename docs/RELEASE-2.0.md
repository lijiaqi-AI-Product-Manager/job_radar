# job_radar 2.0

中国校招、实习、社招岗位与招聘日历的本地数据集。提供可追溯的来源、SQLite 快照、命令行和 MCP 查询工具。

## 包含什么

| 内容 | 规模与能力 |
| :--- | :--- |
| 招聘来源 | 2,242 个启用源、2,201 家配置公司、27 个适配器 |
| 岗位快照 | 294,483 条总记录，其中 276,008 条在招记录 |
| JD 正文 | 已核验快照中，在招正文覆盖率 97.3% |
| 招聘日历 | 4,874 条发布样本，含 2,078 条人工整理记录 |
| 本地查询 | 公司、城市、职类、招聘类型、届次与 JD 文本筛选 |
| 工作流接口 | JSON / 表格 CLI、9 个 MCP 工具、状态和变更历史 |

配置统计日期为 **2026-10-31**；岗位快照截至 **2026-10-29T23:17:25Z**。这些是有日期的已核验数量，当前规模以最新数据发布为准。核心目标配置覆盖为 **931 / 1,655（56.25%）**，不等同于当天在招。

## 开始使用

```bash
pip install --upgrade jobsearchradar
jobradar update
jobradar search --company 复星医药 --type campus --grad-year 2027 --table
```

需要 MCP 时安装 `jobsearchradar[mcp]`，在客户端中以 stdio 运行 `jobradar-mcp`。完整示例见 [项目首页](../README.md)。PyPI 的实际可用版本以包索引为准；也可从本版本 GitHub Release 下载 wheel 安装。

## 数据与兼容

- `v2.0.0` 是代码版本；`data-latest` 和 `data-archive` 继续独立分发 SQLite 数据。
- 新版客户端在本地建立 FTS5 trigram 索引，长关键词保留字面子串匹配，短词回退 LIKE。
- 首次构建约 29 万岗位样本的索引，本机约需 1 分钟并额外占用约 199 MB；实际依硬件和数据变化。
- 公开库继续采用既有兼容格式，导出不会改变采集工作库。
- 官方来源、聚合来源、招聘简章与单个岗位分别标注；未知日期留空，投递前回到原始页面确认。

## 文档与质量

八种语言的使用指南、真实查询演示、目录内容说明、来源证据与贡献模板随源码提供。发布前验证 1,039 项离线测试，并检查跨平台兼容、数据导出、文档链接和安装包。

[覆盖口径](COVERAGE.md) · [字段说明](../skill/jobradar/references/fields.md) · [发布兼容](RELEASE.md) · [贡献指南](../CONTRIBUTING.md)

## English

China recruitment data and calendars, distributed as local SQLite snapshots. Version 2.0 includes a CLI, nine MCP tools, 27 adapters, traceable source metadata and eight language guides. Counts above refer to dated verified snapshots, not live hiring totals. Code and data releases remain separate.
