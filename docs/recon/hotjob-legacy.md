# 侦察：hotjob（大易云）老版 wt 门户

- 侦察日期：2026-10-23
- **结论：可做**（公开 JSON，无需登录/签名/验证码）
- 类型：平台型（多租户），与新版 `/wecruit/...` 不是同一套接口

## 1. 入口形态

老版门户 URL 形如：

```
https://{host}/wt/{tenant}/web/index              # 首页（Vue 模板，服务端渲染）
https://{host}/wt/{tenant}/web/index/webPositionN300!getOnePosition?postId=...&brandCode=1&recruitType=1
```

- 自定义域名的租户：`yili.hotjob.cn/wt/yili/...`、`efunds.hotjob.cn/wt/efunds/...`
- 共用域名的租户：`www.hotjob.cn/wt/Hygon/...`、`sc.hotjob.cn/wt/Jahwa/...`

## 2. 数据接口

页面里的 Vue 模板（`/web/templet1000/index/corpwebPosition1000{tenant}!gotoPostListForAjax`）
会 `GET` 同域的 JSON：

```
GET https://{host}/wt/{tenant}/web/json/position/list
    ?positionType=&comPart=&sicCorpCode=&brandCode=1&releaseTime=&trademark=1
    &recruitType={1校招|2社招|3实习}&projectId=&lanType=1&workPlace=&page={n}&keyWord=
```

实测（`yili.hotjob.cn`，recruitType=1）：

```json
{"pageCount": 41, "postList": [{
  "postId": 533317, "postName": "伊利2027届校招-数字化培训生（婴幼儿 北京）",
  "workPlace": "北京市-丰台区", "publishDate": "2026-10-21", "endDate": "2026-10-23",
  "recruitType": 1, "education": "硕士研究生及以上", "orgName": "婴幼儿营养品事业部",
  "postType": "数字化业务",
  "workContent": "通过系统培养与在岗实践……", "serviceCondition": "1、2027届应届毕业生……"
}]}
```

**要点：列表响应自带 JD 正文**（`workContent` + `serviceCondition`），不需要逐岗请求详情，
所以这个适配器没有详情请求，1 req/s 就够。

注意：响应头是 `text/html` 但正文是 JSON，适配器用 `request_text` + `json.loads`。

## 3. 租户可用性（2026-10-23 实测）

| 租户 | 入口 | 校招 | 社招 | 结论 |
|---|---|---|---|---|
| yili | yili.hotjob.cn | 41 页 | — | 可做（已接入） |
| efunds | efunds.hotjob.cn | 0 条 | 15 页 | 可做（已接入，只开社招） |
| Jahwa | sc.hotjob.cn/wt/Jahwa | — | — | `Sorry! You do not have permission to operate!` |
| Hygon | www.hotjob.cn/wt/Hygon | — | — | 同上 |

共用域名上的租户可能要在自定义域名下访问；找不到就放弃，不做绕过。

## 4. 合规

- robots.txt（yili / efunds）：`User-agent: *` / `Allow: /`
- 只读公开接口，无登录、无签名、无验证码；限速 1 req/s
