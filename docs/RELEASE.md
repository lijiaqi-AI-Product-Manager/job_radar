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

真实数据目录需含 `jobs.db`、`jd_text.db` 与 `calendar.db`；缺少数据的 SKIP 不算通过。80% 覆盖独立运行 `scripts/coverage_report.py --json --min-coverage 0.8`，当前为 952/1,655（57.52%），预期退出 1，仍差 372 家。

## 日历定点修正

已审核的截止日撤回清单位于 `calendar/corrections/`。先在下载副本上预演，再加 `--apply`：

```bash
uv run python scripts/apply_calendar_corrections.py --db calendar.db
uv run python scripts/apply_calendar_corrections.py --db calendar.db --apply
```

该工具只撤回清单中旧的人工日期，保留原链接与观测时间；不会覆盖后续重新核实的数据，重复执行不再改动。
`calendar-data-repair` 手动工作流会备份旧日历、修正 GitHub `data-latest` 的日历与压缩包；
它与每日采集共享发布锁，完成后触发国内镜像同步，不重新采集或发布软件包。

## 既有质量门禁

完整读取成功但云端未能复验的来源，可使用手动 `verified-source-recovery` 工作流恢复。输入必须来自相同版本的适配器、固定访问守卫和源限速；登录、验证码、明确禁止读取或不完整分页均不适用。传输文件仅包含脱敏后的标准化岗位与实际观测时间，不包含会话值或原始响应，不提交到 Git。

工作流按本仓库附件ID和SHA-256获取有界输入，验证源配置摘要、主体、类型、链接域名、日期及24小时有效期。较新观测不能被旧结果覆盖；既有骤降保护继续生效，任一源拒收则整批不写入。旧三库先备份，重新构建日历、兼容导出并通过真实数据门禁后，才成套切换公开快照。作业与每日采集共用发布锁；观测时间不会改成导入时间。

定向采集大源时，`daily-crawl` 的 `source_budget_seconds` 可单独延长；默认仍为900秒。延长预算不改变限速、分页范围或失败时保留旧岗位的规则。

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

日历工作库为 schema 2，字段证据保存在独立的 `entry_field_evidence` 表。
公开导出继续标记 calendar schema 1，保留可忽略的证据表；旧客户端读取原表，
新客户端可幂等升级并读取字段证据。每日与修正发布均先兼容导出再上传。

主分支工作库为 jobs schema 3 / text schema 2，包含本地 FTS5 索引。既有已发布客户端只能读取 jobs 2 / text 1；因此每日发布先生成独立的兼容副本：

```bash
uv run python scripts/export_public_databases.py --home data --out data/public
```

导出使用 SQLite backup 读取工作库副本，去掉可重建的全文索引和相应触发器，恢复公开版本号，执行 VACUUM 与完整性检查，再原子替换输出。岗位、正文与业务事件保留；工作库不改变。未知 schema 拒绝导出，不能静默降级。

`daily.yml` 在日历构建、兼容导出和真实质量门禁成功后，上传三库的不可变压缩文件，再原子更新 Release 中的完整性清单。旧文件名继续供历史客户端读取。新版客户端使用清单中的同一代三库；2.1.0 默认直接查询兼容快照，已有全文索引时复用。`update --prepare-index` 可在新快照中准备索引，完成后才切换；准备失败保留原快照。

本地更新使用 `JOBRADAR_HOME/snapshots/<代号>/` 存放成套三库，验证完成后原子切换 `.active.json`。CLI/MCP 的一次查询固定同一代；失败不覆盖已有数据，`doctor` 输出实际 `data_dir`。国内镜像先暂存完整分片，匿名校验每片及整文件的 SHA-256，再切换稳定入口；失败保留上一代。

## 版本发布

1. 更新 CHANGELOG，记录真实数据检查与独立覆盖结果。
2. 构建 wheel / sdist，确认 sdist 小于 5 MiB，没有缓存、数据库或凭据。
3. 独立环境安装 wheel，验证 CLI / MCP、迁移和包内公司简称映射。
4. 按授权范围提交和推送；GitHub 代码推送、版本 tag、数据 Release 与 PyPI 发布分别处理。
5. 版本唯一来源为 `src/jobradar/__init__.py`。正式发布按 [PyPI 流程](PUBLISHING.md)，完成后验证真实安装、下载与增量更新。

缺失日期、城市、届次或学历保留为空。离线检查不能替代逐站访问规则与当前产出的核实。
