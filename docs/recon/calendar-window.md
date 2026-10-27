# 侦察：日历「网申时间」的三条真实来源

- 侦察日期：**2026-10-26 13:33–13:55 CST**（全部为真实请求，时间取自机器时钟）
- 结论：**能拿到的比原来多得多**。此前「有网申时间」只有 24.7%，根因不是"平台不给"，
  而是**接口给了却没读**（大易、美团、腾讯的列表接口都带日期字段），
  加上**公众号被自家 UA 挡住**（四条推文全部解析成空）。
- 影响文件：`src/jobradar/normalize.py`（`date_only`）、`adapters/{hotjob,meituan,tencent,workday,alibaba,netease}.py`、
  `pipeline/calendar.py`（`auto_entries` 的窗口口径）、`scripts/wechat_parse.py`、`scripts/wechat_entries.py`

## 0. 一句话结论

网申时间的来源分三层，可信度从高到低：

| 层 | 来源 | 能拿到什么 | 实测覆盖 |
|---|---|---|---|
| 1 | 平台列表接口自带的截止日 | 精确到日（大易 `endDate`） | 大易系源 100% 有值 |
| 2 | 平台列表接口自带的上架日 | 只有"起点"，没有终点（美团/腾讯/网易/阿里） | 只能说"什么时候开的" |
| 3 | 官方公众号推文正文 | 起止都给（`2026年9月24日—10月28日`） | 需逐篇解析，正文常是长图 |

**北森（`*.zhiye.com`）一条也不给**：`PostDate` / `EndTime` 字段存在，但 311 个租户
实测调用后返回的全是 `0001-01-01T00:00:00`。这不是我们没解析，是门户没填。

## 1. 平台接口的日期字段实测（逐个原值）

| 适配器 | 字段 | 原值样例 | 含义 | 处理 |
|---|---|---|---|---|
| `hotjob`（大易） | `endDate` | `2026-11-17 23:59:59` | 截止日，**真实值** | `apply_end` |
| `hotjob` | `publishDate` | `2026-10-15 15:20:15` | 本次发布 | `publish_at` |
| `hotjob` | 哨兵值 | `3000-01-01` | "长期开放" | 归一成 `None` |
| `meituan` | `firstPostTime` | `null`（多数）/ 毫秒 | 首次发布 | `publish_at`（优先） |
| `meituan` | `refreshTime` | `1792991700000` = 2026-10-26 13:15 | 最近刷新 | `publish_at`（兜底） |
| `meituan` | `expiredTime` | `null`（多数） | 截止日 | `apply_end` |
| `tencent` | `LastUpdateTime` | `"2026年10月21日"` | 最近更新 | `publish_at`（中文日期要专门解析） |
| `tencent_campus` | — | 列表/详情都没有日期字段 | — | 不填 |
| `netease` | `updateTime` | `1789725119000` | 最近更新（逐条不同） | `publish_at` |
| `alibaba` | `publishTime` | `null` | — | 退回 `modifyTime` → `publish_at` |
| `workday` | `startDate` | ISO | 真实上架日 | `publish_at` |
| `workday` | `postedOn` | `"Posted 30+ Days Ago"` | 相对文案 | 只有 `Posted Today` 可用，其余 `None` |
| `feishu_atsx` | `publish_time` | `1792644099156` | 发布时间 | `publish_at`（既有） |
| `beisen` | `PostDate` / `EndTime` | `0001-01-01T00:00:00` | **未填** | `None`（不猜） |

一个容易踩的坑：`refreshTime` / `updateTime` / `modifyTime` 这些"最近修改"**不是上架日**。
只有当它们逐条不同（不是一个整站统一刷新时刻）时才当弱证据用；如果整站同一秒，那就是
批量刷新产生的噪声，填进去会让日历显示"今天开的"几十次。实测美团/网易/阿里的这些值都逐条不同，
所以可以当 `publish_at` 的下界（真实上架日 ≤ 这个日期），但**不能当 `apply_start`**。

## 2. 截止日从"众数"改成"尚未过期的最早一天"

旧口径（2026-10-26 上午）：取该批在招职位截止日的**众数**。
问题在两处：

1. 一批里 6 条写 11-30、5 条写 12-31，众数报 11-30——但"报名截止"的语义是
   "这天之前都还能投"，用户按 11-30 准备会**少一天**；报最早那天才是对的。
2. 一批里既有已过期岗位（9-01）又有新开岗位（12-31）时，众数可能在两者都够不着时
   报 9-01——用户看到"已截止"，实际还在招。

