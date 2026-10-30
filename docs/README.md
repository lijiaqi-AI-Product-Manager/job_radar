# 文档

这里包含安装查询、数据字段、覆盖口径、来源核验和项目维护文档。按你正在做的事情选择入口。

## 使用数据

| 文档 | 内容 |
| :--- | :--- |
| [2.0 版本说明](RELEASE-2.0.md) | 当前版本的内容、数据规模与使用入口 |
| [快速开始](../README.md#快速开始) | 安装、更新与第一条查询 |
| [常见问题](FAQ.md) | 下载、镜像、空字段、公司匹配与 MCP 排错 |
| [字段说明](../skill/jobradar/references/fields.md) | 岗位、日历和输出字段 |
| [覆盖说明](COVERAGE.md) | 当前规模、固定目标池、记录类型与限制 |
| [日历来源](CALENDAR.md) | 来源分级与招聘入口 |
| [数据使用说明](DATA-LICENSE.md) | 代码许可和第三方内容 |

## 贡献与维护

| 文档 | 内容 |
| :--- | :--- |
| [贡献指南](../CONTRIBUTING.md) | 问题反馈、补源与本地开发 |
| [开发规范](DEVELOPMENT.md) | 架构、数据规则、适配器流程与命名 |
| [侦察索引](recon/README.md) | 平台公开入口、字段与访问证据 |
| [侦察模板](recon/TEMPLATE.md) | 新来源必须核实的内容 |
| [日历格式](CALENDAR-FORMAT.md) | 字段格式与完整度 |
| [发布检查](RELEASE.md) | 回归、真实数据门禁与数据库兼容 |
| [PyPI 发布](PUBLISHING.md) | 版本、构建与 Trusted Publishing |
| [路线图](ROADMAP.md) | 已提供能力与后续方向 |
| [更新日志](../CHANGELOG.md) | 版本行为变化 |
| [合规声明](../COMPLIANCE.md) | 公开访问边界与来源要求 |

[历史记录](internal/)保留当时的工程背景，数值可能已经过时；当前统计以 [覆盖说明](COVERAGE.md) 和可执行报表为准。

## 演示素材

[中英文 GIF 与封面](assets/)由 `scripts/make_assets.py` 生成，数据来自 `docs/assets/demo-data.json` 中保存的真实 CLI 结果节选。生成需要 Pillow 和 CJK 字体，具体运行方式见脚本说明。

文档检查：`uv run python scripts/check_docs_links.py`。
