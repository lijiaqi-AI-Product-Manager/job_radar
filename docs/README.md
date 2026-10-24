# 文档索引

面向使用者的文档在 `docs/`；**内部过程文档**（阶段验收、交接、评审处置、覆盖计划）在 [internal/](internal/)，
不面向使用者，保留是因为它们记录了决策依据。

| 文档 | 内容 |
|---|---|
| [../README.md](../README.md) | 项目介绍、安装、能问什么、已知限制（8 种语言：`README.<lang>.md`） |
| [FAQ.md](FAQ.md) | 常见问题：空字段、下载慢、`--company` 匹配规则、agent 接入、商用边界 |
| [../CLAUDE.md](../CLAUDE.md) | **施工规范**：铁律、适配器流程、命名规范、完成定义 |
| [CALENDAR-FORMAT.md](CALENDAR-FORMAT.md) | 日历条目字段格式（长期要求）与完整度上限分析 |
| [CALENDAR.md](CALENDAR.md) | 招聘日历入口分级（A/B/C 三档）与来源规则 |
| [RELEASE.md](RELEASE.md) | 发布门槛（release_check 的 8 项 GATES）与最近一次自检 |
| [ROADMAP.md](ROADMAP.md) | 路线图与阶段目标 |
| [PUBLISHING.md](PUBLISHING.md) | 发布到 PyPI（Trusted Publishing 配置与发版流程） |
| [DATA-LICENSE.md](DATA-LICENSE.md) | 数据许可草案（三个方案与建议，待维护者确认） |
| [assets/](assets/) | 演示 GIF（中/英）与 social preview 图（`scripts/make_assets.py` 生成） |
| [recon/](recon/) | 各平台/公司的侦察结论（适配器的唯一输入） |
| [internal/COVERAGE-PLAN.md](internal/COVERAGE-PLAN.md) | 500 家目标公司的覆盖现状、逐家证据、扩源尝试结论 |
| [internal/PROGRESS-2026-10-23.md](internal/PROGRESS-2026-10-23.md) | 2026-10-23 阶段验收（日历字段 + 数据源） |
| [internal/PROGRESS-2026-10-24.md](internal/PROGRESS-2026-10-24.md) | 2026-10-24 阶段验收（PyPI/镜像分片/增量更新/自愈） |
| [internal/REVIEW-TRIAGE-2026-10-24.md](internal/REVIEW-TRIAGE-2026-10-24.md) | 外部评审处置记录：改了什么、换了什么方案、还剩什么 |
| [internal/HANDOVER.md](internal/HANDOVER.md) | 交接说明（2026-10-22 快照） |
| [../evals/](../evals/) | 评测集：查询改动是否变好的客观依据 |
| [../CHANGELOG.md](../CHANGELOG.md) | 版本变更记录 |
| [../COMPLIANCE.md](../COMPLIANCE.md) | 合规声明：只读公开页面、不绕过限制 |

自检：`uv run python scripts/check_docs_links.py`（断链 / 版本号 / 安装说法一致性，CI 会跑）。
