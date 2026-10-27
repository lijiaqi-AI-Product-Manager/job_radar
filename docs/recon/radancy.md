# Radancy / TalentBrew 招聘站侦察

侦察时间：**2026-10-26 15:56–16:10 CST**。

## 结论先说（含否决项）

| 站点 | robots.txt | 判定 |
|---|---|---|
| `jobs.sanofi.cn` | `User-agent: *` / `Disallow:/求职/` | ✅ **接入**（`/search-jobs` 不在 Disallow 内） |
| `careers.loreal.com` | `Disallow: /search-jobs` `/location/` `/category/` `/employment/` | ❌ 否决：列表页所有入口都被禁 |
| `careers.unilever.com` | `Disallow:/search-jobs/` | ❌ 否决 |
| `www.ikea.cn/.../search-jobs` | 404 | ❌ 站点已改版 |
| `careers.astrazeneca.cn` | 域名不存在 | ❌ |
| `www.continental.com/zh-cn/career` | 302 到 `continental-tires.cn` | ❌ 已迁站 |

> **教训（这一轮最重要的一条）**：radancy 的 robots 是**逐条 Disallow 前缀**，不是一句话。
> 第一次我只看到 `Disallow: /search-jobs`，就以为 `/en/location/…` 是「合规的替代入口」，
> 还把 351 个岗位抓了下来。回头把 robots 全文读完才发现 `/location/` 也在 Disallow 里。
> 抓取前的 robots 检查必须是**读全文 + 逐条比对实际请求路径**，不能只看第一条。

## 打通的那一个：赛诺菲 `jobs.sanofi.cn`

### 列表

```
GET https://jobs.sanofi.cn/search-jobs
GET https://jobs.sanofi.cn/search-jobs?p=2      # 分页就是 ?p=N，N 从 2 开始
```

页面里一个 `section#search-results` 携带全部分页元信息：

```html
<section id="search-results"
         data-total-results="971" data-total-job-results="971"
         data-total-pages="65" data-current-page="1" data-records-per-page="15"
         data-ajax-url="/search-jobs/results" data-ajax-post-url="/search-jobs/resultspost">
```

`data-total-pages="65"` × `data-records-per-page="15"` = 971 条，全是中国岗位
（站点本身就是中国站，不需要按国家筛）。列表**不需要**任何参数 —— 不传 `keyword` /
`location` 就是全量。

### 卡片（形态 B）

```html
<ul>
  <li>
    <button type="button" class="js-save-job-btn" data-job-id="46350248512" data-org-id="3036">保存</button>
    <a href="/工作/北京/dbu-commercial-intern-天津/3036/46350248512" data-job-id="46350248512">
      <h2>DBU-Commercial Intern-天津</h2>
      <span class="job-location"><strong>地点: </strong>北京, 中国</span>
      <span class="job-category"><strong>类别: </strong>Human Resources</span>
    </a>
  </li>
```

要点：
- 卡片是**裸 `<a>`**，没有 `job-link` class（欧莱雅那种）。所以正则不能锚 class 名。
- `data-job-id` 出现两次（保存按钮 + 链接），必须锚到**带 `<h2>` 的那个 `<a>`**。
- 地点是**中文**（`北京, 中国`），不是欧莱雅那种英文（`Shanghai, Shanghai Municipality`）。

### 详情（这是它最值钱的地方）

```
GET https://jobs.sanofi.cn/工作/北京/dbu-commercial-intern-天津/3036/46350248512
```

详情页头部就有**绝对日期**：

```html
<div class="job-description section7-title" data-job-id="46350248512">
  <h1>DBU-Commercial Intern-天津</h1>
  <span class="job-location job-info">北京, 中国</span>
  <span class="job-type job-info">Apprentice/Intern (Fixed Term)</span>
  <span class="job-date job-info"><b>发布于 &nbsp;</b> Oct. 26, 2026</span>
  <span class="job-end-date job-info"><b>申请截止于 &nbsp;</b> Nov. 30, 2026</span>
```

正文在 `<div class="job-description section7-details">` 里的 `<div class="ats-description">`。

**这是全项目第一个 `apply_end`（申请截止日）100% 的来源。** 对比：
- 大易：有 `publishDate` + `endDate`，但只有一个租户在用；
- 北森：零日期字段；
- 欧莱雅（形态 A）：只有 `Posted 3 days ago` 这种前端相对文案，只能留空。

## 适配器实现

`src/jobradar/adapters/radancy.py` 支持三种详情容器、两种卡片形态、两种分页：

