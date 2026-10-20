# 侦察：阿里巴巴校招（campus-talent.alibaba.com）

- 侦察日期：2026-10-20（recon-probe 第 16、18、19 轮）
- **结论：blocked（需要页面下发的 token 与会话 cookie）**

## 发现
- 前端单页应用，列表接口 `POST /position/search`（脚本 `g.alicdn.com/CPO-platform/recruit-portal/.../index.js`）。
- 不带任何凭据直接 POST 返回 **403**。
- 页面内嵌 `window.__sysconfig = {__token__: "..."}`，接口需要携带该 token 并保持会话 cookie。

## 判断
按 CLAUDE.md 铁律：不存 cookie/token、不绕过访问控制。取页面 token + 会话 cookie 再调用接口，属于模拟浏览器会话，不做。
如官方提供无需凭据的公开接口或数据导出，再重新评估。
