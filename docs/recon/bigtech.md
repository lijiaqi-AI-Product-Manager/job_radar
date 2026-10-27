# 侦察：其他大厂校招站（第 22–24 轮，2026-10-20）

逐家只发 1–3 次请求（GitHub Actions，固定 UA）。结论：

| 公司 | 入口 | 结论 | 依据 |
|---|---|---|---|
| 快手 | campus.kuaishou.cn | ⛔ 不做 | robots.txt：`User-agent: * / Disallow: /` |
| 拼多多 | careers.pddglobalhr.com | ⛔ blocked | 前端含完整验证码流程（`/api/phantom/obtain_captcha`、`user_verify` 等）；robots.txt 返回 403 |
| 百度 | talent.baidu.com | ✅ 已接入 | 早期那个 `no-auth` 只是**缺 `Referer`**；补上后匿名可抓 694 条（`docs/recon/baidu.md`，2026-10-26） |
| 华为 | career.huawei.com | ⛔ blocked | 列表接口 `/reccampportal/services/portal/portalpub/getJob/newHr/page/...` 匿名返回 403 |
| 网易 | campus.163.com | ✅ 可做 | 2026-10-22 复侦察：公开 JSON `position/getJobList?projectId=…`，含 JD；见 `netease.md` |
| 小米 | hr.xiaomi.com | ⛔ 不做 | 2026-10-22 复侦察：只有品牌介绍页（校园招聘/项目/日程），投递走「小米招聘」公众号，无公开岗位列表 |
| 字节 | jobs.bytedance.com | ✅ 已接入 | 2026-10-26 推翻旧结论：405 是缺 `Accept: application/json` + 用错了 CSRF 值（cookie 里那个是 URL 编码的），`_signature` 服务端不校验；`sources/bytedance.yaml` 7,044 条 |

按 CLAUDE.md 铁律：验证码、需要登录/凭据、robots 禁止 → 不实现，不绕过。
已可做：腾讯校招（`tencent.md` §9）、美团（`meituan.md`）。阿里、京东见各自文档。

## 2026-10-22 复侦察：其他大厂的 ATS 归属

覆盖率攻坚时逐个探过一遍（判断"是不是北森白标"：POST `/api/Jobad/GetJobAdPageList`）：

| 公司 | 入口 | 归属 | 结论 |
|---|---|---|---|
| 大疆 | careers.dji.com → apply.careers.dji.com | 飞书 ATSX（定制域名） | 接口需浏览器抓包，见 `COVERAGE-PLAN.md` §4 |
| 蔚来 / 小鹏 | `*.jobs.feishu.cn` | 飞书 ATSX | ✅ 已接入（`adapters/feishu_atsx.py`，2026-10-26） |
| 比亚迪 | job.byd.com | 自研（Spring Boot） | `/portal/api/job/list` 返回 `Token无效或已过期: Not Authenticated` → 需登录态，blocked |
| OPPO | careers.oppo.com | 自研（Spring Boot + Vue） | `/api/Jobad/...` 返回 500；列表接口未找到公开出口 |
| 荣耀 / 联想 | honors/honor、lenovo 域 | 自研 | 招聘域名不可直连（ConnectError），需人工确认入口 |
| 安踏 | app.mokahr.com/campus-recruitment/antahr | Moka | 响应加密，按铁律不做 |
| 汇顶科技 | goodix.zhiye.com | **北森旧版** | ✅ 已接入（`beisen_legacy`，36 校招 + 64 社招） |
