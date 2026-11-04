# 侦察：hotjob（大易云招聘，`*.hotjob.cn`）

## 2026-11-04复核

立讯精密公开列表的首次请求带`pageSize=50`，响应实际每页12条、共19条；第二页仍带50会越过剩余记录并返回空页。后续分页必须沿用响应中的实际页大小，空页和重复页保护继续保留。最小公开元数据见`tests/fixtures/hotjob/pagination-evidence.json`。

华润租户的十六进制部分被写成大写时，公开接口返回“官网不存在”；同一标识恢复小写后返回15条第一页记录。适配器统一公开租户标识大小写，不更改租户本身。平台未提供学历时，不用空值否定已有正文中提取的学历；明确学历变化仍触发详情重读，复用正文保留原观测时间。

以下访问结论为历史样本。当前每轮仍独立核对访问规则，不能将某一主机的允许记录套到其他主机。

- 侦察日期：2026-10-22（本机直连 + GitHub Actions 的 RENDERXHR 抓包）
- **结论：可做**（公开 JSON 接口、无登录、无签名、无验证码）
- 覆盖公司：中联重科、伊利、歌尔股份、长城汽车等（同一平台，租户不同）

## 1. 站点形态

`https://{host}/{tenant}/pb/{campus|social|index}.html` 是 SPA；数据来自
`https://{host}/wecruit/positionInfo/...`，**GET 即可**（POST 表单也行），
必须带两个查询参数：

```
iSaJAx=isAjax&request_locale=zh_CN&t=<毫秒时间戳>
```

`tenant` 形如 `SU60a6449a2f9d2430fdc11a19`（页面 URL 的第一段）。

## 2. 列表

```
GET https://{host}/wecruit/positionInfo/listPosition/{tenant}
    ?iSaJAx=isAjax&request_locale=zh_CN&t=...&isFrompb=true
    &recruitType={1|2|3}&pageSize=50&currentPage=1
```

- `recruitType`：**1=校园招聘，2=社会招聘，3=实习生**（实测 3 在多数租户为空）
- 响应：`{"data":{"pageForm":{"totalPage":N,"pageSize":M,"pageData":[...]}}}`
- 每页实际条数由服务端决定（中联重科为 12），不要假设等于 `pageSize`
- 列表字段（节选）：`postId`、`postName`、`workPlaceStr`（**城市，带「市-区」**）、
  `postTypeName`（职位类别）、`educationStr`、`company`（事业部）、`publishDate`、`endDate`、
  `salary`、`recruitType`

## 3. 详情（JD 正文）

```
GET https://{host}/wecruit/positionInfo/listPositionDetail/{tenant}
    ?iSaJAx=isAjax&request_locale=zh_CN&t=...&postId={postId}
```

- 响应 `data`：`workContent`（职责）、`serviceCondition`（要求）、`education`、
  `workPlaceList`（城市列表）、`postName`、`postTypeName`、`publishDate`、`endDate`
- 缺 `postId` 时返回 `{"msg":"职位ID不能为空！"}`
- 详情页 URL（给用户点开）：
  `https://{host}/{tenant}/pb/posDetail.html?postId={postId}&postType={campus|social}`

## 4. 城市

`workPlaceStr` / `workPlaceList` 是**明写的工作地点**（如「长沙市-长沙县」「长沙市」），
按「-」拆到城市级即可，不需要猜。这是目前除自研站外少数能给城市的数据源。

## 5. 合规

- robots.txt：各租户均为 `Allow: /`（2026-10-22 抽查 wecruit/goertek/yili）
- 匿名 GET、无登录、无签名；限速 1 req/s
- 详情请求量 = 岗位数，按来源配置 `recruit_types` 控制规模（先只开校园）

## 6. 已知边界

- `pageSize` 被服务端限制（中联重科 12/页），大租户社会招聘有几百页，**不要一次性全抓**；
  用 `max_pages` 或只开 `campus`。
- 个别租户的自定义域名（`yili.hotjob.cn`）用同一路径，但 `tenant` 仍是 `SU...`，
  需要从页面 JS/配置里拿到租户 id。
