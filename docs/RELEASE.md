# 发布检查与数据库兼容

代码回归、数据质量与覆盖目标分别验收。源码检查通过不能代替真实快照检查，也不能证明覆盖率已经达到目标。

## 常规检查

```bash
uv run ruff check .
uv run pytest
uv run python scripts/check_docs_links.py
uv run python scripts/check_compliance.py
uv run python scripts/coverage_report.py --json
uv run python scripts/release_check.py --home <数据目录>
```

真实数据目录需含 `jobs.db`、`jd_text.db` 与 `calendar.db`；缺少数据的 SKIP 不算通过。80% 覆盖独立运行 `scripts/coverage_report.py --json --min-coverage 0.8`，当前为 931/1,655（56.25%），预期退出 1，仍差 393 家。

## 既有质量门禁

门槛定义于 `scripts/release_check.py`，不因文档或界面更新而放宽。

| 项目 | 门槛 |
| :--- | :--- |
| 配置目标覆盖 | 至少 15% 且至少 100 家；这是发布最低门槛 |
| 日历或数据覆盖 | 至少 42% 且至少 300 家 |
| 校园岗城市 | ≥20% |
| 在招 JD 正文 | ≥95% |
| 人工日历至少 7/11 字段 | ≥37% |
| 按公司至少一条完整日历 | ≥60% |
| 日历有城市 | ≥44% |
| 日历至少一端网申日期 | ≥20% |
| 数据结构异常 | 0 |
| 交付物异常 | 0 |
| 发布文档 | README / CHANGELOG / COMPLIANCE / LICENSE 齐全 |

2026-10-31 对公开三库完整副本的核验通过上述门禁，岗位数据截至 `2026-10-29T23:17:25Z`。详细数量与限制见 [覆盖说明](COVERAGE.md)。这不是一次新的全量采集，新增截止日规则需后续成功抓取才会更新公开数据。

## 公开数据库兼容

主分支工作库为 jobs schema 3 / text schema 2，包含本地 FTS5 索引。既有已发布客户端只能读取 jobs 2 / text 1；因此每日发布先生成独立的兼容副本：

```bash
uv run python scripts/export_public_databases.py --home data --out data/public
```

导出使用 SQLite backup 读取工作库副本，去掉可重建的全文索引和相应触发器，恢复公开版本号，执行 VACUUM 与完整性检查，再原子替换输出。岗位、正文与业务事件保留；工作库不改变。未知 schema 拒绝导出，不能静默降级。

`daily.yml` 只上传 `data/public/` 中的岗位与正文数据库，Release 文件名保持不变。日历 schema 不变。新版客户端下载后本地建立全文索引，旧客户端继续读取兼容快照。

## 版本发布

1. 更新 CHANGELOG，记录真实数据检查与独立覆盖结果。
2. 构建 wheel / sdist，确认 sdist 小于 5 MiB，没有缓存、数据库或凭据。
3. 独立环境安装 wheel，验证 CLI / MCP、迁移和包内公司简称映射。
4. 按授权范围提交和推送；GitHub 代码推送、版本 tag、数据 Release 与 PyPI 发布分别处理。
5. 版本唯一来源为 `src/jobradar/__init__.py`。正式发布按 [PyPI 流程](PUBLISHING.md)，完成后验证真实安装、下载与增量更新。

缺失日期、城市、届次或学历保留为空。离线检查不能替代逐站访问规则与当前产出的核实。
