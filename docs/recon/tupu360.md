# Tupu360 招聘站侦察（careersite.tupu360.com）

侦察时间：**2026-10-26 15:53–16:05 CST**。样本：西门子 `jobs.siemens.com.cn/siemens`。

## 结论一句话

服务端渲染 HTML，**无登录、无签名、无验证码、无 Cookie**；分页是 `POST …/position/nextPageList`
带 `offset`/`max`，**不是** `?page=N`。这是本项目里少数**列表页就直接带发布日期**的站。

## 站型

| 项 | 值 |
|---|---|
| 平台 | Tupu360 `careersite.tupu360.com`（页面 `staticParams.staticResource` 指向该 CDN） |
| 渲染 | 纯服务端渲染，`<div class="position-item" pid="…" recruitment="…">` |
| 反爬 | 无。裸 UA 直接 200 |
| robots | `https://jobs.siemens.com.cn/robots.txt` → **404**（nginx 默认页），无规则可依 |

## 列表页

```
GET /{tenant}/position/index?recruitmentType=CAMPUSRECRUITMENT
```

卡片结构（已用 `ITEM` 正则解析，`rest` 长度 ~1876 字符）：

```html
<div class="position-item event-vertical" data-action="positionItem" pid="6aa37e3b7280da28da079988" recruitment="CAMPUSRECRUITMENT">
  <h4 class="title"><span class="txt">Siemens Graduate Program - Solution Management</span></h4>
  <ul>
    <li class="ele"><span class="txt">工作地点：上海,北京</span></li>
    <li class="ele"><span class="txt">职能类别：工程</span></li>
    <li class="ele"><span class="txt">JobID:522053</span></li>
    <li class="ele"><span class="txt">办公模式：仅现场办公</span></li>
  </ul>
  <div class="time">发布于: 2026-10-08</div>
</div>
```

> **正则陷阱**：卡片内部还有 `<div class="position-item-container">`，如果用
> `<div class="position-item` 做前瞻，会在这里提前截断（实测 `rest` 只剩 **52** 字符，
> 标题/城市/日期全丢）。正确边界：
> `(?=<div class="position-item |</div>\s*</div>\s*</div>|<div class="pagination|$)`。

## 分页（关键）

`?page=2` **无效**——实测第 2 页返回的 pid 与第 1 页完全相同：

```
1 15 ['6aa37e3b7280da28da079988'] | cur page marker: []
2 15 ['6aa37e3b7280da28da079988'] | cur page marker: []
```

真实机制在 `cdn.careersite.tupu360.com/csresources/scripts/default/position.index.js`
的 `pageTurn(e)` 里（第 350 行起）：

```js
const pageNum = $e.data('pagenum');
const pageMax = $e.data('pagemax');
let searchData = paramsData();
searchData['offset'] = (pageNum - 1) * pageMax;
searchData['max'] = pageMax;
$.ajax({ url: getVisitUrl("position", "nextPageList"), type: "POST", data: searchData, ... })
```

`getVisitUrl(c, n)` = `"/" + careerSiteCustomName + "/" + c + "/" + n`，即：

```
POST /{tenant}/position/nextPageList
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest

recruitmentType=CAMPUSRECRUITMENT&offset=15&max=15
```

**实测三页**：

| offset | HTTP | 首条 pid | 条数 |
|---|---|---|---|
| 0 | 200 | `6aa37e3b7280da28da079988` | 15 |
| 15 | 200 | `6a9fde0c7280da28da0796ba` | 15 |
| 30 | 200 | `6aa0db0d7280da28da079793` | 11 |

返回的是**整个 `#position-list` 片段**（含 `<div class="txt">共41个职位</div>` 与新的分页控件
`data-pagenum="1|2"` / `共3页`），所以第 1 页走 GET index、后续页走 POST，可以复用同一套 `ITEM` 正则。

不需要任何 `paramsData()` 里的筛选字段（`keyword` / `jobCategory` / `baseProvinceCity` …）——
不传就是「不限」。传了反而会缩小结果集。

## 总数

```
GET /{tenant}/position/positionTotal?recruitmentType={CODE}
-> {"success":true,"positionTotal":41}
```

