# 侦察：京东校招（campus.jd.com）

- 侦察日期：2026-10-20（recon-probe 第 16、17、19 轮）
- **结论：blocked（验证码）**

## 发现
- 首页加载 `jcap.m.jd.com/home/requireCaptchaPc.js`；前端脚本中有 `/api/officialsite/getCaptchaSession`、`/api/officialsite/verifyToken` 与滑块回调。
- 静态资源域名 storage.360buyimg.com 的 robots.txt 为 `User-agent: * / Disallow: /`。
- 列表接口路径未在不触发验证码的前提下确认。

## 判断
按 CLAUDE.md 铁律：遇到验证码立即停止，不实现。
