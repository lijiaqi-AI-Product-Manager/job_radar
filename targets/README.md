# 企业目标与覆盖证据

**核心目标 1,655 家 · 当前配置覆盖 931 家 · 2026-10-31**

目标池为覆盖统计提供固定分母。来源线索、已核实来源与当前在招记录分别维护，不能相互替代。

| 文件 | 内容 |
| :--- | :--- |
| `top_companies.yaml` | 核心企业目标、行业 / 地区分组与受限记录 |
| `industry_targets.yaml` | 365 行行业细分的代表企业池 |
| `industries.yaml` | 行业分类资料 |
| `mega_companies.yaml` | 扩展企业目标资料 |
| `coverage_evidence.yaml` | 可复算的最小公开入口证据 |
| `source_checks.yaml` | 当前来源样本、核查时间与记录类型 |

核心池 **931 / 1,655（56.25%）**，官方优先归类 606 家、仅聚合覆盖 325 家；停用源不计入覆盖，受限目标不从分母移除。

复算：`uv run python scripts/coverage_report.py --json`。更多定义与不同目标池的关系见 [覆盖说明](../docs/COVERAGE.md)。
