# 参与贡献

欢迎帮助更多人找到可核实的招聘信息。最有价值的贡献，是一条可追溯的公开来源、一次准确的字段修正，或一个能复现的问题。

## 选择一件事开始

| 贡献 | 从哪里开始 |
| :--- | :--- |
| 报告错误日期、公司或链接 | 提交 Issue，附原始来源、数据时间、命令与预期结果 |
| 增加已有平台的公司 | 在 `sources/` 增加配置，核实归属、公开访问规则与当前产出 |
| 支持新平台 | 先读 [开发规范](docs/DEVELOPMENT.md)，按 [侦察模板](docs/recon/TEMPLATE.md) 记录证据 |
| 完善日历 | 按 [日历格式](docs/CALENDAR-FORMAT.md) 保留来源与核查日期 |
| 改善使用体验 | 修复文档、翻译、查询输出或可复现的筛选问题 |

## 本地开发

```bash
git clone https://github.com/lijiaqi-AI-Product-Manager/job_radar.git
cd job_radar
uv sync --frozen --all-extras
uv run pytest
uv run ruff check .
uv run python scripts/check_docs_links.py
uv run python scripts/check_compliance.py
```

测试均为离线回放。真实网络体检使用 `scripts/smoke_sources.py <source_id>`，事先核实公开入口、robots、条款及限速。

## 提交一个容易评审的改动

1. 说明具体问题、触发方式与预期行为。业务变更先补失败回归。
2. 新源附真实 compliance；新适配器附脱敏 fixtures 与专属测试，一个适配器单独提交。
3. 既有迁移保持原样，schema 变更追加迁移并验证旧客户端兼容。
4. 运行相关测试和上述检查。影响数据发布时，再运行 [真实数据与打包检查](docs/RELEASE.md)。
5. 在 PR 中写清变更后的行为、验证结果与已知限制；统计使用 [统一口径](docs/COVERAGE.md)。

提交信息描述改动，例如 `adapter(jysd): add public campus notices`、`core: preserve explicit application deadlines`、`docs: improve quick start`。不添加工具署名或会话链接。

## 来源要求

只读取允许公开访问的内容，固定 UA、遵守限速，不绕过登录、验证码或访问控制。聚合来源显式标注，不能冒充官方。凭据、个人联系方式、数据库和临时采集产物不进入仓库。fixture 必须在首次写入前完成脱敏。

感谢每一位补充来源、提交问题和修正文档的贡献者。
