# 参与贡献

感谢你愿意帮忙。这个项目的目标是**一份可长期维护、每天自动更新、可被 AI agent 直接查询的中国岗位数据集**，
所以最重要的不是"加了多少源"，而是**每条数据都能追溯到公开来源、不破坏已有行为**。

## 最快上手的三种贡献

| 类型 | 怎么做 | 需要写代码吗 |
|---|---|---|
| 加一家北森门户公司 | 在 `sources/beisen.yaml` 追加一行（`id/company/params.tenant`），跑 `uv run pytest` | 否 |
| 加一家大易（hotjob）公司 | `sources/hotjob.yaml` 或 `sources/hotjob_legacy.yaml` 追加一行 | 否 |
| 加自研站/新平台 | 先写侦察结论到 `docs/recon/<name>.md`，再按 `CLAUDE.md` 的适配器流程实现（必须带 fixtures 与专属测试） | 是 |

## 本地开发

```bash
uv sync --all-extras
uv run pytest                        # 全量测试（提交前必须全绿）
uv run ruff check src tests scripts  # lint
uv run python scripts/smoke_sources.py <source_id>   # 单个源的真实抓取体检
```

## 提交前自查

- [ ] `uv run pytest` 全绿，`uv run ruff check` 无错误
- [ ] 新源有 `compliance` 记录（robots / 条款 / 核查日期），否则模型层会拒绝 `enabled: true`
- [ ] 新适配器有 fixtures（<300KB、无敏感信息）和 `tests/adapters/test_<id>.py`
- [ ] 没改任何已有迁移文件；要改 schema 就新增编号迁移并 `uv run python scripts/update_schema_lock.py`
- [ ] 跑过 `uv run python scripts/release_check.py --home ~/.jobradar`，确认没有把门槛拉红

## 不能做的事（会被直接关闭 PR）

- 绕过验证码 / 登录墙 / 请求签名 / 加密参数；使用代理池或伪造 UA
- 抓取 robots、条款或访问控制禁止的聚合入口，或把聚合来源冒充官方；允许的公开聚合源必须显式标 `source_kind: aggregator` 并附归属与现场验证证据
- 在流水线里调用 LLM 或付费服务
- 把抓到的个人隐私信息（手机号、邮箱）写进 fixtures 或数据集

## 提交信息

`adapter(beisen): 新增某某公司` / `core: ...` / `schema: ...` / `docs: ...` / `calendar: ...`
