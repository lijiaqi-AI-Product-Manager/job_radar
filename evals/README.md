# 评测集

用途：每次改 schema、查询层、入库规则或 skill 之后，用同一套问题评估"有没有变好"。**这是判断改动好坏的唯一客观依据**，不靠感觉。

## 两层

**L1 — 查询层黄金测试（确定性，进 CI）**
`tests/test_core.py` + `tests/test_ingest.py` 已覆盖查询与入库规则。Phase 1 有真实数据后，在 `evals/golden/` 放一份固定的小型快照库 + 期望结果，作为回归基线。

**L2 — agent 端到端（`questions.yaml`）**
让 agent 在装好 skill 与数据的环境里回答这些题（当前 30 题），对照 `checks` 判分。Phase 1 完成时补 `facts`（黄金答案要点）与自动判分脚本；此前先人工跑，记录通过率。

## checks 含义

| check | 通过条件 |
|---|---|
| `cite_source` | 每个岗位都附原始链接（`url`） |
| `state_updated_at` | 回答里写明数据截至何时 |
| `only_from_data` | 所有岗位/数字都能在查询结果中找到，没有凭常识补充 |
| `no_fabrication` | 数据里没有的信息（薪资、面试难度、往年数据等）明确说没有，不编造 |
| `say_not_found` | 库里没有该公司/岗位时，明确说"没有数据" |
| `say_not_found_if_missing` | 部分对象缺数据时，逐个说明哪些缺，不拿别的补 |
| `respect_limit` | 遵守数量上限 |
| `use_event_data` | 新增/下架/变化问题使用事件数据（`recent_changes`/`company_trend`），而不是比对两次搜索结果 |
| `use_jd_text_only` | 对比结论仅基于取回的 JD 原文 |
| `separate_quoted_vs_inferred` | 区分"原文写的"与"推断的" |
| `state_data_span` | 说明趋势所覆盖的时间跨度（历史不足时如实说） |
| `distinguish_closed_vs_missing` | 区分"已下架"与"库里没有" |
| `ask_to_update_if_stale` | 数据过期时提示先更新，而不是直接作答 |
| `use_status_data` | 抓取状态问题使用 `data_status` |
| `refuse_out_of_scope` | 超出能力范围（投递、面试评价）时说明做不到，不假装 |

## 判分与记录

- 每题 pass/fail（所有 checks 全过才算 pass）。记录 `通过数/总数` 与失败题 id 到 PR 描述或提交说明。
- 改动前后各跑一次。通过率下降不能合并，除非有明确理由并经用户确认。
- 新增题目：只增不删；删除或放宽 checks 需要用户确认。
