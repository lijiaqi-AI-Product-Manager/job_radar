# 侦察：招商银行招聘门户（career.cmbchina.com）

- 侦察日期：2026-10-23（recon #60）
- **结论：待定（接口是明文 JSON，但岗位列表端点还没定位到）**
- 类型：企业自研门户（React SPA）

## 1. 已确认

- robots.txt：`User-agent: *` / `Disallow:`（空 = 全站允许）
- 首页 `https://career.cmbchina.com/index.html` 是 React 单页（入口 566B，main.js 916KB）
- 首页只请求两个「宣传视频」接口，响应是**明文 JSON**：

  ```
  GET /api/socialRecruitmentWebsite/common/getPromotionalVideoUrl
  → {"returnCode":"SUC0000","errorMsg":null,"body":"https://s3gw.cmbimg.cn/..."}
  ```

  命名规律：`/api/{social|?}RecruitmentWebsite/<模块>/<动作>`，返回 `returnCode/errorMsg/body`。

- 前端路由是客户端渲染：`/campus`、`/social`、`/job` 等都返回同一个 566B 外壳。
- main.js 里没有字面量 `/api/...` 路径（懒加载/动态拼接），所以岗位列表端点必须靠**在有岗位的路由上抓 XHR**。

## 2. 下一步（未做）

1. 用 RENDERXHR 抓 `https://career.cmbchina.com/` 的「校园招聘」路由（需先确定真实 path，可从首页导航的 href 读）。
2. 若列表接口是 `GET /api/campusRecruitmentWebsite/job/list?...` 这类明文 JSON，就照 `hotjob` 的写法做适配器；
   若带签名/加密，按铁律标 blocked。

## 3. 合规

- 公开页面、无登录；robots 允许；限速 1 req/s。侦察到此为止，未做任何绕过。
## 4. 岗位列表接口（2026-10-23 recon #62 抓到）

前端路由是 `/positionlist/<recruitmentTypeId>`，页面发出：

```
POST https://career.cmbchina.com/api/campusRecruitmentWebsite/job/getList
REQ  {"orgIdList":[],"keywords":"","locationIdList":[],"pageIndex":1,"pageSize":10,
      "recruitmentTypeId":"96574F8D-C7ED-4772-AE7C-BAC896D190C1","jobTypeIdList":[]}
RESP {"returnCode":"SUC0000","errorMsg":null,"body":{"total":0,"data":[]}}
```

- **明文 JSON、无需登录**（`pageIndex` 从 1 开始）
- 但 `recruitmentTypeId` 必须是**当前招聘季**的 GUID；chunk 里挖到的那个是旧季（total=0）
- 拿季 id 的接口目前都返回 401（`recruitmentType/*`、`job/getRecruitmentTypeList` 等），说明需要登录态；
  `/campus/home` 只调公告、FAQ、宣讲会日历，不返回季 id

**结论**：接口是公开的、结构清楚，卡在「当前招聘季 GUID」上。可行路径：
从公告详情页（`notice/getList` 拿到的 noticeId）里找季 id，或等官方在页面上暴露季列表。
下一步留给后续会话，不绕过鉴权。