# 平台识别与扩源扫描（2026-10-26 起）

> 覆盖率瓶颈不是「某家公司的岗位抓不抓得到」，而是**它用哪个 ATS**。
> 一个平台适配器 = 几十家公司。所以扩源的第一步永远是「批量识别平台」，而不是逐家读页面。

## 1. 三个脚本的分工

| 脚本 | 干什么 | 联网 | 产出 |
|---|---|---|---|
| `scripts/gen_slug_candidates.py` | 公司名 → 北森 slug 候选（拼音/英文品牌/去行业词） | 否 | `slugs.txt` + `slug_map.json` |
| `scripts/gen_career_urls.py` | 公司名 + 英文品牌 → 招聘入口 URL 候选 | 否 | `urls.txt` + 映射 JSON |
| `scripts/probe_beisen_tenants.py` | 逐个校验 `{slug}.zhiye.com` 是否真租户 | 是（1 req/s） | HIT 行 |
| `scripts/detect_ats.py` | 一批 URL → 平台识别（域名/跳转/指纹） | 是（4 并发） | 平台分组 JSON |

「生成候选」和「发请求」严格分开：前者可以随便重跑、可以随手改规则；
后者受 1 req/s 约束，每次都要算清预算。

## 2. 为什么之前的 `blocked.jsonl` 不可信

835 条全是 `no_entry`，证据统一写着「北森/大易/旧版三套平台各 6-14 个 slug 组合均无命中」。
问题在于那「6-14 个」是**人工凭感觉敲的**：`byd` / `byd1` / `byd2` / `bydauto`…，
既漏掉了本该命中的写法（拼音全拼 `biyadi`、去行业词 `changanqiche` → `changan`），
也没试过 `nginx` 式的前缀（`hr` / `zhaopin` / `campus`）。

`gen_slug_candidates.py` 把这件事变成规则：

| 规则 | 例（长安汽车 / 361度 / 中金公司） |
|---|---|
| 英文品牌名 | `changan` / `361degrees` / — |
| 中文全拼 | `changanqiche` / — / `zhongjingongsi` |
| 去掉行业后缀再拼：集团/股份/汽车/科技… | `changan` / — / `zhongjin` |
| 首字母缩写 | `cqc` / — / `zjgs` |
| 品牌紧凑写法（去空格/连字符） | — / `361degrees` / — |

## 3. detect_ats 的识别口径

只认**平台独有**的特征，宁可不识别也不误判：

- **域名级**（最可靠）：`*.zhiye.com` → 北森、`*.mokahr.com` → Moka、`*.jobs.feishu.cn` → 飞书 ATSX、
  `*.myworkdayjobs.com` → Workday、`*.hotjob.cn` → 大易 …
- **跳转后域名**：很多公司把 `career.example.com` CNAME 到平台，最终 URL 才是真相。
- **内容指纹**：`GetJobAdPageList` → 北森、`avature`/`SearchJobs` → Avature、
  `myworkdayjobs`/`data-automation-id="jobPosting"` → Workday。

扫描结果**只是线索**，不是「能接」的结论。接之前仍要：读 robots → 看接口形态 →
确认匿名可读 → 抓一页冒烟。这条链路见 `docs/internal/COVERAGE-PLAN.md` §4。

## 4. 2026-10-26 实测记录

### 4.1 北森 slug 重探（2,421 个候选）

`gen_slug_candidates.py --top 8` 对 835 家 blocked 公司生成 2,421 个 slug（含 eTLD 级别的去重）。

结果（1,201+ 个已探测）：**命中 1 个** —— `sanxia`，但页面标题是「三峡油漆」，
与名单里的「三峡集团」不是同一家（同名不同主体，和 `sunny`→天阳地产、
`haitian`→海天精工 是同一类坑）。**拒绝**。

结论：**拼音/英文品牌名这条路已经走到尽头**。剩余公司的租户 slug 要么是人工起的
（`hisense1`、`yuwellhr`、`ctghr`），要么根本不用北森。继续加 slug 变体是负收益。

### 4.2 招聘入口 URL 批量识别（2,888 个候选）

`gen_career_urls.py` 生成，`detect_ats.py` 识别。结果见 §4.3 回填。

### 4.3 平台矩阵（截至 2026-10-26）

| 平台 | 适配器 | 源数 | 已知可用入口形态 |
|---|---|---|---|
| 北森（新版）`{slug}.zhiye.com` | `beisen` | 400 | `POST /api/Jobad/GetJobAdPageList` |
| 北森（旧版） | `beisen_legacy` | 23 | `/campus/` 里的 `/zpdetail/<id>` |
| 大易 `wecruit*.hotjob.cn` | `hotjob` | 26 | 租户 id 在 URL 路径里 |
| Radancy | `radancy` | 2 | `/search-jobs` + `/job/<城市>/<slug>/<id>/<id>` |
| Avature | `avature` | 1 | sitemap → `/careers/JobDetail/<id>` |
| Workday | `workday` | 5 | CXS API `/wday/cxs/<tenant>/<site>/jobs` |
| 飞书 ATSX | `feishu_atsx` | 3 | 搜索 POST 需前端签名 → **受限于 405** |
| Moka | ⛔ | 0 | 响应 AES 加密 → 按红线不做 |
