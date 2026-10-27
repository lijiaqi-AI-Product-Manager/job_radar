# 提示词：把 job_radar 的数据源从 500 家扩到 1000+（发给其他 AI 的完整任务书）

> 用法：把**本文件全文**复制给执行方 AI（建议用支持长任务的模型，并允许它联网、跑命令、写文件）。
> 下面第一行到文件末尾都是给它看的，不要删「附录」，那是它的契约依据。
> 执行方需要在 `job_radar` 仓库里工作；若它没有仓库访问权，让它**按本文格式交回产物**，由你合并。

---

## 0. 你的角色与最终交付

你是 `job_radar` 项目的**数据源拓荒者（recon + source expansion）**。这个项目是一个每日自动更新的中国校招/实习/社招岗位开放数据集：

- 数据只来自**各公司官方招聘页/官方 JSON 接口**，每天采集一次，发布成 SQLite，用户本地查询（CLI / MCP / Skill 给 AI agent 用）。
- 现在有 **279 个数据源**、**500 家目标公司**、约 **88,600 个在招岗位**；其中只有 **161/500** 家能拿到岗位级数据。
- 你的任务：**把可覆盖公司扩到 1000 家以上**，并带回**能直接合并**的侦察产物、sources 条目、fixtures 录制计划与测试。

**最终交付物（缺一不可，格式见第 6 节）**

1. `companies.jsonl` —— 1000+ 家公司的主数据（含官方招聘入口与 ATS 指纹）
2. `proposed-sources.yaml` —— 可直接追加进 `sources/*.yaml` 的片段（每家一行，参数完整）
3. `blocked.jsonl` —— 不可做的公司 + 原因码 + 证据（URL / 状态码 / 时间）
4. `recon/<company>.md` —— 每家可做公司一份，严格按 `docs/recon/TEMPLATE.md` 的 8 节
5. `samples/<company>/` —— 脱敏样本（列表第 1 页 / 详情 1 条 / 末页，每个 ≤50KB）
6. `fixtures-plan.md` —— 哪些源要录 fixtures、命令、`max_pages`、体积预估、脱敏点
7. `batch-report.md` —— 汇总表 + 统计 + 风险 + 待确认问题

**如果你只能先做一件事**：先把 1000 家公司的 `careers_url` + ATS 指纹 + 结论交回来（第 1、2、3 节）。sources 片段和 fixtures 可以下一批补。

---

## 1. 绝对红线（违反任何一条，整批作废）

这些是项目的铁律，写进 `CLAUDE.md`，不要"灵活处理"：

1. **只访问公开、无需登录的页面/接口。** 遇到**验证码、滑块、登录墙、需要逆向的签名/加密参数** → 立即停止，标 `blocked`，写清证据，**不要尝试绕过**。
2. **匿名会话可以，登录态不行。** 站点给匿名访客下发的 cookie/CSRF token 可以按浏览器顺序用（内存里用、不落盘）；用账号登录拿到的 cookie 一律禁止。
3. **限速：每个 host ≤1 请求/秒。** 同一个 host 不许并发。不要伪造 UA（用项目固定的 `USER_AGENT`），不要用代理池。
4. **不做第三方聚合站。** BOSS直聘、猎聘、智联、前程无忧、牛客、应届生求职网、脉脉、看准网、实习僧等**平台自身域名**一律不碰（它们在 `taxonomy/calendar.yaml` 的 `third_party_blocklist` 里）。
5. **不逆向加密/签名。** Moka 的响应是 AES 加密（`necromancer`）、飞书 ATSX 要前端 `_signature`、北森部分自研网关要 `hcm_param`——这些都是**平台主动设置的技术保护**，判定 `blocked`，不做解密实现。
6. **不把 LLM 放进采集流水线。** 归一化只用规则和 `taxonomy/` 映射表。你的产出是"给人审的侦察报告 + 配置"，不是运行时依赖。
7. **不新增依赖**（Playwright 已批准，但只在"公开页面必须执行 JS 才有内容、且找不到公开 JSON"时用）。
8. **不改** `src/jobradar/store/migrations/**`、`schema_lock.json`、`models.py`、`ingest.py` 里的阈值/下架规则。要改 schema = 停下来问人。
9. **不得虚构。** tenant / slug / 接口 / 岗位数，每一个都要有证据：URL + HTTP 状态码 + 响应片段 + 抓取时间。**空门户（页面存在但 0 个岗位）不算可做。**
10. **同名不同公司必须核对。** 见第 8 节的反面案例，代价是整个数据集被污染。

