---
description: 新增一个适配器（一个适配器一个会话）。用法：/new-adapter <adapter_id>
argument-hint: <adapter_id，如 moka>
---

为适配器 `$ARGUMENTS` 完成以下工作。严格遵守 CLAUDE.md 的全部铁律。

1. 读 `CLAUDE.md` 和 `docs/recon/` 下与 `$ARGUMENTS` 对应的侦察文档。若不存在、或结论不是"可做"、或合规信息不全：**停止**，告诉用户需要先做侦察（`/recon`），不要继续。
2. 读 `src/jobradar/adapters/example.py`、`tests/adapters/test_example.py`、`tests/test_adapter_contract.py`，把它们当作模板与契约。
3. 在 `sources/` 中加入该适配器的源条目（填真实 compliance）。
4. 运行 `uv run python scripts/record_fixtures.py <source_id> --max-pages 2` 录制 fixtures；检查体积与敏感信息，必要时裁剪（保留一条完整记录、一条缺字段记录、末页空页）。
5. **先写** `tests/adapters/test_$ARGUMENTS.py`，运行并确认失败。
6. 复制 `example.py` 为 `src/jobradar/adapters/$ARGUMENTS.py` 并实现，直到测试通过。
7. 运行 `uv run pytest` 与 `uv run ruff check . --fix`，全绿后提交（信息格式 `adapter($ARGUMENTS): ...`）。
8. 最后汇报：覆盖的公司/租户数、抓到的岗位数、校招特有字段（届别、批次）是否拿到、已知缺口、下一步建议。

不要做：改 schema / models / ingest 规则；引入新依赖；顺手重构其他适配器。需要时先问用户。
