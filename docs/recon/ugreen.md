# 侦察：绿联（北森新版 · ugreen.zhiye.com）

- 侦察日期：2026-10-25
- 侦察人：自研批量探针（work/probe_beisen.py，串行 ≤1 req/s）
- **结论：可做**（实测 32 条在招，列表接口明文 JSON，JD 在列表内）
- 类型：平台型（多租户）· 适配器 `beisen`

## 1. 入口与范围
- 公开入口 URL：https://ugreen.zhiye.com/
- 覆盖的招聘类型：社招 / 校招 / 实习（北森门户混列，详见第 5 节陷阱）
- 预估岗位总量（全量）：32
- 平台型预估租户数：本批实测命中 83 个北森租户（见 beisen-batch.md）

## 2. 合规核查
- robots.txt：`User-agent: * / Allow: /`（2026-10-25 实测，抽样 5 家一致）
- 服务条款：北森门户为企业自建公开门户，列表接口无需登录、无签名、无验证码
- 是否需要登录/验证码/签名：**否**
- 建议限速：1 rps（本项目全局约束）
- 其他风险：见第 5 节（门店岗位噪声、CategoryId 失效）

## 3. 取数接口
- 列表接口：`POST https://ugreen.zhiye.com/api/Jobad/GetJobAdPageList`
  - body：`{"PageIndex":0,"PageSize":100,"KeyWords":"","SpecialType":0,"PortalId":""}`
  - 分页：`PageIndex` 从 0 起；`PageSize` 上限实测 100
  - 终止条件：`(PageIndex+1)*PageSize >= Count` 或返回空 `Data`
- 详情接口：**无需单独请求**，`Duty`（职责）与 `Require`（要求）直接在列表项里
- 返回结构：`{"Code":200,"Count":N,"Data":[{"Id","JobAdId","JobAdName","CategoryId","Duty","Require","LocNames",...}]}`
- 岗位唯一 id：`Id`（GUID 字符串）
- 岗位页链接：`https://ugreen.zhiye.com/social/detail?jobAdId={Id}`

## 4. 字段映射
| 我们的字段 | 站点字段 / 提取方式 | 备注 |
|---|---|---|
| source_job_id | `Id` | GUID，稳定 |
| title | `JobAdName` | 含 `(J12345)` 内部编号后缀，需清洗 |
| url | `https://ugreen.zhiye.com/social/detail?jobAdId={Id}` | 构造 |
| recruit_type | `CategoryId` → 1/5=social, 2=campus, 3=intern | **4/6/7 未映射（见陷阱）** |
| grad_year | 标题正则 `20\d{2}届` | 多数无 |
| batch | `normalize.batch_from_text(标题)` | 提前批/正式批/补录 |
| cities | `LocNames[]` | **本租户实测恒为空**，城市缺失 |
| degree_min | `Degree` | 多数 null |
| department | 无独立字段 | 可从 `Org` 取（多数 null） |
| description | `Duty` | 纯文本，含换行 |
| requirements | `Require` | 纯文本 |

## 5. 已知陷阱
1. **`CategoryId` 请求参数被服务端忽略**：传 1/2/3/4/5 均返回同一 `Count`，筛选必须在客户端做。
2. **`CategoryId=4` 是门店/操练岗**（来伊份 7216 条里大量「营业员/店员/美食顾问」），适配器当前 `None` → `SkipRecord` 会整条丢弃，是**正确**行为，但意味着该租户绝大多数岗位不可用。
3. `LocNames` 在本租户恒为空（与 docs/recon/beisen.md 记录一致）。
4. 标题带 `(J27391)` 内部编号，做去重前先剥离。

## 6. 样本
`docs/recon/samples/ugreen/`：`list_p1.json`（第 1 页）、`list_last.json`（末页）、`detail.html`（详情页 HTML）。已脱敏（邮箱/手机号/token 已替换）。

## 7. 从 GitHub Actions 的可达性
未测（本机实测 200，耗时 200–600ms）。建议新增源上线前跑 `scripts/smoke_sources.py beisen-ugreen`。

## 8. 下一步
可以直接合并 `sources/beisen.yaml`：
```yaml
  - {id: beisen-ugreen, company: 绿联, params: {tenant: ugreen}}   # 32 岗（2026-10-25 实测）
```