---

## 2. 现状基线（别重复劳动）

```
数据源 279 个：
  beisen（北森新版，{tenant}.zhiye.com）  236
  beisen_legacy（北森旧版，服务端渲染）     15
  hotjob（大易，{host}/wecruit/...）        12
  hotjob_legacy（大易旧版）                  6
  workday（外企）                            4   nvidia / intel / pfizer / astrazeneca
  自研站                                    6   tencent(社招) / tencent_campus / meituan / alibaba / netease×2
目标公司 500 家（targets/top_companies.yaml，18 个行业分组，22 条别名，17 条 blocked）
覆盖：日历或岗位数据 494/500；**岗位级数据只有 161/500**；在招岗位 ~88,600；JD 正文 99.8%
```

**已经 blocked 的 17 家（别再试，除非你能给出"平台改版/新增公开出口"的证据）**

| 公司 | 原因码 | 一句话证据 |
|---|---|---|
| 字节跳动 | ~~captcha+signature~~ 已接入 | 飞书 ATSX 匿名接口：早期 405 是缺 `Accept` 和 CSRF 原值，`_signature` 服务端根本不校验（`docs/recon/feishu-atsx.md`） |
| 大疆 | encrypted | 是 Moka，响应 `{data, necromancer}` 加密串 |
| 蔚来 / 小鹏汽车 | ~~signature~~ 已接入 | 同上，`adapters/feishu_atsx.py` |
| 京东 | ~~captcha~~ 已接入 | 只有 `campus.jd.com` 匿名可抓；`zhaopin.jd.com` 同路径会 302 到登录页（`docs/recon/jd.md`） |
| 拼多多 | captcha | 完整验证码流程 + robots 403 |
| 百度 | ~~login~~ 已接入 | `no-auth` 只是缺 `Referer`，补上即 200（`docs/recon/baidu.md`） |
| 华为 | login | 列表接口匿名 403 |
| 快手 | robots | `robots.txt: Disallow: /` |
| 博世 | robots | `smartrecruiters` 的 robots 对非 LinkedInBot 一律禁止 |
| BOSS直聘/猎聘/智联/前程无忧 | third_party | 平台自身域名在 `third_party_blocklist` |
| 微博 | login | 只暴露 Sina Visitor System 登录墙 |
| 招商蛇口 | no_entry | `cmsk.com` 域名已被域名商占用 |
| 中国建筑 | encrypted | `recruit.cscec.com` 请求/响应都走 `hcm_param` |

---

## 3. 任务 A：把公司清单从 500 建到 1200

**口径（必须都覆盖到，按这个顺序）**

1. **A 股 + 港股 + 美股中概**的上市公司（按行业分类），优先市值/员工规模靠前的；
2. **央企/国企名录**（国资委央企名录、各省属国企）——注意：这批多为自研站，命中率低但要记录；
3. **在华外企**（世界 500 强中国区 + 知名外企），优先 Workday / SAP SuccessFactors / SmartRecruiters 用户；
4. **独角兽/准独角兽**（AI、机器人、半导体、新能源、消费）；
5. **专精特新"小巨人"**（工信部名单）中招聘活跃的；
6. **校招热度榜**：各高校就业网/宣讲会名单里高频出现的雇主（注意：只用来"发现公司名"，不去抓这些站点的岗位数据）。

**命名与去重规则**

- `name` 用**公司对外简称**（与 `targets/top_companies.yaml` 的风格一致，如 `腾讯`、`比亚迪`、`京东方`）；
- 全称放 `legal_name`；英文名放 `name_en`；
- 同一集团下不同招聘主体（如 `阿里云`、`飞猪`）**单独成行**，但 `group` 字段填集团名；
- 去重：先按 `name`，再按官网域名（`careers_url` 的 host），最后按 ATS 的 `tenant`。

**`companies.jsonl` 每行字段（严格照此，不要加字段）**

