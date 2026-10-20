# 侦察：其他大厂校招站（第 22–24 轮，2026-10-20）

逐家只发 1–3 次请求（GitHub Actions，固定 UA）。结论：

| 公司 | 入口 | 结论 | 依据 |
|---|---|---|---|
| 快手 | campus.kuaishou.cn | ⛔ 不做 | robots.txt：`User-agent: * / Disallow: /` |
| 拼多多 | careers.pddglobalhr.com | ⛔ blocked | 前端含完整验证码流程（`/api/phantom/obtain_captcha`、`user_verify` 等）；robots.txt 返回 403 |
| 百度 | talent.baidu.com | ⛔ blocked | 列表接口 `POST /httservice/getPostListNew` 匿名访问返回 `{"status":"no-auth","message":"illegal-visit"}` |
| 华为 | career.huawei.com | ⛔ blocked | 列表接口 `/reccampportal/services/portal/portalpub/getJob/newHr/page/...` 匿名返回 403 |
| 网易 | campus.163.com | ⬜ 待定 | 页面加载网易易盾（`cstaticdun.126.net/load.min.js`）；接口未确认，需谨慎 |
| 小米 | hr.xiaomi.com | ⬜ 待定 | 静态介绍页，职位列表在外部招聘系统，未侦察 |

按 CLAUDE.md 铁律：验证码、需要登录/凭据、robots 禁止 → 不实现，不绕过。
已可做：腾讯校招（`tencent.md` §9）、美团（`meituan.md`）。阿里、京东见各自文档。