`recruitmentType` 是**枚举**，拼错会静默返回 0（不会报错）：

| 值 | 西门子 |
|---|---|
| `CAMPUSRECRUITMENT` | 41 |
| `INTERNSHIPRECRUITMENT` | 9 |
| `SOCIALRECRUITMENT` | 170 |
| `INTERN` / `INTERNSHIP` / `TRAINEE` | 0（无效） |

## 详情页

```
GET /{tenant}/position/detail?positionId={pid}&recruitmentType={CODE}
```

列表已经给了城市、职能、发布日期、JobID，详情页主要是 JD 正文。适配器目前只用列表。

## 适配器实现要点

- `tupu360.py`：`_fetch_page()` 第 1 页 GET、后续页 POST；`page_size` 默认 **15**（= `data-pagemax`）。
- **踩过的坑（已修）**：内层翻页 `while` 里用 `return` 结束，会把**后面所有招聘类型**一起终止。
  西门子 campus 41 条抓完后直接 return，intern 的 9 条一条都没进结果，而 CLI 照样打印
  `1 ok / opened: 41`。现在改成 `break`。
- `base.py` 的 `request_json` / `request_text` 增加了 `data=` 关键字（httpx form-encoded）。

## 结果

`tupu360-siemens`：**50 条**（campus 41 / intern 9），城市 **50/50**、发布日期 **50/50**、职能 **50/50**。

## 同平台其他站点：**一台能抓、一台全线禁止**

Tupu360 有两种部署方式，robots 完全不同（2026-10-26 实测）：

| 主机形态 | 例子 | robots.txt | 判定 |
|---|---|---|---|
| 企业自有域名 | `jobs.siemens.com.cn/siemens` | **404**（nginx 默认页，无规则） | ✅ 可抓 |
| 平台共享域名 | `careersite.tupu360.com/<tenant>` | `User-agent: *` / **`Disallow: /`** | ❌ **整站禁止** |

`careersite.tupu360.com` 上探到 6 个有在招岗位的租户（合计 774 个岗位），逐个都能解析：

| tenant | 校招 | 实习 | 社招 | 页面形态 |
|---|---|---|---|---|
| `iqvia`（艾昆纬） | 12 | 4 | 11 | 列表式（`ele e-title/e-salary/e-date`） |
| `siemens`（西门子） | 41 | 9 | 170 | 卡片式（`pid` + 「工作地点：」） |
| `jnj`（强生） | 18 | 3 | 373 | **SPA 门户**（`location.replace("/jnj/home/index/#/position")`，服务端无卡片） |
| `schaeffler`（舍弗勒） | 11 | 0 | 79 | 列表式 |
| `accenture`（埃森哲） | 12 | 0 | 5 | 列表式 |
| `intel`（英特尔） | 8 | 8 | 10 | 卡片式（`pid` + `ele e-city`） |

**但 `Disallow: /` 意味着一个都不能抓**，所以这一批只做了适配器兼容（列表式 / `e-city` /
`<h4 class="title" >` 带空格），没有挂源。在 `proposed-sources.yaml` 里记为 blocked。

> **这一轮最值钱的两条教训**
>
> 1. **能解析 ≠ 能抓**。适配器跑通、`opened: 41`，和「允许抓」是两件独立的事。
>    robots 检查必须在对每个**主机**做，而且要在写源配置**之前**做。
> 2. **radancy 与 tupu360 是同一个坑的两面**：radancy 是逐条 `Disallow` 前缀（要看全），
>    tupu360 共享主机是一行 `Disallow: /`（要看主机）。两次都是「先跑通了才发现不能抓」。

## 候选租户的探测方法（留着复用）

不要猜公司域名（`jobs.bosch.com.cn` 这类 20 个全都不存在，DNS 直接失败）。
Tupu360 的租户名同时挂在共享域名下，所以直接打共享域名：

```
GET https://careersite.tupu360.com/{tenant}/position/positionTotal?recruitmentType=CAMPUSRECRUITMENT
-> {"success":true,"positionTotal":N}
```

这一步本身是**探测**（每个 tenant 1 个请求），拿到数之后再去看该租户有没有自有域名 ——
有自有域名且 robots 允许，才挂源。
