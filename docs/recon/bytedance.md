# 侦察：字节跳动（jobs.bytedance.com）

- 侦察日期：2026-10-20
- 侦察人：Claude 会话（recon-probe 第 1、4、9 轮，从 GitHub Actions 发出）
- **结论：待定（大概率 blocked）**
- 类型：自研站（基于飞书招聘 atsx 门户）

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