| 维度 | 形态 A（欧莱雅） | 形态 B（赛诺菲） |
|---|---|---|
| 卡片 | `<a class="job-link"><h3>` | `<a data-job-id><h2>` |
| 地点 | 英文 `Shanghai, Shanghai Municipality` | 中文 `北京, 中国` |
| 详情正文 | `<section id="anchor-job-description">` / `<div class="job-description"><div class="ats-description">` | `<div class="job-description section7-details">` |
| 日期 | 只有相对文案 | **绝对日期 + 截止日** |
| 分页 | `?p=N`；`/location/…/2/{page}` 也有但被 robots 禁 | `?p=N` |

统一处理：
- `_en_date()` 把 `Oct. 26, 2026` 解析成 `2026-10-26`；解析不出来返回 `None`，**不猜**。
- `_cities()` 英文段走 `city_from_english`，中文段走 `cities_from_text`，并用 `_NOT_CITIES`
  过滤掉 `中国` / `印度` / `全国` 这类非城市词（实测不过滤时 15 条岗位全带「中国」）。
- `recruit_type_of()` 默认社招，标题或 `job-type` 里明写 intern/trainee/apprentice 才改实习。

## 这个平台还剩什么

Radancy 服务大量欧洲跨国企业（达能、雀巢、联合利华、宜家、阿斯利康、大陆、拜耳…），
但**逐家 robots 都要读全文**。可复用的验证脚本思路：

1. `GET {base}/robots.txt`，把每条 `Disallow` 收进一个列表；
2. 枚举候选列表路径（`/search-jobs`、`/en/search-jobs`、`/search-jobs/{Country}`、`/en/location/…`）；
3. 任一候选路径 `startswith` 任一条 Disallow → 丢弃；
4. 剩下的路径 GET 一次，`200` 且含 `data-job-id` → 可用。

这一步没写成脚本，因为命中率低（4 个候选里 0 个全通过），人工读 robots 更快。

---

## 追加侦察：2026-10-26 16:50–17:05 CST — 阿斯利康（形态 D）

### 怎么找到的

全球站 `careers.astrazeneca.com/search-jobs` 有 822 个岗位、`data-total-pages="55"`，
但 `country` facet 里只有 `Hong Kong, China (4)` 和 `Taiwan, China (11)` —— **没有大陆**。
在列表页 HTML 里翻到一处官方自己挂的入口：

```html
<div class="china-jobs">
  <a title="Looking for roles in China? Click here"
     href="https://job-search.astrazeneca.cn/china-jobs">Looking for roles in China? Click here</a>
</div>
```

这就是中国站的入口。不是猜域名，是站点自己写出来的。

### robots

```txt
User-agent: *
```

只有一行，没有任何 Disallow。`job-search.astrazeneca.cn/robots.txt` 与
`careers.astrazeneca.com/robots.txt` 都是这个内容。

> 对照教训：radancy 平台上不同租户的 robots 差别极大 —— 欧莱雅逐条禁了所有列表入口、
> 联合利华禁 `/search-jobs/`、赛诺菲只禁 `/求职/`、阿斯利康全球站与中国站都是全开。
> **必须一家一家读，不能因为「同一个平台」就套用结论。**

### 列表

```
GET https://job-search.astrazeneca.cn/china-jobs        302 → /求职?acm=ALL&alrpm=1814991&…&p=1
GET https://job-search.astrazeneca.cn/china-jobs?p=2
```

`data-total-results="279"` / `data-total-pages="19"` / `data-records-per-page="15"`。
`alrpm=1814991` 就是「中国」这个国家 facet 的 id（在全球站里查到的 `data-id="1814991"` 同样是
`data-display="China"`，两个站共用同一套 facet id）。

### 形态 D 的三处差异（相对赛诺菲的形态 B）

| 维度 | 形态 B（赛诺菲） | 形态 D（阿斯利康） |
|---|---|---|
| 卡片标题位置 | `<a data-job-id><h2>` 紧邻 | 中间夹 `<div class="brand-logo-wrapper"><img></div>` |
| 正文位置 | `div.job-description.section7-details > div.ats-description` | `section.job-description > div.details-and-apply-button`（工具栏）**之后**才是 `div.ats-description` |
| 日期格式 | `Oct. 26, 2026` | `07/07/2026`（MM/DD/YYYY） |
| 地点串 | `北京, 中国` | `上海 上海` / `江苏 无锡`（省市用空格分隔）；多地点时写 `Multiple locations` |
| 截止日 | 有 `span.job-end-date` | **没有** |

正则在 `src/jobradar/adapters/radancy.py`：
- `CARD` 用 `(?:(?!</a>).)*?<h[1-3]` 跨过 logo div（旧的 `>\s*<h` 在这里 0/15 命中）
- `DESC_SECTION` 定位整个 `<section class="job-description">`，再 `ATS_INNER` 抽里面第一段 `ats-description`
- `TRAILING_DATE` 加 `\d{1,2}/\d{1,2}/\d{4}` 分支

