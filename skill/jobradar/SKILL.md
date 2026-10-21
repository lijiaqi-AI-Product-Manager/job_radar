---
name: jobradar
description: 查询中国公司（含大厂与招聘平台上的公司）当前在招的校招/实习/社招岗位、近期新开/下架变化、岗位要求对比和招聘趋势。用户问"某公司在招什么岗位""这周新开了什么岗""A 和 B 的某类岗位要求有什么差异""某公司招聘是在扩张还是收缩"时使用。数据来自各公司官方招聘页，每日更新，本地查询。
---

# jobradar：中国岗位数据查询

数据在本地 SQLite 中，通过 `jobradar` 命令查询，所有命令输出 JSON。**你只能根据命令返回的数据回答，不能用常识或记忆补充岗位信息。**

## 第一步：检查数据（每次会话第一次使用时）

```bash
jobradar doctor
```

- 没有数据，或 `stale: true` → 先运行 `jobradar update`（同时下载岗位库与 JD 原文库），再继续。
- 用户在国内、下载慢或失败时：`jobradar update --mirror gitee`。
- 没装 `jobradar`：`pip install git+https://github.com/lijiaqimun-coder/job_radar`（或 `uv tool install ...`）。

## 按问题类型选命令

| 用户在问 | 命令 |
|---|---|
| 某公司/城市/职类在招什么 | `jobradar search --company 腾讯 --category 技术 --city 深圳 --type campus --grad-year 2027 --limit 20` |
| 标题关键词 | `jobradar search --keyword 大模型` |
| 按技能/要求找岗位（JD 原文里出现的词） | `jobradar search --text "PyTorch 多模态" --type campus --limit 20`（空格分隔的词须全部出现；结果的 `match` 是命中处原文片段） |
| 某个岗位详情、要求 | `jobradar show <job_id>` |
| 这周/最近新开、下架、变化 | `jobradar diff --days 7 --company 腾讯 --types open` |
| 两家或多家公司同类岗位要求对比 | `jobradar compare 药明康德 正大天晴 --category 算法 --per-company 5`，或按标题关键词 `--keyword 研发` |
| 招聘规模趋势 | `jobradar trends 腾讯 --step-days 7` |
| 数据什么时候更新、哪些源有问题 | `jobradar sources` |

参数说明：`--type` 取 `campus`(校招) / `intern`(实习) / `social`(社招)；`--company` 是名称子串匹配；`--category` 同时匹配大类与子类（如 技术、算法、后端、芯片/硬件、产品经理），可选值见 `references/fields.md`。**职类按标题规则归类，部分岗位为空**：`--category` 无结果时，再用 `--keyword` 按标题关键词查一次（如 `--keyword 研发`），仍无结果再用 `--text` 在 JD 原文里查，三者都无结果才能说"没有"。

## 回答规则（必须遵守）

1. **注明数据时间**：回答开头或结尾写"数据截至 {data_as_of}"。`stale: true` 时明确提醒数据可能过期。
2. **附链接**：列出的每个岗位都附 `url`，引导用户去官网查看和投递。
3. **只用返回的数据**：没查到就说没查到。不编造岗位、薪资、面试难度、往年数据、HC 数量。
4. **查不到时说清楚是哪种情况**：
   - 公司不在库里（`results` 为空，或 `compare` 的 `not_found` 里有它）→ "目前的数据里没有这家公司"，不要说"这家公司没在招"。
   - 岗位 `closed_at` 有值 → "该岗位已于 {closed_at} 下架"。
   - 字段为空（如北森门户的 `cities` 为空列表）→ 说明"数据中未提供该信息"，不要从标题或常识推断。
   - **过滤条件会漏掉字段为空的岗位**：`--grad-year`、`--city`、`--category` 只命中该字段有值的岗位（届别来自标题里写明的年份，很多校招岗位标题不写）。加了这些过滤后结果为 0 或很少时，去掉该过滤再查一次（如只用 `--type campus`），再如实说明"其中 N 个标题写明了 2027 届"。
   - 某公司未收录或只覆盖了部分招聘类型（例如阿里、字节、京东因访问限制未收录）：`jobradar sources` 可看各源；不要因为没查到就说"该公司没有校招"，应说"数据里没有"。
5. **变化类问题用 `diff`/`trends`**，不要拿两次 `search` 结果自己比。说明覆盖的时间跨度；历史不足时如实说（例如"数据从 X 日开始积累"）。
6. **对比类问题**：只依据 `compare` 返回的 `requirements`/`description` 原文；区分"JD 原文写的"与"你的归纳"，引用关键原句。某家 `requirements` 为 `null` 时说明缺少原文。样本有限时（如每家只有 2–3 个岗位）提醒结论的代表性有限。
7. **超出范围的请求**（投递简历、内推、面试评价、薪资）→ 说明本工具不提供，建议去官网或其他渠道。

## 输出建议

- 岗位多时先给数量和分布（按城市/职类），再列最相关的 5–10 个。
- 列表格式：`公司 | 岗位名称 | 城市 | 类型/届别 | 链接`。

更多示例见 `references/examples.md`。
