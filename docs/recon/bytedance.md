# 侦察：字节跳动招聘 jobs.bytedance.com

- 侦察日期：2026-10-20 / 2026-10-22（判 blocked）；**2026-10-26 复测，结论改为可用**
- 结论：**可用（campus）**，适配器 `src/jobradar/adapters/bytedance.py`，源 `sources/bytedance.yaml`
- 规模：**7044 条在招**（校招正式 2313 + 实习 4731），一次抓取约 72 秒
- 类型：自研站（基于飞书招聘 ATSX 门户）

## 1. 上一版为什么判成 blocked

旧结论（本文档 2026-10-22 版）写：

> 带 Referer/Origin 的 `POST /api/v1/search/job/posts` → **405**，响应体为空。
> 按 CLAUDE.md 铁律 1：不逆向前端生成令牌 → 不实现。

那个判断有**两处偏差**，都在本次实测中被证伪：

1. **405 不是"缺签名"，是"缺 `x-csrf-token`"**。逐个变量做对照实验（见 §2），
   去掉 `_signature` 照样 200，把 `_signature` 改成垃圾照样 200；去掉 `x-csrf-token` 立刻回落成 405。
2. **`x-csrf-token` 必须是 `POST /api/v1/csrf/token` 响应 body 里的 `data.token` 原值**，
   不是 `Set-Cookie` 里那个——cookie 值是 URL 编码过的（`...%3D`），header 送编码值 = 405。
   而且这个 token 是**站点匿名下发的**，不是前端运行时算出来的签名。

另一个隐坑：**`Accept: application/json` 也参与路由**。不带它（curl 默认 `*/*`）同样 405。
两次 405 长得一模一样，所以很容易误判成"接口不存在"。`GET` 同一路径不报 405，
而是 200 返回「字节跳动猎头平台」的 HTML——这也是判成 blocked 的另一个诱因。

页面里确实加载了 `verify.snssdk.com/static/pc_slide.js`（滑块），但**匿名请求列表接口不触发它**，
只在提交表单/高频访问时出现。本适配器只读列表，不碰任何提交动作。

## 2. 对照实验（2026-10-26 05:36–05:40 CST，全部真实请求）

| 变量 | 结果 |
|---|---|
| 完整复现浏览器请求（含 `_signature`） | **200** JSON |
| `_signature` 末 4 位改成 `AAAA` | **200** —— 签名不校验 |
| 去掉 `_signature` 参数 | **200** |
| 去掉 `x-csrf-token` | 405 |
| `x-csrf-token` = 随机串 | 405 |
| `x-csrf-token` 用 cookie 里那个（URL 编码）值 | 405 |
| 去掉 `Accept`（curl 默认 `*/*`） | 405 |
| 去掉 `website-path` / `portal-channel` / `portal-platform` / `Referer` / `Origin` | 200，均非必需 |
| 去掉全部 cookie（`s_v_web_id` 等） | 200，非必需 |
| 纯 httpx：`csrf/token` → 带 `x-csrf-token` + `Accept` 请求列表 | **200**，无浏览器也可 |

## 3. 可用接口

| 用途 | 请求 | 说明 |
|---|---|---|
| 取 token | `POST /api/v1/csrf/token`，body `{"portal_entrance":1}` | 200，`data.token` 与 `atsx-csrf-token` cookie 同值（cookie 版 URL 编码） |
| 岗位列表 | `POST /api/v1/search/job/posts?portal_type=3&limit=100&offset=0&portal_entrance=1` | 200，`data.job_post_list` + `data.count` |
| 筛选项 | `GET /api/v1/config/job/filters/3` | 200，9 个一级职类、93 个城市、社招/校招类型 |
| 地区树 | `GET /api/v1/config/location/nodes/?portal_type=6` | 200（3.2 MB） |

列表接口**一次给全**：`description`（职责）、`requirement`（要求）、`job_category`、
`city_list`（**多城市**，`city_info` 只是第一个）、`job_subject`（招聘项目名）、
`recruit_type`（正式/实习）、`publish_time`（毫秒）、`code`。
**不需要逐岗请求详情页**——这家 JD 覆盖率是 100%。

分页：`offset` 生效（0 / 10 / 7040 三档返回不同数据），`limit` 实测可到 100。
`data.count` = 7044，`data.extra` 里另带 `fe_tracking.total`（同值）。

## 4. 数据口径

