# 字段说明

所有查询输出都是：

```json
{"data_as_of": "2026-10-20T03:00:00Z", "stale": false, "...": "...", "results": [...]}
```

- `data_as_of`：最近一次成功抓取的时间（UTC）。回答时换算成北京时间更友好（+8 小时）。
- `stale`：全局数据超过48小时未更新，或本次返回岗位包含超过48小时未确认的来源或岗位观测；来源新鲜不能覆盖岗位自身的陈旧。
- `snapshot_stale`：只判断全局快照是否超过48小时；为`false`而`stale`为`true`时，应核实陈旧岗位的原始链接，不把重复下载同一快照作为恢复证据。
- 岗位的 `source_last_ok` / `source_age_hours` / `source_stale`：对应来源最近成功时间、距今小时数及是否过期；`availability` 区分已下架、已到期、旧来源尚未确认及最近观测，不能作为实时可投保证。
- `last_seen` / `job_age_hours` / `job_stale`：岗位自身最近观测、距今小时数及是否超过48小时。`not_seen_in_latest_success=true`表示最近成功采集中没有再次见到该岗位；`availability=unconfirmed_not_seen`仍保留历史记录，不能直接推定关闭或保证可投。`availability_counts`只汇总返回页；对比时为各家公司返回列表合计，不等于全库分布。
- `text_observed_at`：详情、对比及全文检索所附正文的实际观测时间；为空时不能从 `last_seen` 补成新读正文。按截止日筛选的岗位优先返回更早的明确截止日；不传日期范围时保持最近发现优先。
- `source_enabled`：客户端来源目录中的启用状态，未知为 `null`；`false` 对应 `availability: unconfirmed_disabled`，旧成功记录不能覆盖停用状态。已下架或已到期仍优先显示相应状态。
- `availability_label` / `source_warnings`：中文状态及历史来源限制；`source_tenant_peers`非空表示配置中同一租户还登记在其他来源下，不能将来源数量直接相加。
- `frontline_filter`：校招/实习查询的一线岗位标题过滤模式、排除记录数和计数范围；不修改岗位状态，全文检索未复算数量时为`null`。`include_frontline=true`可主动包含，`exclude_categories`按固定职类字段排除；对比的`company_filters`逐公司返回说明。

## 招聘公告记录

`source_id` 以 `jysd-` 开头的是高校公开招聘公告，属于聚合来源。一条记录可能包含多个岗位，不能把记录数说成单岗数或招聘人数；`company` 保留实际登记主体全名，分公司范围不代表集团全量招聘。标题和正文仍需附原始学校来源链接。

学校的公告过期时间与雇主网申截止日不同，只有明示、唯一的报名截止日才写入 `apply_end`。公告在来源中过期或不可见，不等于该公司所有招聘都结束。城市、学历或截止日缺失时按空值解释。

## 空值怎么理解（很重要，别把"没抓到"说成"没有"）

| 字段 | 空值含义 | 覆盖口径 |
|---|---|---|
| `cities` | 来源未提供可靠工作地 | 本次 `stats.jobs.fields.cities`；校招单列 `campus_cities` |
| `grad_year` | 来源没有唯一可靠届次；多届、范围或否定也可能留空 | 本次 `stats.jobs.fields.grad_year`；校招单列 `campus_grad_year` |
| `category` | 标题规则未能归类 | 本次 `stats.jobs.fields.category`；不等于没有相关岗位 |
| `batch` | 来源没区分批次 | 常见于社招与部分校招 |
| `degree_min` | 未得到四档内的可靠学历值，或平台只写不限/更低学历 | 本次 `stats.jobs.fields.degree_min`；有值也需检查正文冲突 |

`degree_min` 的取值只有四档：`大专` / `本科` / `硕士` / `博士`（2026-10-29 起统一）。
平台原值（"本科及以上""硕士研究生""中技（中专/技校/职高）"等 26 种写法）在入库时已经归一；
低于大专的学历（高中/中专/初中/小学）与"不限"记为空。