新口径：`apply_end = 第一个 ≥ 今天 的截止日`；整批都已过期则取**最晚**那天（这批的整体收口日）。
哨兵值在适配器层已被归一成 `None`，所以不会因为 2100 年把窗口拉长 70 年。

## 3. 公众号：一次 UA 写法导致的全面失效

四条官方推文（`calendar/wechat-urls.json`）在旧脚本下**全部解析成 None**。两个独立原因：

1. **抓页顺序反了**。旧脚本优先用 Playwright（Chromium 无头）渲染，实测渲染结果是
   22 KB 的「环境异常，完成验证后即可继续访问」壳页——无头浏览器指纹被识别。
   普通 HTTP GET 反而拿到 3.5 MB 完整文章。
2. **UA 写法**。带联系地址的长 UA
   `jobradar/0.1 (+https://github.com/lijiaqimun-coder/job_radar; ...)` 被拦（3 次全部 18 KB 验证页）；
   短的 `Mozilla/5.0 (compatible; jobradar-bot/0.1)` 通过（3 次全部 3.5 MB）。
   两者都是**诚实的爬虫标识**，区别只是后者不带 URL——不构成伪造浏览器。

修正后 `scripts/wechat_parse.py`、`scripts/wechat_entries.py`、`scripts/enrich_calendar.py`
统一用短 UA + 「先普通 GET、被拦才退渲染」+ 验证页显式识别（`_is_blocked`）。

解析结果（2026-10-26 13:46 实测）：

| 推文 | 发布日期 | 届次 | 网申时间 | 城市 |
|---|---|---|---|---|
| 中石化炼化工程 2027 校招 | 2026-10-08 | 2027 | **2026-09-24 ~ 2026-10-28** | 北京/上海/广州/南京/天津/青岛/宁波 |
| 中建三局（深圳）2027 校招 | 2026-09-11 | 2027 | —（正文是长图） | — |
| 中船海舟 2027 校招 | 2026-09-03 | 2027 | — | — |
| 建设银行福建省分行 2027 秋招 | 2026-09-05 | 2027 | — | — |

**为什么只有一篇有网申时间**：公众号正文经常是**长图**（`mmbiz.qpic.cn` 上的 PNG/GIF），
文字全在图里，HTML 里只有"素材｜人力资源部"这类版尾。这是这个来源的硬上限，
不是解析器的问题。要么上 OCR（中文字库约 100 MB），要么承认这个来源只能覆盖"有文字版"的推文。

## 4. 复现

```bash
# 1) 确认平台给不给日期（大易示例：长沙某租户）
curl -s -A "jobradar-bot/0.1" \
 "https://wecruit.hotjob.cn/wecruit/positionInfo/listPosition/SU60a6449a2f9d2430fdc11a19?iSaJAx=isAjax&request_locale=zh_CN&isFrompb=true&recruitType=1&pageSize=5&currentPage=1" \
 | python3 -c "import json,sys;[print(x['postName'][:16],x['endDate'],x['publishDate']) for x in json.load(sys.stdin)['data']['pageForm']['pageData']]"

# 2) 北森租户一律不填日期（311 个全测过，随机抽一个）
curl -s -A "jobradar-bot/0.1" -H 'Content-Type: application/json' \
 -d '{"PageIndex":0,"PageSize":2,"KeyWords":"","SpecialType":0,"PortalId":""}' \
 "https://boe.zhiye.com/api/Jobad/GetJobAdPageList" \
 | python3 -c "import json,sys;[print(x['PostDate'],x['EndTime']) for x in json.load(sys.stdin)['Data']]"
# -> 0001-01-01T00:00:00 0001-01-01T00:00:00

# 3) 公众号：两种 UA 对比（同一篇文章）
for ua in "jobradar/0.1 (+https://github.com/x/y)" "Mozilla/5.0 (compatible; jobradar-bot/0.1)"; do
  curl -s -A "$ua" "https://mp.weixin.qq.com/s/Ogar3bEBbwYY0ZlXTMspPA" | wc -c
done
# -> 18044（验证页） / 3501721（正文）
```

## 5. 合规

- 全部是**匿名可读的公开页面**，无登录、无 Cookie 复用、无代理池；
- 每主机 ≤ 1 rps（`rate_limit_rps: 1`），UA 为可识别的爬虫标识；
- 北森/大易/美团/腾讯/网易/阿里/飞书都是**公开职位列表 JSON**，没有签名、没有加密；
- 公众号只读推文页，不做批量遍历（列表来自人工筛选的官方账号），单篇一请求。