```json
{"name":"比亚迪","legal_name":"比亚迪股份有限公司","name_en":"BYD","group":"比亚迪",
 "sector":"汽车与新能源","type":"cn_private",
 "careers_url":"https://job.byd.com/","ats":"unknown|beisen|beisen_legacy|hotjob|hotjob_legacy|workday|moka|feishu_atsx|self_built|smartrecruiters|successfactors",
 "tenant":null,"site":null,"recruit_types":["campus","intern","social"],
 "verdict":"doable|blocked|no_entry|empty",
 "jobs_estimate":null,"evidence":["https://job.byd.com/ 200 2026-10-25T02:10:00Z"],
 "checked_at":"2026-10-25T02:10:00Z","notes":""}
```

`sector` 取值固定（与 `targets/top_companies.yaml` 对齐）：互联网与软件 / 通信与电子硬件 / 半导体 / 汽车与新能源 / 智能制造 / 金融 / 医药与生物 / 快消与零售 / 地产与建筑 / 能源与电力 / 交通与物流 / 咨询与专业服务 / 游戏与内容 / AI 与大模型 / 央企与国企 / 外企。

---

## 4. 任务 B：找官方招聘入口（每家 1–3 分钟）

按顺序尝试，**记录每一次的 URL + 状态码 + 重定向终点**：

1. `https://careers.<domain>` / `https://job.<domain>` / `https://jobs.<domain>` / `https://hr.<domain>` / `https://zhaopin.<domain>`
2. 官网首页 → 找 `招聘|人才|加入我们|careers|jobs|join us|校园招聘` 的链接（**只看 href，不要执行 JS**）
3. `https://<domain>/robots.txt` 里的 `Sitemap:` 行（经常直接暴露招聘站）
4. 搜索引擎：`<公司名> 校园招聘 官网`（**只用它发现公司自己的域名**，不要用它的快照数据）

**判定**：入口 200 且能列出岗位 → 继续第 5 节；入口存在但 0 岗位 → `empty`（不算可做）；入口 403/登录 → `blocked`（原因码 `login`）。

---

## 5. 任务 C：ATS 指纹识别 + 租户发现

### 5.1 指纹表（看到这些特征就直接归类）

| 特征 | 平台 | 适配器 | 可做性 |
|---|---|---|---|
| `*.zhiye.com`，列表接口 `POST /api/Jobad/GetJobAdPageList` 返回明文 JSON | 北森新版 | `beisen` | ✅ |
| `*.zhiye.com`，列表是服务端渲染 HTML（`/campus/?PageIndex=N`、`/zpdetail/<id>`） | 北森旧版 | `beisen_legacy` | ✅ |
| `{host}/wecruit/positionInfo/listPosition/{SU...}`（`iSaJAx=isAjax`） | 大易 hotjob | `hotjob` | ✅ |
| `{tenant}.wd{1,2,3,5,103}.myworkdayjobs.com` + `/wday/cxs/...` | Workday | `workday` | ✅（注意限流） |
| `app.mokahr.com/campus_apply/...`，接口返回 `{data, necromancer}` | Moka | — | ❌ encrypted |
| `*.jobs.feishu.cn` / `jobs.bytedance.com` 前端要 `_signature` | 飞书 ATSX | — | ❌ signature |
| `*.italent.cn` / `*.beisen.com` 旧招聘云 | 北森旧云 | 待侦察 | ⚠️ |
| `smartrecruiters.com` | SmartRecruiters | — | ❌ robots |
| `*.successfactors.eu/career?company=...` | SAP SuccessFactors | 待侦察 | ⚠️（有公开 career 页） |
| 自研域名 + `/api/*` 明文 JSON | 自研站 | 需新适配器 | ⚠️ 一家一议 |

### 5.2 北森租户批量发现（当前最高杠杆，236 个源都来自这里）