回答时的正确姿势：

- 用户问"北京有哪些岗"时，先说明"部分来源不提供城市，结果可能不全"，再给结果；
- 不要因为 `cities` 为空就断言"该岗位不在北京"——它可能只是来源没写；
- 同理，`grad_year` 为空不等于"不限届别"；
- `degree_min` 为空不等于"不限学历"，只表示"没抓到可信的学历要求"。

## 招聘日历（calendar 的元素）

| 字段 | 含义 |
|---|---|
| `group_name` | 集团名（与 `targets/top_companies.yaml` 一致） |
| `company` / `product` | 具体公司/产品线，可能为空 |
| `project_type` | 提前批/秋招正式批/春招/暑期实习/日常实习/校招/社招… |
| `apply_start` / `apply_end` | 网申起止（来源写明才填，否则为空） |
| `deadline_scope` | `batch` 批次截止 / `job_evidence` 岗位样本日期（不代表整批截止）/ `unknown` 截止日未知 |
| `field_evidence` | 城市、届次、起止日期各自的来源与作用域；补城市不覆盖原截止日证据。旧快照缺少字段证据时按旧来源保守解释 |
| `cities` | 工作城市（同上） |
| `apply_url` | 投递入口（官方招聘站） |
| `jd_status` | `linked`（数据层有 JD）/ `official_page`（有公开 JD 页）/ `blocked`（被挡，只给日历）/ `none` |
| `hint` | `blocked` 时给用户的引导语，回答时**原样**放在最后一句 |
| `source` | `{type, name, url, date}`：官方公众号 / 官网 / 政府平台；第三方日历不采 |
| `origin` | `manual` 人工从官方渠道整理 / `auto` 由岗位数据自动生成 |
| `tracks` | 方向（track 级）：`[{direction, roles}]`，roles 是具体岗位名，可能为空 |
| `open_jobs` | 仅 `auto` 条目：与默认搜索一致，排除已下架及明确截止日已过的岗位；不等于当前实时可投数量 |
| `window_status` / `window_counts` | 指定日期下的完整批次日期窗口或未知；汇总的scope=returned仅指返回页，不等于实时可投数量 |
| `observed_from` / `observed_to` | 仅 `auto` 条目：数据里首次/最近一次看到在招的日期（不是网申起止） |
| `as_of` | 这条信息人工核实/自动生成的日期 |

| 字段 | 含义 |
|---|---|
| `id` | 岗位唯一 id，`show` 用它 |
| `company` | 公司名 |
| `title` | 岗位名称或招聘公告标题（原文） |
| `url` | 可用来源入口；已审核的旧失效路径改为列表入口时另保留 `recorded_url` |
| `recruit_type` | `campus` 校招 / `intern` 实习 / `social` 社招渠道；不等于完整投递资格 |
| `grad_year` | 届别，如 2027；来自明确的平台字段、标题或适配器已经核验的正文规则，不使用通用 JD 规则回填；无法确定则为空 |
| `batch` | 批次，如 提前批/正式批/补录；可能为空 |
| `cities` | 工作城市列表（"北京市-海淀区"归一为"北京"）；来源未提供时，取标题中被分隔符明确隔开的城市名（如"-深圳-""（武汉）"），否则为空 |
| `category` / `subcategory` | 职类（归一化后）；可能为空，此时以 `title` 判断 |
| `degree_min` | 最低学历要求；可能为空 |
| `department` | 部门/事业群 |
| `first_seen` | 数据中第一次观测的时间，不代表企业首次发布时间 |
| `last_seen` | 来源列表最近一次看到记录的时间；是否可投还需结合截止日与下架状态 |
| `text_observed_at` | `show` 的正文观测批次时间；复用原文时保留旧值，不等于列表刷新时间 |
| `closed_at` | 已观测到的下架时间；为空只表示尚未确认下架，需结合截止日期及来源新鲜度 |
| `description` / `requirements` | JD 原文（职责 / 要求）；`search --text` 全文检索 |
| `match` | 仅 `search --text` 返回：JD 原文中命中处的片段（只命中标题时为 null） |
| `qualification_evidence` / `field_warnings` | 平台学历与正文候选证据、冲突提示和正文时间；不改原字段，不保证资格成立 |
| `grad_year_match` | 传届次时区分 `explicit` 与 `unknown`，后者需另行核实 |
| `url_scope` / `url_hint` | `project_listing` 为项目列表，`source_notice` 为公告，`unknown` 为未确认作用域；均不保证已完成投递 |
| `variants` | 折叠组内原记录数；同组正文仍可能不同，不能等同新增机会或招聘人数 |

