# 自动检查与离线回放

**1,039 项测试 · 2026-10-31 验证基线**

测试覆盖岗位查询、入库状态、截止日、公司归属、数据库迁移、发布兼容、适配器契约、来源配置与访问边界。

| 路径 | 内容 |
| :--- | :--- |
| `adapters/` | 各平台的字段映射与边界用例 |
| `fixtures/` | 最小化、脱敏的公开响应回放样本 |
| `test_adapter_contract.py` | 所有注册适配器的统一输出契约 |
| `test_ingest.py` / `test_core.py` | 状态事件与查询行为 |
| `test_schema_guard.py` / `test_release_export.py` | 迁移不可变与旧客户端兼容 |

```bash
uv sync --frozen --all-extras
uv run pytest
```

测试不连接真实网络。新增业务规则先补回归；新增适配器必须有专属测试和 fixtures。当前案例数会随版本变化，以实际 pytest 汇总为准。
