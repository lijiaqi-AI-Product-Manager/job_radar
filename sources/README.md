# 招聘数据源

**2,242 个启用源 · 2,201 家配置公司 · 2026-10-31**

这里保存公开招聘来源的 YAML 配置：公司归属、适配器、公开入口、平台参数与访问核查记录。多个公司可以复用同一平台适配器。

| 内容 | 说明 |
| :--- | :--- |
| 官方招聘页 | 公司自有招聘站与共享招聘平台 |
| 公开聚合来源 | 高校就业网、招聘简章等，显式标注为聚合来源 |
| compliance | robots、条款、核查日期与读取边界 |
| enabled | 是否参加实际采集与配置覆盖统计 |

配置覆盖核心目标 **931 / 1,655 家（56.25%）**。启用源不代表当天有岗位，招聘简章也不等于一个独立职位。

```bash
uv run python scripts/coverage_report.py --json
uv run python scripts/check_compliance.py
```

补源前阅读 [贡献指南](../CONTRIBUTING.md)与[开发规范](../docs/DEVELOPMENT.md)。完整统计口径见 [覆盖说明](../docs/COVERAGE.md)。
