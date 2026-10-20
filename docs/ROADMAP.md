# 路线图（2 天出初版，2 周发布）

> 状态说明：✅ 已完成　⬜ 未开始。每项都有可验证的完成标准。
> "2 天"的前提是 Phase 0 的侦察结论为"可做"。如果 Moka/北森的接口需要签名/登录，或 GitHub Actions 访问不通，
> 计划作废并立即重新评估——这两件事要在第一个小时内就知道。

## 已完成：工程底座（本分支）

- ✅ schema + 迁移 + 迁移守卫（不可改已有迁移）
- ✅ 入库逻辑 `ingest_run`：新增/变更/下架(连续3次缺席)/重开 + 抓取失败不下架 + 骤降熔断
- ✅ 查询层 `core/queries.py`：search / recent_changes / company_trend / data_status / compare_roles
- ✅ 适配器基类 + 模板 + fixtures 录制/回放 + 契约测试；sources 加载与合规校验
- ✅ 评测题集 24 题；CLAUDE.md / 会话命令 `/recon` `/new-adapter`
- 58 个测试全绿

## Day 1：数据跑起来

| # | 任务 | 完成标准 |
|---|---|---|
| 1 | **Phase 0 侦察（平台优先）**：Moka、北森、gllue（`/recon`），并用 `recon-probe` 工作流测 Actions 可达性 | 每个平台一份 `docs/recon/*.md`，结论明确；租户数量有估计 |
| 2 | 平台适配器 #1（体量最大且结论为"可做"的那个）`/new-adapter` | 契约测试 + 专属测试通过；录到真实 fixtures |
| 3 | 租户清单：把可发现的租户写进 `sources/<平台>.yaml`（一行一家） | 首批 N 家，每家有 compliance；`test_sources` 通过 |
| 4 | **crawl 编排器**：按 sources 并发/限速抓取 → `ingest_run` → 写 `jobs.db`/`jd_text.db` → 失败/熔断记录 | 本地一条命令跑完全量，`data_status` 能看到每源状态 |
| 5 | GitHub Actions 每日定时 + 发布到 Release（`latest`）+ 保活 | 手动触发一次成功，Release 里有两个 db |

## Day 2：agent 能用

| # | 任务 | 完成标准 |
|---|---|---|
| 6 | CLI：`update` `search` `show` `diff` `compare` `trends` `sources` `doctor`（只调 core） | 每个命令有测试；输出带 `url` 与 `updated_at` |
| 7 | Skill：SKILL.md + references（schema、职类、回答模板），回答规则按 `evals/README.md` | 手工跑 24 题，记录通过率 |
| 8 | 平台适配器 #2、再 3–5 家大厂自研站（逐家先侦察） | 契约测试通过 |
| 9 | 首版 README（含一段真实对话演示） | 他人能照着装好并问出第一个问题 |

## Day 3–14：发布前

- 监控：每日健康报告（哪些源挂了/熔断）→ 自动开 issue；`sources` 新增的 PR 校验
- 镜像方案（国内下载）：CLI `--mirror`，至少一个国内可用的数据镜像
- MCP 薄壳（6 个只读工具）
- 职类归一化（`taxonomy/` 规则表，遇不确定留空）
- 趋势与周报（自动生成，作为传播内容）
- 贡献指南 + 新增公司的最短路径（一个 yaml PR）
- 发布前合规复核（COMPLIANCE.md 的许可措辞、LICENSE）

## 不会承诺的

- 具体的 star 数、具体的公司数——取决于侦察结果。
- "每家大厂都能抓"——自研站逐家评估，不可做的明确标注不支持。
