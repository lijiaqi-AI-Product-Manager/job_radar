# 侦察：网易校园招聘（campus.163.com / campus.game.163.com）

- 侦察日期：2026-10-22
- 侦察人：本机探针（本机直连，固定 UA，全程 ≤1 req/s）
- **结论：可做**
- 类型：自研站（React SPA + 公开 JSON）

## 1. 入口与范围

`https://campus.163.com/` 是应届生入口，导航接口列出 4 个项目（2026-10-22）：

| 项目 | 站点 | projectId | 岗位数 |
|---|---|---|---|
| 网易互联网2027届校园招聘 | campus.163.com | 103 | 81 |
| 网易互娱2027届校园招聘 | campus.game.163.com | 102 | 38 |
| 蛋仔派对 AI 实习生专项 | campus.game.163.com | 75 | 5 |
| 星火计划 2027 届人力资源培训生 | campus.163.com | — | 非岗位列表 |

另有「日常实习生」跳转到 `hr.163.com/job-list.html?workType=1`（另一套系统，未侦察）。

## 2. 合规核查

- robots.txt：三个站点均返回 SPA 的 HTML 页面（无 robots 规则），按 meituan 同样方式记为 `not_applicable`。
- 页面加载网易易盾 `cstaticdun.126.net/load.min.js`，但**只用于登录/报名**；职位列表与详情接口不校验（不带任何 cookie/token 直接 200）。
- 无验证码、无签名参数、无需登录、无会话依赖。
- 用户协议：待人工复核。
- 限速：1 req/s；每天 1 次列表请求（按项目）+ 可选详情。

## 3. 取数接口

- 导航（可选）：`GET /api/campuspc/project/navigation/list` → 项目、链接、projectId
- 列表：`GET /api/campuspc/position/getJobList?projectId=<id>&pageNo=1&pageSize=100`
  - 返回：`{"code":200,"data":{"total":81,"pages":1,"list":[...]}}`
  - 每页上限：100 已验证；终止条件 `pageNo >= pages`
- 详情（本项目用不到，列表已含 JD）：`GET /api/campuspc/position/getJobDetails?id=<id>`
- 分站：互娱（102、75）在 `campus.game.163.com`，接口路径相同。

## 4. 字段映射

| 我们的字段 | 站点字段 | 备注 |
|---|---|---|
| source_job_id | id | |
| title | positionName | |
| cities | workPlaceName | 「北京」；多城市用逗号 |
| description | positionDescription | 职责原文 |
| requirements | positionRequirement | 要求原文 |
| 其他 | positionTypeName（站点自己的职类，如「市场」）、interviewCityName、updateTime | 不入库；职类仍由 taxonomy 按标题归类 |

## 5. 已知陷阱

- **没有单岗位 URL**：详情是 SPA 路由，接口不返回分享链接（`/position/share` 只返回微信 JS-SDK 签名）。`url` 用项目列表页
  `{base}/app/job/position?id=<projectId>`，用户在该页搜标题——诚实但不够精确，已在适配器里注明。
- 列表接口没有届别字段：届别来自项目名（source.yaml 的 `project_name`，如「网易互联网2027届校园招聘」），不是猜的。
- 项目 75（蛋仔 AI 实习生）是实习，未单独建源；需要时加一条 source（`recruit_types: [intern]`）。
