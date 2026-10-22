# 侦察：SmartRecruiters（外资常用，如博世）

- 侦察日期：2026-10-22
- 侦察人：DeepSeek agent（本机直连，固定 UA）
- **结论：blocked（robots 禁止）**
- 类型：平台（SmartRecruiters 公开 Posting API）

## 发现

技术上是通的，但合规不允许：

- `https://api.smartrecruiters.com/robots.txt` 返回：

  ```
  User-agent: LinkedInBot
  Allow: /v1/companies/
  User-agent: *
  Disallow: /
  ```

- 也就是说：**除 LinkedInBot 外，所有爬虫都被禁止访问 `/v1/companies/`**，而职位列表/详情
  正是这个路径。
- 接口本身（`GET /v1/companies/BoschGroup/postings?country=cn`）无需登录、无签名，
  能返回 1,331 个中国岗位、详情含 JD——但按 CLAUDE.md 铁律 1（robots 明确禁止 → 不实现），
  **不接入**。

## 影响的目标

- 博世（BoschGroup）：确认在 SmartRecruiters 上，但按 robots 不做。
- 其他用 SmartRecruiters 的外资公司同理。

## 备注

- 如果将来博世官网/Welcome to Bosch 站点提供了自己的公开职位页（非 api.smartrecruiters.com
  域），应优先看那个域名的 robots 与条款，而不是绕过这里的限制。