## 变化（diff）

| 字段 | 含义 |
|---|---|
| `type` | `open` 新开 / `close` 下架 / `change` 内容变更 / `reopen` 重新开放 |
| `ts` | 发现变化的时间 |
| `diff.fields` | change 时变化的字段名；`["text"]` 表示只有 JD 原文变了 |

注意：下架判定需要岗位在连续 3 次成功抓取中都缺席，所以"下架时间"比实际下架晚 1–3 天。

`stats.jobs.jd_observation` 单独报告正文在48小时内的观测数与较早观测数，以及最早/最近的正文观测时间。岗位来源刷新不能替代正文新鲜度；详情应同时查看 `last_seen` 和 `text_observed_at`。

`diff --by category` 不返回事件流，而是聚合结果：`[{"category": "技术", "n": 120}, …]`，按新增数量降序；
没有职类的岗位归到「未分类」。用于回答"最近哪类职位新增最多"。

## 趋势（trends）

`[{"date": "2026-10-01", "open": 120}, ...]`：每个采样日的在招岗位数。最早日期 = 该公司数据开始积累的日期。

## 职类（category / subcategory）

由 `taxonomy/categories.yaml` 按岗位标题规则归类；**没命中规则的岗位职类为空**，查询时请同时用 `--keyword` 按标题关键词搜索，不要因为某职类无结果就断言"没有这类岗位"。

`stats.jobs.category_vocabulary` 是安装包分发的固定词表，不会被平台遗留职类改变；`category_match` 说明精确、别名或未匹配，`matched`列出实际检索值。
财务/会计/审计映射到具体的财务审计，backend/frontend分别映射后端/前端，不自动扩成整个技术或职能大类。

| category | subcategory |
|---|---|
| 管培 | 管培生 |
| 产品 | 产品经理 |
| 项目管理 | 项目管理 |
| 技术 | 算法、芯片/硬件、嵌入式、前端、客户端、测试、数据、运维、安全、后端、软件开发、技术支持 |
| 设计 | 设计 |
| 工程制造 | 汽车工程、工艺/设备、质量、机械/电气、生产 |
| 运营 | 运营 |
| 门店零售 | 门店运营 |
| 市场销售 | 销售、市场 |
| 职能 | 人力、财务审计、法务、采购供应链、行政 |
| 金融 | 投研、银行柜员、保险 |
| 医药 | 医药研发、临床医学、学术推广 |

## `stats` 里几个容易混淆的键

| 键 | 含义 |
|---|---|
| `calendar.calendar_covered` / `calendar_entries_covered` | **有日历条目**的目标公司数，以本次返回为准 |
| `calendar.covered_any` | **有日历条目或有岗位数据**的目标公司数，与岗位数据源配置覆盖分别报告 |
| `calendar.jd_covered` / `jd_page_covered` | 有**公开 JD 页/关联**的公司数，不是岗位比例 |
| `calendar.entries` | 人工条目数 / 数据层自动条目数 |
| `calendar.by_sector` | 按行业的 `targets` / `calendar_covered` / `jd_covered` |
| `jobs.with_jd_text` | **岗位**里有 JD 正文的数量（与上面的「公司数」不是一个量纲） |
