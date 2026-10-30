# 维护与发布工具

这里包含数据验证、覆盖统计、样本录制、发布导出、镜像和演示素材生成脚本。

| 任务 | 入口 |
| :--- | :--- |
| 配置覆盖 | `coverage_report.py --json` |
| 离线合规核验 | `check_compliance.py` |
| 文档链接与版本一致性 | `check_docs_links.py` |
| 真实数据质量 | `release_check.py --home <三库目录>` |
| 兼容数据库导出 | `export_public_databases.py --home data --out data/public` |
| 适配器样本录制 | `record_fixtures.py <source_id>` |
| 单源网络体检 | `smoke_sources.py <source_id>` |
| README 封面与 GIF | `make_assets.py`（需要 Pillow 与 CJK 字体） |

在仓库根目录使用 `uv run python scripts/<脚本>`，各脚本的 `--help` 或模块说明列出具体参数。

网络探测、采样与录制前必须先核实来源访问规则。日常用户仅需 [安装和查询命令](../README.md#快速开始)，无需运行维护脚本。
