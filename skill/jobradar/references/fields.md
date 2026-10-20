# 字段说明

所有查询输出都是：

```json
{"data_as_of": "2026-10-20T03:00:00Z", "stale": false, "...": "...", "results": [...]}
```

- `data_as_of`：最近一次成功抓取的时间（UTC）。回答时换算成北京时间更友好（+8 小时）。
- `stale`：数据超过 48 小时未更新。

## 岗位（search / show / compare 的元素）

| 字段 | 含义 |
|---|---|
| `id` | 岗位唯一 id，`show` 用它 |
| `company` | 公司名 |
| `title` | 岗位名称（原文） |
| `url` | 官方岗位页面链接 |
| `recruit_type` | `campus` 校招 / `intern` 实习 / `social` 社招 |
| `grad_year` | 届别，如 2027；可能为空 |
| `batch` | 批次，如 提前批/正式批/补录；可能为空 |
| `cities` | 工作城市列表 |
| `category` / `subcategory` | 职类（归一化后）；可能为空，此时以 `title` 判断 |
| `degree_min` | 最低学历要求；可能为空 |
| `department` | 部门/事业群 |
| `first_seen` | 第一次被抓到的时间（≈发布时间，但不等于官方发布日期） |
| `last_seen` | 最后一次确认在招的时间 |
| `closed_at` | 下架时间；为空表示仍在招 |
| `description` / `requirements` | JD 原文（需 `update --with-text`） |

## 变化（diff）

| 字段 | 含义 |
|---|---|
| `type` | `open` 新开 / `close` 下架 / `change` 内容变更 / `reopen` 重新开放 |
| `ts` | 发现变化的时间 |
| `diff.fields` | change 时变化的字段名；`["text"]` 表示只有 JD 原文变了 |

注意：下架判定需要岗位在连续 3 次成功抓取中都缺席，所以"下架时间"比实际下架晚 1–3 天。

## 趋势（trends）

`[{"date": "2026-10-01", "open": 120}, ...]`：每个采样日的在招岗位数。最早日期 = 该公司数据开始积累的日期。
