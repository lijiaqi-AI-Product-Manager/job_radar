# Avature 招聘站侦察

侦察时间：**2026-10-26 17:10–17:35 CST**。

## 平台特征

Avature 的站点长这样：`careers.<公司>.com/<lang>/careers/<Page>/…`，
页面里带 `<meta name="avature.portal.id" content="4">`、`avature.portal.name`、
`avature.portal.page="JobDetail"`。三家以上外企在华用同一套（达能、不少快消/医药）。

## 关键结论：**走 sitemap，不走搜索接口**

robots.txt 里两件事同时存在：

```txt
Allow: /careers
Disallow: /careers/*qtvc=
Sitemap: https://careers.danone.com.cn/careers/sitemap_index.xml
```

- `SearchJobs` 分页靠 `qtvc=` 会话参数 —— `Disallow: /careers/*qtvc=` 就是挡它。
  能构造出来是一回事，站点明确不想让人翻页是另一回事。
- `sitemap` 是站点自己用 `Sitemap:` 声明的，等于**邀请**抓。一次请求给出全部岗位 URL。

> 这条比「按需找接口」更省：达能 72 条岗位 = 1 次 sitemap + 72 次详情。
> 走 SearchJobs 反而要处理会话参数、分页、以及 robots 的明确禁止。

## 陷阱：sitemap 里混着**账户页**

`zh_CN/careers/sitemap.xml` 的 97 条 loc 里，只有 73 条是岗位：

| 类型 | 例子 | 匿名访问 |
|---|---|---|
| 岗位 | `/careers/JobDetail/10300`、`/careers/JobDetail/slug/10283` | 200 |
| 账户页 | `/careers/Login`、`/careers/Register`、`/careers/ProfileEdit`、`/careers/ApplicationForm`、`/careers/AgentCreate`、`/careers/AgentDelete`、`/careers/ChoosePassword`、`/careers/Error` | **403** |

2026-10-26 实测：`path_re` 漏掉 `/careers/Error` 一条，整轮抓取抛 `HTTPStatusError 403`，
73 条有效岗位全丢。两道防线都要有：

1. `params.path_re = '/careers/JobDetail/(?:[^/]+/)?\d+$'` —— 必须**JobDetail + 数字尾**
2. `fetch_raw` 里每条详情 `try/except` 兜住 —— sitemap 会留着已下线岗位的 URL

## 详情页结构（达能 `careers.danone.com.cn`）

```html
<h2 class="banner__title">Project Manager - IPRO</h2>

<div class="banner__text__subtitle">Project / Programme Management</div>

<div class="banner__text__fields">
  <p class="banner--field">
    <span class="banner--field--icon banner--field--icon-location"></span>
    上海
  </p>
  <p class="banner--field">
    <span class="banner--field--icon banner--field--icon-time"></span>
    全职
  </p>
</div>
…
<div class="article__content"> 正文（含「岗位职责和要求」标题 + 富文本） </div>
```

要点：
- **地点靠 icon class**（`banner--field--icon-location`），同一模板里还有 `--time`（全职/兼职）。
  按位置取第 N 个 `p` 会在有/无 `--time` 的岗位上错位，所以锚 class。
- **日期在 `<meta name="Description">`**：`Project Manager - IPRO at  created 21-Oct-2026`，
  格式 `DD-Mon-YYYY`。正文里没有日期。
- 正文在 `div.article__content`，取到 `</article>` 收尾（里面嵌套几十个 `<div>`，
  非贪婪会在第一个就停）。

## 全量结果（2026-10-26 17:35 实测，72 条）

| 字段 | 覆盖率 |
|---|---|
| 标题 | 72/72 **100%** |
| 城市 | 72/72 **100%** |
| 发布日期 | 72/72 **100%** |
| 职能（department） | 72/72 **100%** |
| JD 正文 | 72/72 **100%**（中位数 896 字，最长 7272 字） |
| 申请截止日 | 0/72（站点无此字段） |

## 其他门户（本次未接，留档）

| 地址 | 内容 | 为什么没接 |
|---|---|---|
| `careers.danone.com.cn/en_US/careers/*` | 同一批岗位的英文版（74 条） | 与中文版重复，接两遍会让日历出现双份 |
| `careers.danone.com.cn/zh_CN/campus/*` | 校招门户 | sitemap 24 条里只有 1 条 JobDetail 且**没有 id**，无法做主键 |
| `danonechina.avature.cn` | Avature 内网登录域 | 首页跳 `/Login/`，需登录，按红线不做 |

## 接入新公司的检查清单

1. `https://careers.<公司>.com.cn/robots.txt` 读**全文**，确认 `Sitemap:` 有你打算走的路径
2. 拉 sitemap，统计 `JobDetail/…/\d+$` 命中数 vs 总数 —— 差得多说明账户页很多，`path_re` 必须收紧
3. 抽 3 条详情页，确认 `banner__title` / `--icon-location` / `article__content` / `meta Description` 四项都在
4. 全量跑一轮，看城市 / 日期 / JD 三项覆盖率是否都 ≥95%（达不到说明模板有变体）