- `portal_type` 不影响返回集合，**社招岗会混进来**：本适配器用 `job_subject` + `recruit_type`
  两个字段判断，只保留校招/实习，社招整条跳过。
- 招聘项目名即批次：`2027届校园招聘`、`2027届前沿技术领域人才校招`、
  `ByteIntern`、`日常实习`。届别**先看项目名**，项目名没写才看标题，最后才用 JD 正文兜底。
- **JD 兜底有陷阱**（本次踩到，已写进适配器与测试）：2023 年上架、一直挂到今天的
  「客户端开发实习生-抖音研发」，JD 里写的是"2023届"。按 JD 取届别就会写出「2023届在招」。
  规则：JD 兜底只对发布时间 ≥ 本年度招季起点（7-1）的岗位生效，更早的一律留空。
- `publish_time` 是毫秒时间戳，按东八区落日期（跨零点那条实测会差一天）。
- **上游 `_enrich` 也不许再补届别**：`pipeline/crawl.py::_enrich` 原来会在适配器留空时用
  `grad_year_from_jd` 再算一次，等于把刚判废的 JD 届别又填回去（实测 2150 条被改错）。
  已删除该分支——届别只由适配器判定。

## 5. 抓取成本与合规

- `robots.txt`：`Allow: /experienced`、`/society`、`/campus`、`/en`、`/jp`；只 `Disallow: /referral`。
  `jobs.toutiao.com` 是同一份规则（同一套 ATSX）。本适配器只碰 `/campus` 与 `/api/v1`。
- 频率：1 req/s（`rate_limit_rps: 1`）。成本 = 1 次 token + 71 页 ≈ **72 秒/天**。
- 匿名：不登录、不提交任何表单、不碰 `/referral`（robots 明确禁止）。
- 会话 token 只在内存里流转，录 fixtures 时按 `secret_patterns` 脱敏成 `REDACTED`。

## 6. 同平台的其他公司（同一套 ATSX）

| 公司 | 入口 | 状态 |
|---|---|---|
| 字节跳动 | jobs.bytedance.com | **已接入** |
| 蔚来 | nio.jobs.feishu.cn | **已接入**（同一套握手，869 条；见 `docs/recon/feishu-atsx.md`） |
| 小鹏 | xiaopeng.jobs.feishu.cn | **已接入**（`/campus` 站，629 条） |
| 大疆 | apply.careers.dji.com | 不是 ATSX，是 Moka（响应加密），仍 blocked |

> 这条对"上千家目标公司"有杠杆效应：一个 ATSX 适配器能吃下所有飞书招聘租户。
> 本次只补字节跳动，其余留作下一轮。

## 7. 复现步骤

```bash
# 1) 取 token
curl -s -X POST https://jobs.bytedance.com/api/v1/csrf/token \
  -H 'Content-Type: application/json' -d '{"portal_entrance":1}'
# → {"code":0,"data":{"token":"..."}}

# 2) 用 data.token 请求列表（注意 Accept 与 x-csrf-token）
curl -s 'https://jobs.bytedance.com/api/v1/search/job/posts?portal_type=3&limit=10&offset=0&portal_entrance=1' \
  -X POST -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -H 'x-csrf-token: <上一步的 token>' -H 'website-path: campus' \
  -d '{"keyword":"","limit":10,"offset":0,"job_category_id_list":[],"tag_id_list":[],"location_code_list":[],"subject_id_list":[],"recruitment_id_list":[],"portal_type":3,"job_function_id_list":[],"storefront_id_list":[],"portal_entrance":1}'
```

## 8. 踩坑记录

| 现象 | 真实原因 |
|---|---|
| `POST /api/v1/search/job/posts` → 405，body 空 | 缺 `x-csrf-token` 或 `Accept` |
| `GET` 同路径 → 200 但返回「字节跳动猎头平台」HTML | GET 不是该路由，网关回落到了默认站点 |
| `/atsx/api/v1/...` → 404 | 前端 JS 里的 `"/atsx"` 前缀属于另一套服务，与 search 无关 |
| `/api/v1/job/posts/{id}` → 只有 `recommend_job_post_List` | 该接口要登录态；但列表已含 JD，用不上 |
| cookie 里的 `atsx-csrf-token` 当 header 用 → 405 | cookie 值是 URL 编码过的（`%3D` 结尾），header 要原值 |
| 页面 900KB 里没有职位 HTML | SPA + `for-seo` 空壳；数据只在 XHR 里（本次已能直接取 XHR） |