- 候选 slug = 拼音全拼（`pypinyin`）+ 英文品牌名；**再试后缀** `1`、`hr`（真实案例：`hisense1`）。
- 判定：`GET https://{slug}.zhiye.com/` → **200 且 `<title>` 是公司名** = 命中；302 → `/404` = 不存在；200 但标题是**别家公司** = 同名不同公司，丢弃。
- **必须**用适配器再验一遍岗位数（页面 200 ≠ 有岗位），少于 1 条不算可做。
- 已知坑：`sunny`=天阳地产、`ctghr`=易才集团、`haitian`=海天精工、`dongpeng`=东鹏控股、`minmetalshr`=五矿考试中心。
- 可复用脚本：`scripts/probe_beisen_tenants.py`、`scripts/verify_beisen_tenants.py`（先读源码再改）。

### 5.3 大易 hotjob 租户

- 租户 id 形如 `SU` + 24 位十六进制，**不能猜**，只能从公司招聘页的 URL/HTML 里取（`career.honor.com` → `wecruit500.hotjob.cn/SU5fb.../pb/index.html` 这种重定向链就是线索）。
- 拿到 id 后先用 `GET {host}/wecruit/positionInfo/listPosition/{tenant}?iSaJAx=isAjax&isFrompb=true&recruitType=2&pageSize=5&currentPage=1` 试；返回 `{"state":"500","msg":"官网不存在"}` 说明 id 不是站点 id，换线索。
- 大易旧版（`hotjob_legacy`）是服务端渲染 HTML，字段在 `<li>` 里，需要单独看。

### 5.4 Workday 租户

- `GET https://{tenant}.wdN.myworkdayjobs.com/robots.txt`：`Sitemap:` 行里的路径通常就是 **site slug**；也有 `Allow: /{site}/` 的写法。
- 拿到 site 后 `POST https://{host}/wday/cxs/{tenant}/{site}/jobs`，body `{"appliedFacets":{},"limit":1,"offset":0,"searchText":""}`。
- **中国岗位判定**：响应里 `facets` 的 `locations`（`descriptor` 形如 `China, Shanghai`）或 `locationMainGroup`（`PRC, Shanghai`）或 `Location_Country`（精确值 `China`）。拿不到国家分面 → **不抓**，标 `no_china_facet`。
- **限流会咬人**：同一 IP 连续探测后 CXS 会开始返回 **303 / 500**（连本来可用的 `nvidia` 也会 303）。一旦出现，**立刻停 10 分钟以上**，或换时段；不要重试轰炸。
- 一个公司可能有多个 site（区域站/校招站），优先中国相关 site。

### 5.5 自研站

- 先看有没有公开 JSON：`GET` 页面 → 在 HTML/JS 里找 `/api/`、`/job/list`、`graphql`；很多自研站是 SPA + XHR。
- 有公开 JSON 且无签名 → 交"新适配器需求单"（格式见第 6.6 节），**不要自己改 `models.py`/`ingest.py`**。
- 只有 HTML → 记录 DOM 结构（列表项选择器、详情页字段位置），同样交需求单。

---

## 6. 产物格式（逐字照做）

### 6.1 `recon/<company-slug>.md`

严格按 `docs/recon/TEMPLATE.md` 的 8 节写。特别要求：

- 第 3 节必须给出**可直接复制的请求**：方法、URL、query/body、分页参数、每页上限、终止条件；
- 第 4 节填满字段映射表（`source_job_id` / `title` / `url` / `recruit_type` / `grad_year` / `batch` / `cities` / `degree_min` / `department` / `description` / `requirements`）；
- 第 6 节的样本放 `docs/recon/samples/<name>/`，**脱敏**（去 cookie/token/个人邮箱/手机号），每个文件 ≤50KB；
- 结论只能是 `可做` / `待定（缺什么）` / `blocked（原因+证据）`。

### 6.2 `proposed-sources.yaml`

可直接追加到对应 `sources/*.yaml` 的片段。平台型用 `defaults` + 每家公司一行：

```yaml
# 平台：beisen（北森新版）。侦察：docs/recon/beisen.md
defaults:
  adapter: beisen
  recruit_types: [campus, intern, social]
  rate_limit_rps: 1
  compliance:
    checked_on: 2026-10-25
    robots: allowed
    terms: "公开招聘门户，列表接口无需登录、无签名、明文 JSON"
    notes: ""
sources:
  - {id: beisen-cinda, company: 中国信达, params: {tenant: cinda}}          # 35 岗（2026-10-25 实测）
  - {id: beisen-yuwell, company: 鱼跃医疗, params: {tenant: yuwellhr}}       # 34 岗
```

