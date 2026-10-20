---
description: 侦察一个招聘平台或公司站点，产出 docs/recon/<name>.md。用法：/recon <name> <入口URL>
argument-hint: <name> <入口URL>
---

对 `$ARGUMENTS` 做侦察，产出 `docs/recon/<name>.md`（严格按 `docs/recon/TEMPLATE.md` 的结构填写）。**这一步只读，不写适配器。**

要求：
- 先读 `CLAUDE.md` 的合规铁律与 `docs/recon/README.md` 的优先级。
- 总共只发少量请求（每个站点 ≲ 20 次），间隔 ≥1 秒，只访问公开页面/接口，UA 用 `jobradar/0.1 (+项目地址)`。
- 先读 `robots.txt` 和站点服务条款，如实记录原文要点。
- 找页面背后的公开 JSON 接口（看页面加载的 XHR/JSON、`__NEXT_DATA__` / 内嵌 JSON、sitemap）。记录：方法、URL、参数、分页方式、返回结构、总量。
- **如果接口需要登录、验证码、或逆向签名/加密才能访问：结论写 `blocked`，写明原因，不要尝试绕过。**
- 平台型（Moka/北森等）：估算租户数量，给出 5–10 个租户样例，并说明租户标识怎么得到（例如 URL 里的 org 参数）。
- 记录校招特有信息：是否有届别、批次、岗位类型（校招/实习/社招）字段；是否有 JD 详情接口。
- 附 ≤50KB 的脱敏样本响应到 `docs/recon/samples/<name>/`。
- 结论只能是：`可做` / `待定（缺什么信息）` / `blocked（原因）`。
- 最后用一句话告诉用户：下一步是否可以 `/new-adapter`。
