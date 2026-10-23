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
| 校园岗城市覆盖 | ≥ 20% | 用户第一诉求是"某个城市有什么岗"。门槛定为 20%：95% 的校园岗来自北森新版门户，其列表接口 LocNames 恒为空、详情页是无数据的 SPA 壳（2026-10-22 实测 HTML 里连岗位名都没有），60%/25% 在当前数据源结构下不可达。要突破只能逐个租户做浏览器渲染或等官方开接口 |
| JD 正文覆盖 | ≥ 95% | 没有正文就没法对比、没法全文检索 |
| 发布文档 | README/CHANGELOG/COMPLIANCE/LICENSE 齐全 | 正式版要给用户交代许可证与合规边界 |

## 最近一次自检（2026-10-23，数据 as_of 2026-10-23T07:13Z，daily #17）

| 项 | 当前值 | 门槛 | 状态 |
|---|---|---|---|
| 数据源覆盖 | 157 / 500 | ≥150 | **PASS** |
| 日历覆盖 | 494 / 500（blocked 16） | ≥450 | **PASS** |
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
## 延伸目标（未纳入 v1.0 门槛，持续追）

除发布门槛外，还有两个「越高越好」的目标，当前进度与卡点写在这里，避免以后重复摸索：

| 目标 | 现状 | 卡点（2026-10-23 实测） |
|---|---|---|
| 数据源覆盖 ≥450/500 | **157/500** | 剩下的公司绝大多数不用北森/hotjob/Moka 这类可枚举的 ATS：银行券商是自研门户（招商/中信/平安…），央企是加密网关（中国建筑 `hcm_param` 加密）、WAF 412（国家电网/中国石油），外企是 Workday/SuccessFactors。可枚举的通道（北森拼音/英文 slug、hotjob 租户、官网招聘页反查）已经跑过 200+ 组，命中率降到个位数。再加只能一家一家写自研适配器，一家的成本 ≈ 一轮迭代 |
| 校园岗城市 ≥60% | **29.6%** | 城市字段只存在于 hotjob（100% 有）、北森旧版（100% 有）和**部分**北森新版租户（xdf 68%、tigermed 82%、wuxiapptec 70%）；而体量最大的几个新北森租户恰恰没有城市（cherry 2357 岗 9%、picc 2024 岗 24%、chinalife 1824 岗 13%、norinco 1769 岗 2.7%）。北森列表/详情的城市字段已被三次独立验证为空（见 docs/recon/beisen.md §6），所以覆盖率只能靠「多接自带城市的源」慢慢抬 |

结论：这两个数字短期内由**数据源的平台结构**决定，不是解析 bug。要突破 450/60%，
需要逐个攻克自研门户（每家一轮侦察 + 适配器），或用浏览器渲染逐个租户补城市（成本更高）。