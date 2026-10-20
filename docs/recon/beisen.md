# 侦察：北森招聘门户（{tenant}.zhiye.com）

- 侦察日期：2026-10-20
- 侦察人：Claude 会话（请求从 GitHub Actions 发出，recon-probe 第 2–8 轮；租户验证见 tenant-verify）
- **结论：新版门户 可做；旧版门户（服务端渲染）待定**
- 类型：平台型（多租户）

## 1. 入口与范围
- 租户站：`https://{tenant}.zhiye.com/`，校招 `/campus/jobs`，实习 `/intern/jobs`，社招 `/social/jobs`
- **两代门户**：
  - 新版（2022 门户，`acdn.bstatics.com/ux/ux-recruitment-portal-2022`）：前端渲染，走 JSON 接口 → 本适配器
  - 旧版（服务端渲染，如 `smics`、`cssc`、`sast`、`casic`，URL 形如 `/campus/?PageIndex=1&p=...`）：`/api/Jobad/...` 返回 404，需要单独的 HTML 适配器
- 租户发现：搜索引擎 `site:zhiye.com campus`，候选清单 `docs/recon/beisen_tenants.txt`，由 `tenant-verify` 工作流逐个验证门户代际与岗位数

## 2. 合规核查
- robots.txt：抽查 beisen、fosunpharma、intsig、cfmoto 均为 `User-agent: * / Allow: /`
- 登录/验证码/签名：列表接口无需登录、无签名、明文 JSON
- 建议限速：1 req/s；所有租户同属 zhiye.com，crawl 中同适配器的源串行执行

## 3. 取数接口
- `POST https://{tenant}.zhiye.com/api/Jobad/GetJobAdPageList`
- body：`{"PageIndex":0,"PageSize":100,"KeyWords":"","SpecialType":0,"PortalId":""}`
- 返回：`{"Code":200,"Count":N,"Data":[...]}`；PageIndex 从 0 开始；PageSize=100 可用
- `SpecialType`：**不是**招聘类型。实测 1 = 热招（`Channel4IsHot`），2 = 长期（`Channel4IsLong`），0 = 全部
- 岗位链接：`https://{tenant}.zhiye.com/{campus|intern|social}/detail?jobAdId={Id}`

## 4. 字段映射
| 我们的字段 | 站点字段 | 备注 |
|---|---|---|
| source_job_id | Id（UUID） | |
| title | JobAdName | |
| url | 由 Id 与类型构造 | |
| recruit_type | CategoryId：1 社招 / 2 校招 / 3 实习 / 5 社招（专家、资深岗） | 1–3 实测于 intsig；5 实测于 cxmt、chinalife；其他值跳过 |
| grad_year / batch | 从标题解析（`normalize.py`） | 如"【27校招】""2027届提前批" |
| cities | LocNames | **列表中恒为空**，城市暂缺 |
| degree_min | Degree | 多为 null |
| description / requirements | Duty / Require | 列表直接带 JD 原文 |

## 4.1 租户验证（第 1 批，2026-10-20）
- 候选 73 家：**new 门户 67 家**（已写入 `sources/beisen.yaml`，合计约 2 万岗位，最大为奇瑞 5781、中国人寿 2931、长鑫存储 2001）
- 旧版门户 6 家：smics（中芯国际）、xib（厦门国际银行）、glprop（普洛斯）、kelun（科伦药业）、biad（北京建院）、eic（启德教育）
- 注意：raytrontek 与 raytrontek1 均为睿创微纳（两个门户），可能存在重复岗位

## 4.2 租户验证（第 2 批，2026-10-20）
- 候选 46 家：new 门户 37 家，入库 36 家（`jmgroup-o` 标题为"JM华中华东区"，无法确认公司，暂不入库）
- 旧版门户 9 家：eswinchipch（奕斯伟）、gtgroup（绿城）、newhope（新希望）、crrczzs（中车株洲所）、sast（上海航天）、cssc（中船）、casic（航天科工）、ehr-dian（小电）、zghkyjy（中国航空研究院）
- 大户：heytea 5144、norincogroupzhaopin 1903、jssoft 671、vital 532、inovance 417

## 4.3 租户验证（第 3 批，2026-10-20）
- 候选 31 家：new 门户 29 家，入库 28 家（`ciccwm` 中金财富的 Count 与 `cicc` 完全相同（483），疑似共享岗位，暂不入库以免重复）
- 旧版门户 2 家：weiheng（威衡）、tecon（天康生物）
- 大户：sunwodacampus 1286、gotion 937、cpgroup 816、cttq 769、futurefoton 683、wuxiapptec 634

## 4.3b 租户验证（第 4 批，2026-10-20）
- 候选 23 家：new 门户 22 家，入库 21 家（`huitian1` 标题为"招聘门户网站"，无法确认公司，暂不入库）；`eswinplp` 非新版门户
- 大户：ccccltd（中国交建）2630、ymtc（长江存储）656、tigermed 515、pudutech 281、mindray 238、mengniu 213

## 4.3c 租户验证（第 5 批，2026-10-20）
- 候选 5 家：new 门户 4 家，入库 3 家：leapmotor1（零跑汽车）1174、dptech（迪普科技）407、novastar（诺瓦星云）148
- `chery` 的 Count 与已入库 `chery1` 完全相同（5781），同一批岗位，不入库
- `611`（成都飞机设计研究所）为旧版门户，待旧版变体检查

## 4.4 旧版门户（服务端渲染，第 12 轮侦察）
- 共 17 家：smics、xib、glprop、kelun、biad、eic、eswinchipch、gtgroup、newhope、crrczzs、sast、cssc、casic、ehr-dian、zghkyjy、weiheng、tecon
- 变体 A（如 cssc）：列表 `GET /campus/?PageIndex=N`，岗位链接 `<a title="标题" href="/zpdetail/<数字id>?PageIndex=N">`
- 变体 B（如 smics）：链接参数形如 `jobId=390852397&jc=2&c=&p=1^-1,3^-1`
- 列表只有标题与 id；JD 原文需逐个请求详情页（HTML）
- 页码从 1 开始（PageIndex=0 越界并返回第 1 页）；页脚"当前第N/M页"给出总页数；每行带所属单位、地点、发布日期
- 结论：可做，已实现 `adapters/beisen_legacy.py`（正则解析，无新依赖；列按内容识别地名，不依赖列顺序）
- 第 15 轮变体检查：变体 A 共 8 家（cssc、sast 207 岗、tecon、eic、gtgroup、xib、ehr-dian、zghkyjy）已入库；
  smics（变体 B）、kelun（另一结构）、casic/weiheng（路径不同）、glprop/biad/newhope/crrczzs（列表页无岗位链接）待后续

## 5. 已知陷阱
- 城市字段缺失（需要找详情接口；不要从标题猜）
- 部分租户在 `/custom/...` 自定义页面（cmhk、chinalife、coamc），接口是否相同待验证
- 某些租户校招页职位数为 0（如 sany 在侦察时）

## 7. 从 GitHub Actions 的可达性
全部 200，约 0.3s。

## 8. 下一步
新版门户：`adapters/beisen.py`。旧版门户：单独侦察 HTML 结构（smics 页面 80KB，含服务端渲染列表）。
