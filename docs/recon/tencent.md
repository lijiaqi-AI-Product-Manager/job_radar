# 侦察：腾讯（careers.tencent.com 社招 / join.qq.com 校招）

- 侦察日期：2026-10-20
- 侦察人：Claude 会话（请求从 GitHub Actions 发出，见 recon-probe 第 1、4、5 轮）
- **结论：社招 可做；校招（join.qq.com）待定（接口未确认）**
- 类型：自研站

## 1. 入口与范围
- 社招：https://careers.tencent.com/ ，列表接口返回 `Count: 2282`（2026-10-20）
- 校招：https://join.qq.com/post.html（前端渲染，脚本 `p_zh-cn_post.build.js`，接口待从脚本中确认）

## 2. 合规核查
- robots.txt：careers.tencent.com 与 join.qq.com 的 `/robots.txt` 均返回 HTML 页面，无 robots 规则。
- 条款：列表接口无需登录、无签名参数；用户协议待人工复核。
- 登录/验证码/签名：无。
- 建议限速：1 req/s。

## 3. 取数接口（社招）
- `GET https://careers.tencent.com/tencentcareer/api/post/Query?pageIndex=1&pageSize=N&language=zh-cn&area=cn`
- 返回：`{"Code":200,"Data":{"Count":2282,"Posts":[...]}}`
- 分页：pageIndex 从 1 开始；`pageIndex*pageSize >= Count` 时结束。
- 唯一 id：`PostId`；岗位链接：`PostURL`（http，转 https）。
- 详情（含岗位要求）：未调用；后续如需 requirements，需逐岗位请求详情，约 2300 次/天，暂不做。

## 4. 字段映射
| 我们的字段 | 站点字段 | 备注 |
|---|---|---|
| source_job_id | PostId | |
| title | RecruitPostName | |
| url | PostURL | http→https |
| recruit_type | 固定 social | careers.tencent.com 为社招 |
| cities | [LocationName] | |
| department | BGName | 如 IEG |
| description | Responsibility | 职责 |
| requirements | — | 列表不含 |
| 其他 | CategoryName、ProductName、RequireWorkYearsName、LastUpdateTime | 暂不入库 |

## 7. 从 GitHub Actions 的可达性
200，约 0.2s。

## 8. 下一步
社招已实现 `adapters/tencent.py`。校招需要再侦察 join.qq.com 的接口。

## 9. 校招 join.qq.com（第 19–21 轮补充，2026-10-20）
- **结论：可做**
- 列表：`POST https://join.qq.com/api/v1/position/searchPosition`，body
  `{"projectIdList":[],"projectMappingIdList":[],"keyword":"","bgList":[],"workCountryType":0,"workCityList":[],"recruitCityList":[],"positionFidList":[],"pageIndex":1,"pageSize":100}`
  → `{"status":0,"data":{"positionList":[...],"count":1024}}`；每页 100 已验证。
- 详情：`GET https://join.qq.com/api/v1/jobDetails/getJobDetailsByPostId?postId=<postId>` → `data.desc`（职责）、`data.request`（要求）。
  响应约 40KB（含全部事业群介绍），只取需要的字段。
- 岗位链接：`https://join.qq.com/post_detail.html?postid=<postId>`（200）
- 项目（招聘类型）：应届毕业生(1)、青云计划-应届生(14) → campus；应届实习(2)、项目实习生/日常实习(12) → intern
- 城市：`workCities` 空格分隔，"深圳总部"→深圳；事业群：`bgs`（如 "CDG CSIG IEG"）
- 无登录、无签名、无验证码；前端静态资源（cdn.multilingualres.hr.tencent.com）对我们的 UA 返回 403，但接口本身可访问。
- 适配器 id：`tencent_campus`（source id `tencent-campus`）