命名规则（**必须**）：

- `id`：`<adapter>-<slug>`，全小写 + 连字符，例如 `beisen-cinda`、`workday-cisco`；
- `company`：与 `targets/top_companies.yaml` 里的写法**完全一致**（否则覆盖率统计对不上）；
- `params`：平台必需项写全（北森 `tenant`；Workday `host/tenant/site/country`；大易 `host/tenant`；自研 `max_pages` 等）；
- 每行末尾注释写**实测岗位数**和日期。

### 6.3 `blocked.jsonl`

```json
{"name":"字节跳动","reason_code":"captcha","evidence":["POST https://jobs.bytedance.com/api/v1/search/job/posts 405 2026-10-24T08:00:00Z","SSR 无 CSRF，页面部署滑块"],"checked_at":"2026-10-25T02:00:00Z","recon":"docs/recon/bytedance.md"}
```

`reason_code` 只能取：`captcha` / `login` / `signature` / `encrypted` / `robots` / `third_party` / `no_entry` / `empty` / `no_china_facet`。

### 6.4 `fixtures-plan.md`

每个要新增的源一行：

```markdown
| source_id | 适配器 | 录制命令 | max_pages | 预估体积 | 脱敏点 |
|---|---|---|---|---|---|
| beisen-cinda | beisen | `uv run python scripts/record_fixtures.py beisen-cinda --max-pages 1` | 1 | ~40KB | 无 cookie；岗位标题保留 |
```

规则：`tests/fixtures/<adapter_id>/` 里要有 `manifest.json` + `source.yaml`，**总大小 <300KB**；超了就用 `params.max_pages` 限量或裁剪列表 items。

### 6.5 `batch-report.md`

```markdown
# 第 N 批侦察报告（2026-10-25）

## 统计
- 本轮检查：120 家
- 可做（有岗位 + JD 可得）：38 家，预计新增岗位 12,400
- blocked：46 家（captcha 9 / login 7 / encrypted 12 / robots 2 / no_entry 10 / empty 6）
- 待定：36 家（缺：登录后页面、接口签名未知…）

## 明细表（按公司）
| 公司 | 招聘入口 | ATS | tenant/site | 类型 | 岗位数 | JD可得 | robots | 结论 | 证据 |
|---|---|---|---|---|---|---|---|---|---|

## 按平台汇总
| 平台 | 可做公司数 | 预计岗位 | 备注 |

## 风险与待确认
- …
```

### 6.6 新适配器需求单（`adapter-request-<platform>.md`）

现有 10 个适配器覆盖不了的平台，交这个：

```markdown
# 新适配器需求：<平台名>

- 平台类型：多租户 / 单公司
- 样例租户（5–10 个，含 URL 与标识）：
- 列表接口：方法 / URL / 参数 / 分页 / 每页上限 / 终止条件
- 详情接口（JD）：方法 / URL / 参数 / JD 在哪个字段
- 响应样本（脱敏，≤20KB）：
- 字段映射表（同第 6.1 节第 4 项）
- 中国岗位如何判定（国家/城市分面或字段）：
- 岗位唯一 id 字段：
- 岗位页 URL 构造：
- robots / 条款要点：
- 预计覆盖公司数与岗位量：
- 风险（限流/加密/字段缺失）：
```

---

## 7. 验收标准（你要自检并把输出贴进报告）

一个源算"可做"，必须同时满足：

1. 招聘入口是**公司官方域名**（不是聚合站）；
2. 列表接口**无登录、无验证码、无签名**，且返回明文（JSON 或可解析 HTML）；
3. 至少能拿到 **1 条真实岗位**（标题 + 可点开的 URL + 唯一 id）；
4. **≥90% 的岗位能拿到 JD 正文**（职责/要求原文）——拿不到就只发日历、不进数据集；
5. `robots.txt` 允许（或该接口不被 robots 覆盖），条款无禁止自动化；
6. 页面标题/岗位内容能对上公司名（防同名不同公司）；
7. 实测请求频率 ≤1 rps 时不会被封（给出你观察到的行为）。

自检命令（在仓库根目录）：

