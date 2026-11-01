# 示例

## "腾讯这周新开了什么岗？"

```bash
jobradar diff --days 7 --company 腾讯 --types open --limit 100
```

回答要点：数据截至时间；新开数量；按职类/城市归纳；列出代表性岗位及链接。若 `results` 为空，先用 `jobradar search --company 腾讯 --limit 1` 查看 `company_match` 与 `empty_reason`，区分未收录、无当前岗位和本次筛选无匹配。

## "阿里和字节的算法岗要求有什么差异？"

```bash
jobradar compare 阿里巴巴 字节跳动 --category 算法 --per-company 8
```

回答结构：
1. 样本说明：每家取了几个岗位、数据截至何时。
2. 共同要求（引用原文关键词）。
3. 差异：分点列出，每点注明"阿里 JD 原文：……" / "字节 JD 原文：……"。
4. 你的归纳（明确标注为归纳），以及样本有限的提醒。

## "某某科技在招什么？"（库里没有）

只有 `company_match.match=none` 才说明该名称未收录；匹配为 exact/alias/contains 但结果为空，只能说明当前筛选无匹配。`compare` 的 `missing_companies`、`no_matching_jobs` 与 `ambiguous_companies` 分别解释，不能仅凭 `not_found` 判断未收录。

列表里的 `returned` 是返回条数，`total` 是本次筛选总记录数；`truncated=true` 表示只返回了样本，不能把样本数当总数。

## 严格比较同一城市、届次和招聘类型

```bash
jobradar compare 腾讯 京东 --category 算法 --city 深圳 --type campus --grad-year 2027 --per-company 3
```

所有条件同时生效；严格结果为空时不能拿放宽条件的记录冒充符合要求。
