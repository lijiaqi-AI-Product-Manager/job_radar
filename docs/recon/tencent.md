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
