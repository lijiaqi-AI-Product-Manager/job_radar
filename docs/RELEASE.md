# v1.0 发布门槛与自检

这份文件把"能不能发正式版"变成可执行的检查，而不是拍脑袋。

```bash
uv run python scripts/release_check.py --home ~/.jobradar
```

输出逐项 PASS/FAIL，退出码非 0 表示未达标。CI 也可以 nightly 跑一次，提前发现回退。

## 门槛（`scripts/release_check.py` 里的 GATES）

| 项 | 门槛 | 为什么 |
|---|---|---|
| 数据源覆盖 | ≥ 150 / 500 | 有岗位数据的公司才谈得上"岗位查询" |
| 日历覆盖 | ≥ 450 / 500 | 抓不到 JD 的公司也要能告诉用户"去哪投、什么时候" |
| 校园岗城市覆盖 | ≥ 60% | 用户第一诉求是"某个城市有什么岗"；现在只有 18%，是最大硬伤 |
| JD 正文覆盖 | ≥ 95% | 没有正文就没法对比、没法全文检索 |
| 发布文档 | README/CHANGELOG/COMPLIANCE/LICENSE 齐全 | 正式版要给用户交代许可证与合规边界 |

## 最近一次自检（2026-10-22，数据 as_of 2026-10-22T05:08Z）

| 项 | 当前值 | 门槛 | 状态 |
|---|---|---|---|
| 数据源覆盖 | 103 / 500 | ≥150 | FAIL |
| 日历覆盖 | 172 / 500（blocked 10） | ≥450 | FAIL |
| 校园岗城市覆盖 | 18.4% | ≥60% | FAIL |
| JD 正文覆盖 | 99.9% | ≥95% | PASS |
| 发布文档 | 齐全 | 齐全 | PASS |

## 干净环境安装验证（2026-10-22 已通过）

用 uv build 的 wheel 建全新 venv（不依赖仓库），跑完整用户路径：

| 步骤 | 结果 |
|---|---|
| jobradar --version | jobradar 0.9.0 |
| jobradar update | 4.6s，三个库都走 GitHub，data_as_of = 当天 |
| jobradar doctor | jobs/jd_text/calendar 都在，未过期 |
| jobradar search --limit 2 | 正常返回岗位 |
| jobradar calendar --group 京东 | 返回 2 条，含 blocked 提示 |
| jobradar stats | jobs.fields 字段覆盖率正常输出 |

## 发布流程（每次发版）

1. `uv run pytest` + `uv run ruff check .` 全绿；
2. `uv run python scripts/release_check.py --home ~/.jobradar` 全部 PASS；
3. 更新 `CHANGELOG.md`（新增/修复/数据/已知缺口）；
4. 改 `pyproject.toml` 版本号 → `uv build` 确认 sdist < 5MB（CI 已守卫）；
5. `git tag vX.Y.Z && git push origin vX.Y.Z`；
6. 在 GitHub 建 Release，正文用本版 CHANGELOG 段落；
7. 发完后跑一次 `jobradar update` 验证 Release 资产可下载、`doctor` 不报过期。

## 还缺的硬骨头

- **城市**：北森新版列表接口 `LocNames` 恒为空，标题只能补回一部分；要么侦察详情接口，要么在查询结果里显式标注"该来源不含城市"。
- **届次**：校园岗 62.7% 缺失，来源未提供，JD 里也没有（实测 3000 条命中 0）。
- **日历覆盖**：500 家里还有 328 家没有条目，需要逐家找到官方招聘入口（不能猜 URL）。