```bash
uv run pytest tests/test_adapter_contract.py -q          # 适配器契约（fixtures + JD ≥90%）
uv run pytest -q                                          # 全量测试（必须绿）
uv run ruff check .
uv run python scripts/check_docs_links.py                 # 文档断链/版本/安装名一致性
uv run python scripts/smoke_sources.py <source_id>         # 新增源上线前冒烟（真实抓一页）
uv run python scripts/release_check.py --home ~/.jobradar   # 8 项发布门槛
```

---

## 8. 反面案例（这些都是真踩过的，逐条对照）

| 案例 | 教训 |
|---|---|
| `--company 京东` 返回了**京东方** 200+ 条 | 前缀只差一个字 ≠ 同一家公司；必须核对页面标题与岗位内容 |
| `sunny.zhiye.com` 是**天阳地产**，被当成舜宇光学 | slug 猜中 ≠ 公司对；标题核对是必做项 |
| `haitian.zhiye.com` 是**海天精工**（机床），被当成海天味业 | 集团名相似的两家完全不同 |
| `dongpeng.zhiye.com` 是**东鹏控股**（陶瓷），被当成东鹏饮料 | 同上 |
| `minmetalshr` 是**五矿考试中心**（笔试题库） | "有页面" ≠ "有岗位" |
| `5i5j` 我爱我家：门店销售帖 + 标题含招聘人姓名 | 内容质量与 PII 风险，校招数据集不收 |
| 华夏基金新旧门户都能列岗，但**详情页取不到 JD** | 按铁律放弃，不进数据集 |
| 荣耀 `career.honor.com` → 大易 `SU...`，但列表接口返回"官网不存在" | 租户 id ≠ 站点 id，别硬接 |
| Workday 连续探测后连 `nvidia` 都返回 303 | 限流要停手，不要重试轰炸 |
| 中国五矿、中国建筑等自研网关用 `hcm_param` 加密 | 不逆向，标 blocked |

---

## 9. 节奏与批次（重要）

- **每批 ≤50 家公司**，一批一个 `batch-report.md`，便于人审；
- 顺序：**先平台型（北森/大易/Workday）后自研站**——平台型一次能覆盖几十家，自研站一家半天；
- 每批先交 `companies.jsonl` 增量 + `proposed-sources.yaml` 片段 + `blocked.jsonl` 增量，再交 recon md；
- **不要一次交 1000 家**：第一批先做 50 家跑通格式，等人确认格式无误再放量；
- 遇到需要改 schema / 改 ingest 规则 / 新增依赖的情况：**停下来问人**，不要自行决定。

---

## 10. 回报模板（直接复制填）

```markdown
## 第 N 批交付

**范围**：<公司清单来源 + 数量>

**结果**：可做 X 家 / blocked Y 家 / 待定 Z 家 / 预计新增岗位 K

**可直接合并的产物**
- [ ] companies.jsonl（本批 X 行）
- [ ] proposed-sources.yaml（X 条，已按平台分组）
- [ ] blocked.jsonl（Y 条，每条带证据）
- [ ] recon/<company>.md（X 份）
- [ ] samples/<company>/（脱敏，≤50KB/份）
- [ ] fixtures-plan.md（含录制命令与体积预估）
- [ ] adapter-request-<platform>.md（如有新平台）

**自检输出**（贴命令与结果）
- pytest / ruff / check_docs_links / smoke_sources

**需要人决定的事**
1. …
```

---

## 附录 A：现有适配器能力表（决定新公司归哪个 adapter）

| adapter | 平台 | 必需 params | recruit_types | 备注 |
|---|---|---|---|---|
| `beisen` | 北森新版 `{tenant}.zhiye.com` | `tenant` | campus/intern/social | 明文 JSON；分页 `PageIndex/PageSize` |
| `beisen_legacy` | 北森旧版（服务端渲染） | `tenant`、`portal`(默认 campus)、`recruit_type` | campus | 变体 B 用 `params.variant: b` |
| `hotjob` | 大易新版 | `host`、`tenant` | campus/intern/social | `recruitType` 1/2/3 |
| `hotjob_legacy` | 大易旧版 | `host`、`tenant` | campus | HTML 解析 |
| `workday` | Workday | `host`、`tenant`、`site`、`country`(默认 China) | social/intern | 可选 `location_facet`、`country_exact`、`max_pages` |
| `tencent` / `tencent_campus` | 腾讯自研 | — | social/campus | 详情接口补 JD |
| `alibaba` / `meituan` / `netease` | 自研 | — | — | 匿名会话/JSON |

