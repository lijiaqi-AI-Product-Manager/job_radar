# 侦察：字节跳动（jobs.bytedance.com）

- 侦察日期：2026-10-20；2026-10-22 按"匿名会话"政策复侦察
- 侦察人：Claude 会话（recon-probe 第 1、4、9 轮）；DeepSeek agent（2026-10-22，本机直连）
- **结论：blocked**
- 类型：自研站（基于飞书招聘 atsx 门户）

## 2026-10-22 复测（匿名会话政策之后）

- `GET https://jobs.bytedance.com/campus` → 200（827KB SSR 页面），未下发任何 cookie。
- 页面含 `csrfToken` 字样与 `verify.snssdk.com/static/pc_slide.js`（滑块），但**没有可直接使用的 token 值**
  （`"csrfToken":"…"` 不出现；`use_window_csrfToken_ua: "aweme"` 表示令牌由前端运行时注入）。
- 带 Referer/Origin 的 `POST /api/v1/search/job/posts` → **405**，响应体为空。
- 按 CLAUDE.md 铁律 1：不逆向前端生成令牌、不绕过滑块 → 不实现。

## 发现
- robots.txt：`Allow: /campus`、`/experienced`、`/society`，`Disallow: /referral`
- 页面 900KB，前端渲染，静态资源来自 `lf-package-cn.feishucdn.com/obj/atsx-throne/hire-fe-prod/portal/campus/`
- 页面加载 **`verify.snssdk.com/static/pc_slide.js`（滑块验证码）**，配置中有 `csrf_block_strategy`
- `POST /api/v1/search/job/posts`（不带 token）返回 405

## 判断
职位接口需要 CSRF token，且站点部署了滑块验证与拦截策略。按 CLAUDE.md 铁律 1，不尝试获取 token 或绕过验证。
除非找到无需 token 的公开数据出口（例如 sitemap、公开的静态岗位页），否则不做。

## 下一步（可选）
- 检查是否有 sitemap / 静态岗位详情页可直接读取（只读、低频）
- 同样基于飞书招聘的其他公司站点情况相同
