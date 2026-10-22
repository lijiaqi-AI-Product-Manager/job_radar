# 侦察：其他大厂校招站（第 22–24 轮，2026-10-20）

逐家只发 1–3 次请求（GitHub Actions，固定 UA）。结论：

| 公司 | 入口 | 结论 | 依据 |
|---|---|---|---|
| 快手 | campus.kuaishou.cn | ⛔ 不做 | robots.txt：`User-agent: * / Disallow: /` |
| 拼多多 | careers.pddglobalhr.com | ⛔ blocked | 前端含完整验证码流程（`/api/phantom/obtain_captcha`、`user_verify` 等）；robots.txt 返回 403 |
| 百度 | talent.baidu.com | ⛔ blocked | 列表接口 `POST /httservice/getPostListNew` 匿名访问返回 `{"status":"no-auth","message":"illegal-visit"}` |
| 华为 | career.huawei.com | ⛔ blocked | 列表接口 `/reccampportal/services/portal/portalpub/getJob/newHr/page/...` 匿名返回 403 |
| 网易 | campus.163.com | ✅ 可做 | 2026-10-22 复侦察：公开 JSON `position/getJobList?projectId=…`，含 JD；见 `netease.md` |
| 小米 | hr.xiaomi.com | ⛔ 不做 | 2026-10-22 复侦察：只有品牌介绍页（校园招聘/项目/日程），投递走「小米招聘」公众号，无公开岗位列表 |
| 字节 | jobs.bytedance.com | ⛔ blocked | 2026-10-22 复侦察：列表接口 POST 仍 405，页面未下发 CSRF token，站点部署滑块验证；见 `bytedance.md` |

按 CLAUDE.md 铁律：验证码、需要登录/凭据、robots 禁止 → 不实现，不绕过。
已可做：腾讯校招（`tencent.md` §9）、美团（`meituan.md`）。阿里、京东见各自文档。
