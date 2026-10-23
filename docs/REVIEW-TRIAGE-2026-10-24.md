# 外部评审处置记录（2026-10-24）

给「请别的 AI 评审本项目」这件事收个尾：5 份外部评审（打分区间约 3.3–4.2/5）里，
哪些改了、哪些换了方案、哪些不采纳、还有什么仍然开着。

处置原则只有一条：**会让用户得出错误结论的问题优先修**——错答案比没有答案更有害。

## 一、已修（1.0.2）

| # | 评审指出的问题 | 实测确认 | 处置 |
|---|---|---|---|
| 1 | `--company 京东` 返回「京东方」的岗位 | 库里没有京东，`LIKE %京东%` 命中京东方 200+ 行，**且无任何提示** | `resolve_company`：全等 → 简称表 → 唯一子串；只差一个字的前缀延伸不猜。命中方式写进 `company_match`，没确定就 0 条 + 候选 + stderr 说明；新增 `--contains` |
| 2 | `diff --by category --company X` 忽略 `--company` | `new_jobs_by_category` 根本没有 company 参数；腾讯实测全库 14,156 → 实际 1,283 | 加参数并真的过滤，`company_match` 一起回显 |
| 3 | `MAX_REJECTS` 连空结果一起放行 | 连续 3 轮 rejected 后 `reason=None` 无条件执行，源返回 0 条 = 整家公司被洗空 | 空结果永不自动放行；只能由源配置 `params.allow_empty: true` 显式接受（crawl 已接线） |
| 4 | 本地库损坏时裸 traceback（含 `doctor` 之外的命令） | `sqlite3.DatabaseError: file is not a database` 直接抛给用户 | `local.open_db` 统一转成「本地库损坏 → `update --force`」，CLI/MCP 同一套文案；MCP 另加兜底 |
| 5 | `--open-on` 把「没写起止」当「确定可投」 | 1372 条日历里只有 8 条有完整起止，其余被当成"今天还能投" | 条目仍返回（否则等于藏起 99% 校招），但标 `window_status: unknown`；要严格就加 `--has-window` |
| 6 | 空结果没有下一步提示 | agent 把「字段没写」说成「没岗位」 | 空结果新增 `hints`（届别/城市/职类只命中字段有值的岗位；公司名未唯一确定时给候选） |
| 7 | wheel 里没有 `taxonomy/`，简称映射在 pip 安装后失效 | `taxonomy/` 在仓库根，hatch 只打 `src/jobradar` | `force-include` 到 `jobradar/_data/`；单测 + CI 都校验 wheel 内容（本地已 build 验证，1830B 在包内） |
| 8 | README/文档数字与实测不符 | 逐项复核：门槛 7→8、UTC 22:19→19:17、测试 255→491、网申时间「约 5%」→ 0.6%、按公司 60.7% 的分母是 596 不是 500、PyPI 实际 404、`janitor/` 路径不存在 | 全部改成实测值，并在 FAQ 写清「怎么复算」 |
| 9 | 重复岗位 | 实测 8,115/88,608 = **9.2%**（星巴克门店岗一家 2,907 条同标题同城市） | 如实写进「已知限制」（此前完全没提）+ `search --dedupe` 折叠（星巴克实测 2,907 条 → 22 组，带 `variants`）；默认计数口径不变，避免牵动发布门槛。入库层去重单独一轮 |
| 10 | 过期判定两套阈值（36h vs 48h） | `sources` 用 36h、`envelope` 用 48h，同一份数据两个命令可能一个说新鲜、一个说过期 | 统一 48h（连续两个日报周期没成功），加测试钉住「40h 两边都新鲜、50h 两边都过期」 |

对应提交：`edc248b`（代码+测试+打包）、`68f5a3c`（文档）、`5c6c979`（评审处置记录）、
`22a151f`（`--dedupe`）以及本文件所在提交。测试 485 → 492，`ruff check .` 干净。

## 二、换方案处理

| 评审建议 | 为什么没照做 | 实际做法 |
|---|---|---|
| 「JD 里有手机号/邮箱，与 COMPLIANCE 的『不保存个人信息』矛盾」 | 这是**文案**问题不是数据问题：JD 是企业公开的招聘文案，抹掉联系方式会降低实用性（不少岗位就靠邮箱投递） | 改文案：实测 10.5 万份 JD 里 6 份含手机号、45 份含邮箱，原样保存、不单独提取成字段、不用于联系；并指向下线机制 |
| 「去重用 LLM / 相似度聚类」 | 违反项目铁律（流水线不用 LLM、不引入付费服务） | 先把 9.2% 的事实写清楚，下一轮用纯规则的 `(company, title, cities)` 折叠 + `--dedupe` 开关 |
| 「用 LLM 做 JD 字段抽取提高完整度」 | 同上；且会引入不可复现的字段 | 字段拿不到就留空，`hints` 告诉用户怎么绕过 |

## 三、不采纳

| 评审意见 | 理由 |
|---|---|
| 「README 说已发布 PyPI 属于造假，应删除发布流程」 | 虚假陈述是真的（已改成"尚未发布"），但发布流程本身是资产：`publish.yml` 用 OIDC、`docs/PUBLISHING.md` 写了配置步骤，等 `vars.PYPI_ENABLED=true` 即可发 |
| 「`--company` 应保留子串匹配（默认），加提示就够」 | 京东/京东方证明"提示 + 错数据"仍会被 agent 直接采信。默认拒绝猜、`--contains` 显式放开更安全 |
| 「`search --text` 用 LIKE 全表扫太慢，应上 FTS5」 | 认同是性能债，不是正确性问题；上 FTS5 要新迁移 + 重写查询层，排在去重之后 |
| 「500 家目标应全部有岗位级数据」 | 6 家（BOSS直聘/猎聘/智联/前程无忧/微博/招商蛇口）robots/登录墙明令禁止，按铁律不做；证据在 `docs/COVERAGE-PLAN.md` |

## 四、仍然开着（按优先级）

1. **入库层去重**：`--dedupe` 只折叠展示；同一 ATS 多 req 是否在库里并成一条（会改岗位总数与门槛）待定。
2. **性能债**：`--text` 的 `LIKE` 全表扫 + 把 179KB 的 id JSON 塞进 `json_each`；`data_status` 一次返回 67KB。
3. **阈值口径不统一**：`local.STALE_HOURS=48` 与 `data_status(stale_after_hours=36)` 两处判断，`sources` 与 `doctor` 可能给出不同"过期"结论。
4. **`source_run.duration_s` 从没写入**（字段在 schema 里，抓取时长没记）。
5. **`data-archive` 每周 ~82MB 无上限**：需要保留策略（比如只留 8 周）。
6. **PyPI 未发布**（流程就绪，等维护者开 `PYPI_ENABLED`）；`DATA-LICENSE.md` 仍是草案。

## 五、怎么复核

```bash
uv run pytest -q                                   # 491 个测试
uv run ruff check .
uv run python scripts/release_check.py --home ~/.jobradar    # 8 项门槛

# 本轮四个 P0 的现场验证（用真实库）
jobradar search --company 京东            # 0 条 + company_match.candidates=[京东方]
jobradar search --company 京东方          # 正常返回，match=exact
jobradar diff --days 7 --by category --company 腾讯   # 只统计腾讯
jobradar doctor                            # 库损坏时给 advice，不抛 traceback
```
