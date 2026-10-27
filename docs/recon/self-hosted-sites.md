# 自研站侦察笔记：三个「看起来抓不到、其实抓得到（或反之）」的案例

侦察时间：2026-10-26 14:1x–14:26 CST
适用：所有「大厂自研招聘站」类目标（不是北森/大易/Moka 那类 SaaS ATS）

这三个案例的共同点是：**HTTP 状态码不告诉你真相**，真正的门槛在业务字段或域名里。

| 公司 | 表面现象 | 真相 | 结论 |
|---|---|---|---|
| 百度 | `200` + `{"status":"no-auth"}` | 缺 `Referer` | ✅ 可抓 694 条 |
| 京东 | `302` → 登录页 | **域名选错** | ✅ 可抓 355 条 |
| 华为 | `405` / `403` | 方法错 / WAF | ❌ blocked |

---

## 1. 百度：业务层的「未授权」不是 HTTP 401

```
POST https://talent.baidu.com/httservice/getPostListNew?recruitType=GRADUATE
→ 200 {"status":"no-auth","message":"illegal-visit"}
```

HTTP 层完全正常（200），错误在业务字段里。如果只看 `raise_for_status()`，会以为是"返回了空数据"。

**两个独立的门槛**：

1. `recruitType` 必须**同时出现在 query 和 body**。只在 body → `Illegal argument : recruitType`；
   只在 query → `不支持的请求，请核实`。
2. 必须带 `Referer: https://talent.baidu.com/jobs/list?recruitType=GRADUATE`。
   **只带 `Origin` 无效**（实测仍 `illegal-visit`）。

类型名也和直觉相反：校招是 **`GRADUATE`**，不是 `CAMPUS`。

→ 详见 `docs/recon/baidu.md`

---

## 2. 京东：同一路径，换个域名就从 302 变 200

```
GET https://zhaopin.jd.com/api/wx/position/getProjectList  → 302 passport.jd.com/new/login.aspx
GET https://campus.jd.com/api/wx/position/getProjectList    → 200 {"success":true,...}
```

**同路径、同参数、同 UA，只差域名。** 加 `Referer` 救不了 `zhaopin`。

首次侦察（2026-10-20）当时记为 blocked（验证码），因为首页加载
`jcap.m.jd.com/home/requireCaptchaPc.js`。这次把 `umi.js` 拉下来读 `parseParam` 后发现：
**验证码挂在投递环节，列表接口本身不触发**。

教训：**「首页有验证码脚本」≠「数据接口有验证码」**。要看具体接口，不要按首页下结论。

另外三个参数坑：
- `pageIndex` 从 **0** 开始（不是 1）
- `pageCount` 恒为 0，只有 `totalNumber` 可信
- 筛选字段是 `positionDeptList`，写错会得到 **Tomcat 的 400 HTML**（不是 JSON）：
  这种"连 JSON 都不是"的错误最容易被误判成"接口挂了"

→ 详见 `docs/recon/jd.md`

---

## 3. 华为：接口确实存在，但有两道墙

```
GET https://career.huawei.com/reccampportal/services/portal/portalpub/getJob/newHr/page/{size}/{page}?jobType=0
```

| 时间 | 结果 |
|---|---|
| 14:1x | `GET` 可用：`jobType=0`（校招）返回 **0 条**；`jobType=1/3/4/5/-2/-3` 恒返回同一批 **2 条社招** |
| 14:2x | 所有 `jobType` 全部 `403 Forbidden`（WAF 拦截页，HTML） |

另外：`POST` 该路径 → `405 Method Not Allowed`，只吃 GET。

判断：即使 WAF 撤掉，校招也是 0 条——接口通了不等于有数据。
**不绕 WAF**（CLAUDE.md 铁律），记 blocked。

---

## 4. 可复用的排查顺序

按这个顺序查，能避免 90% 的误判：

1. **页面能不能开**（`curl -L`，看最终 URL 有没有跳登录）
   - 跳了 → 试**其它域名**（`campus.` / `careers.` / `job.` / `hr.` / `zhaopin.`），别急着判死
2. **前端 JS 里的接口清单**（`grep -oE '"/api/[^"]*"' app.js`）
   - 有 `getCaptchaSession` / `verifyToken` → 验证码在**哪个环节**？列表还是投递？
3. **接口本身**：先 `GET`，再 `POST`（405 说明方法错，不是没权限）
4. **200 也要看 body**：`status` / `success` / `code` 字段
5. **缺什么头**：`Referer` → `Origin` → `X-Requested-With`，逐个加
6. **参数名逐字抄 JS**，不靠猜（`positionDeptList` vs `deptCodeList`）

## 5. 合规边界（本轮的实际取舍）

| 做法 | 是否采用 | 理由 |
|---|---|---|
| 带同源 `Referer` | ✅ | 浏览器本来就会带，不是伪造身份 |
| 换一个无登录墙的公开子域 | ✅ | 公开页面 |
| 诚实爬虫 UA（`jobradar-bot/0.1`） | ✅ | 不伪装浏览器 |
| 带 URL 的长 UA | ❌ | 公众号会拦（见 `calendar-window.md` §3），且不必要 |
| 绕 WAF / 逆向签名 / 试 Cookie | ❌ | 铁律 |
| 抓 `storage.360buyimg.com` | ❌ | 其 robots 是 `Disallow: /` |
