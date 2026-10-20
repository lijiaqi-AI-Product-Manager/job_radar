# 侦察：美团（zhaopin.meituan.com）

- 侦察日期：2026-10-20
- 侦察人：Claude 会话（请求从 GitHub Actions 发出，见 recon-probe 第 16、19–21 轮）
- **结论：可做**
- 类型：自研站

## 1. 入口与范围
- 校招：https://zhaopin.meituan.com/web/campus ；社招入口同站点
- 总量（2026-10-20）：校招 196、实习 370、社招 2609，合计 3175

## 2. 合规核查
- robots.txt：返回 HTML 页面，无 robots 规则。
- 列表接口无需登录、无签名参数、无验证码；页面加载了 `certificates.meituan.com/cert/latestsdk`，但列表接口不校验其结果（不带任何 token 直接 200）。
- 用户协议：待人工复核。
- 限速：1 req/s。

## 3. 取数接口
- `POST https://zhaopin.meituan.com/api/official/job/getJobList`
- body：`{"page":{"pageNo":1,"pageSize":100},"jobShareType":"1","keywords":"","cityList":[],"department":[],"jfJgList":[],"jobType":[],"typeCode":[],"specialCode":[]}`
  - `jobType: []` 返回全部；`[{"code":"1","subCode":[]}]` 只返回校招（2 实习、3 社招）
- 返回：`{"data":{"list":[...],"page":{"pageNo":1,"pageSize":100,"totalPage":32,"totalCount":3175}}}`
- 每页上限：100 已验证。终止：`pageNo >= totalPage`。
- 唯一 id：`jobUnionId`；岗位链接：`/web/position/detail?jobUnionId=<id>&highlightType=campus|social`（200）

## 4. 字段映射
| 我们的字段 | 站点字段 | 备注 |
|---|---|---|
| source_job_id | jobUnionId | |
| title | name | |
| recruit_type | jobType | 1 campus / 2 intern / 3 social |
| cities | cityList[].name | "北京市"→北京 |
| department | department[].name | 常为空 |
| description | jobDuty | |
| requirements | jobRequirement | |
| 其他 | jobFamily、jobFamilyGroup、jobSpecialCode（专项计划，如北斗）、refreshTime | 暂不入库 |

## 5. 已知陷阱
- 标题多不写届别；校招/实习的 grad_year 大多为空。
- `jobSpecialCode` 区分专项计划（含义未确认），暂不使用。

## 8. 下一步
适配器 id：`meituan`（单源，三类一起抓）。