## 附录 B：字段契约（`src/jobradar/models.py`）

`Job`（适配器唯一输出）：`source_id, source_job_id, company, url, title, recruit_type(campus/intern/social), category, subcategory, grad_year, batch, cities[], degree_min, department, description, requirements`

`SourceConfig`：`id`（`^[a-z0-9][a-z0-9_-]*$`）、`company`、`adapter`、`params`、`recruit_types`、`enabled`、`rate_limit_rps`（≤5）、`compliance`

`Compliance`：`checked_on`(日期)、`robots`、`terms`、`notes` —— **`enabled: true` 的源必须有这个记录**，否则加载直接报错。

## 附录 C：目录与命名

```
sources/                公司清单（yaml）。`_` 开头是示例，不加载
taxonomy/               职类/城市/学历/批次映射表（不要改，除非人同意）
targets/top_companies.yaml   500 家目标（sectors / aliases / blocked）
docs/recon/             侦察结论（你的主战场）+ samples/
tests/fixtures/<adapter>/     录制响应 + manifest.json + source.yaml（<300KB）
tests/adapters/test_<adapter>.py   专属测试
```

命名：适配器 id `小写蛇形`；source id `小写 + 连字符`（`<adapter>-<slug>`）；迁移文件 `NNNN_动词_对象.sql`（你不该碰）；提交信息 `adapter(<id>): ...` / `sources: ...` / `docs: ...`。

## 附录 D：可复用工具（先读源码再跑）

- `scripts/scan_careers.py` —— 从域名列表扫招聘入口
- `scripts/probe_beisen_tenants.py` / `verify_beisen_tenants.py` —— 北森租户探测/验证
- `scripts/record_fixtures.py <source_id> --max-pages N` —— 录 fixtures（会发真实请求）
- `scripts/smoke_sources.py <source_id>` —— 新增源冒烟
- `scripts/recon_probe.py` —— Actions 环境下的可达性探测
- `scripts/coverage_report.py` —— 覆盖率报告

## 附录 E：目标公司文件格式（你要追加到的 `targets/top_companies.yaml`）

```yaml
sectors:
  互联网与软件: [腾讯, 阿里巴巴, 字节跳动, ...]
  半导体: [中芯国际, 长江存储, ...]
aliases:
  中核集团: [中国核工业集团]
  航空工业: [中国航空研究院, 成都飞机设计研究所, 沈阳飞机工业]
blocked:
  字节跳动: "captcha + signature（docs/recon/bytedance.md）"
```

**扩到 1000+ 时要做的**：在 `sectors` 里按行业追加公司名（保持一行一个行业的风格），把不可做的写进 `blocked` 并注明 recon 文档路径；**不要**把聚合站、招聘平台写进 `sectors`。

## 附录 F：最终目标与验收口径

- **公司数 ≥1000**（`targets/top_companies.yaml` 的 sectors 去重后总数）；
- **岗位级覆盖 ≥400 家**（当前 161；这是"能力"指标，不是"名单"指标）；
- **日历覆盖 1000/1000**（每家至少一条日历条目，含届次/项目类型/投递入口/来源/时间戳）；
- **JD 正文 ≥90%**（每个新源都要过契约测试）；
- **全部 blocked 有证据**（`blocked.jsonl` + recon md）；
- 新增源 **全部有 fixtures + 专属测试**，`uv run pytest` 全绿。

---

## 最后：给执行方的 5 句话

1. **先跑通格式再放量**：第一批 50 家，格式对了再继续。
2. **证据 > 结论**：每个"可做/不可做"都要带 URL、状态码、时间、样本。
3. **平台优先**：北森/大易/Workday 一次能覆盖几十家，自研站一家半天。
4. **限流是硬约束**：1 rps/host；被 303/403 挡就停手，不要换 IP、不要并发轰炸。
5. **不确定就写"待定（缺什么）"**：编造一个 tenant 比漏掉十家公司危害大得多。
