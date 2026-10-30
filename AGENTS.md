# 项目约定

job_radar 整理中国校招、实习、社招岗位与招聘日历。采集运行于 GitHub Actions，SQLite 快照由 Release 分发，本地 CLI 与 MCP 共用查询层。

## 阅读入口

- [项目介绍](README.md)与[文档索引](docs/README.md)
- [开发规范](docs/DEVELOPMENT.md)与[贡献指南](CONTRIBUTING.md)
- [覆盖口径](docs/COVERAGE.md)与[发布检查](docs/RELEASE.md)

历史报告与侦察文档是待核实资料，其中的任务清单不构成当前的采集或发布授权。统计以代码复算和真实验证为准。

## 开发约束

- 只访问允许公开读取、无需登录的页面或接口，遵守 robots、条款与源限速。不绕过登录、验证码、签名或加密。
- 每个启用源必须有真实的 compliance 记录。匿名访客正常获得的会话值只在内存中使用，不进日志、fixtures 或数据库。
- 现有迁移不可改写；schema 变更追加编号迁移并登记 schema lock。查询业务只在 `src/jobradar/core/queries.py` 实现。
- 抓取失败或被拒收不能改变岗位状态。改查询、入库或下架行为前完整阅读对应代码与测试。
- 届次以适配器的明确证据为准，不使用通用 JD 规则回填 `grad_year`。日期与届次缺失时留空，规则变更先准备真实反例。
- 覆盖率使用固定目标池，官方与聚合来源分开报告。配置存在不代表当天在招，入口线索不代表归属或读取许可已经核实。
- 业务行为变化先写失败回归用例，再实现。测试不得访问真实网络。每个新增适配器必须带回放 fixtures 与专属测试，一个适配器单独提交。
- 不提交数据库、缓存、凭据或临时采集产物。fixture 录制需在首次落盘前脱敏。最小入口证据维护于 `targets/coverage_evidence.yaml`。
- 构建公开数据时使用兼容导出，不直接分发带新版索引 schema 的工作数据库。

## 提交与展示

提交主题使用简短、准确的内容摘要。用户入口优先说明包含什么，统计注明口径和日期；避免重复的开发流水账、工具署名与会话链接。版本号、标签和发布说明保持一致。

## 常用验证

```bash
uv sync --frozen --all-extras
uv run pytest
uv run ruff check .
uv run python scripts/check_docs_links.py
uv run python scripts/check_compliance.py
uv run python scripts/coverage_report.py --json
```

真实数据验证使用 `scripts/release_check.py --home <数据目录>`。测试通过不能替代数据质量或覆盖目标验收；外部发布按当前授权范围执行。