### 全量结果（2026-10-26 17:10 实测，279 条）

| 字段 | 覆盖率 |
|---|---|
| 标题 | 279/279 **100%** |
| 城市 | 278/279 **99.6%** |
| 发布日期 | 279/279 **100%** |
| 申请截止日 | 0/279（站点无此字段） |
| JD 正文 | 279/279 **100%**（中位数 2751 字，最长 13328 字） |

城市那一层：列表写 `Multiple locations` 的卡片，URL 路径里的城市段
（`/工作/上海/slug/12977/94245123536`）才是真值。只靠列表地点会漏 29 条（89.6%），
加上 URL 兜底后到 99.6%。

> 日期那 100% 要留个心眼：`07/07/2026` 是站点声明 `DisplayJobDateFormat` 的 MM/DD 解读。
> 若哪天出现 `13/05/2026` 这种首段 >12 的，说明站点改了格式，`_en_date` 会返回 `2026-13-05` 这种非法值 ——
> 已由 `test_us_date_format_is_parsed` 锁住常见形态，但跨年那一批需要人工抽查一次。

## 追加侦察：2026-10-26 17:08–17:35 CST — 第二次全量暴露的三个坑

赛诺菲第一次全量（17:05）报「城市/日期/截止日/JD 四项 100%」。第二次全量（17:08）只拿到
978 岗、城市 945/978（96.6%）、发布日期 976/978。逐条排查后定位到三个**独立的**缺陷，
前两个是我自己的代码，第三个是站点行为：

### 坑 1：`_cities()` 的分段变量没重置（会直接抛异常）

```python
for part in parts:
    zh = city_from_english(part)
    if zh:              found = [zh]
    elif 中文:          found = cities_from_text(part)
    elif 大写英文:      found = [...]
    for c in found:     # ← 若三条分支都不命中，found 还是**上一轮**的值
```

`city_from_english("verna")` 返回 None（它是英→中映射表，只收中国城市），
`re.search(中文, "verna")` 不命中，`part[:1].isupper()` 也不成立（URL 路径里是小写）
—— 三个 elif 全落空，`found` 未定义或沿用上一条的记录。**每轮必须重置。**

顺带把「全小写英文地名」补成一条正式分支：URL 兜底路径传进来的是 `verna` 而不是 `Verna`。

### 坑 2：`Multiple locations` 把 URL 兜底短路了

```python
cities = _cities(raw.get("location")) or _city_from_url(raw.get("href"))
```

`_cities("Multiple locations")` 原来返回 `["Multiple locations"]` —— 非空，
`or` 直接短路，URL 里的真值（`/工作/上海/slug/12977/…`）**永远走不到**。
阿斯利康 29/279 条列表地点是占位词，城市覆盖率因此只有 89.6%。

修法：`_cities()` 遇到占位词（`multiple locations` / `various locations` / `各种地点`）
返回空列表，让调用方的 `or` 正常工作。**占位词不是地名，不要在 `_cities` 里给它编一个位置。**

### 坑 3：同一站点的日期格式会**逐条**不同

赛诺菲详情页的发布日期是 `Oct. 26, 2026`（`DisplayJobDateFormat = "MMM. dd, yyyy"`），
但 2026-10-26 17:12 实测有 1 条是 `10月. 25, 2026`：

```html
<span  class="job-date job-info"><b>&#x53D1;&#x5E03;&#x4E8E; &nbsp;</b> 10&#x6708;. 25, 2026</span>
```

`10&#x6708;` 就是「10月」—— 站点的日期文案在个别岗位上被本地化了，而**格式串没变**。
抽样 5 页 75 条里只有 1 条（1.3%），靠"抽查前几条"永远发现不了。
`_en_date()` 补上 `\d{1,2}月\.?\s*\d{1,2},\s*\d{4}` 分支，并对月份/日做范围校验
（`13月. 25, 2026` 返回 None，不能给出 `2026-13-25`）。

> **教训**：判断「字段覆盖率」要看全量，不能看抽样。1.3% 的异常值在全量里就是 13 条丢字段，
> 在抽样里是 0 条。第一次全量报 100%、第二次报 99.8%，差的正好就是这种长尾。

### 修复后复测（`--max-pages 3`，45 条）

```
title       45/45 100.0%
cities      45/45 100.0%
publish_at  45/45 100.0%
apply_end   45/45 100.0%
JD 正文      45/45 100.0%
```

全量复跑结果见 `docs/internal/PROGRESS-2026-10-26.md`。
