# 侦察：阿里巴巴校招（campus-talent.alibaba.com）

- 侦察日期：2026-10-20（recon-probe 第 16、18、19 轮）；2026-10-21 复查（第 35–38 轮）
- **结论：可做（匿名会话，2026-10-21 起符合 CLAUDE.md 铁律 1）**
- 类型：自研站；适配器 `alibaba`，源 `alibaba`

## 发现
- robots.txt：404（无规则）。
- 打开公开职位页 `/campus/position`：站点给匿名访客下发 `SESSION`、`XSRF-TOKEN` 等 cookie，页面内嵌
  `window.__sysconfig = {__token__: "<uuid>"}`。
- 批次：`POST /searchCondition/listBatch?_csrf=<token>`（空请求体）→ `content.graduate / internship / topTalentPlan`，
  2026-10-21 为「阿里巴巴2027届应届生」（招聘对象 2026-11-01 至 2027-10-31 毕业）、「阿里巴巴日常实习生」、
  「阿里巴巴研究型实习生」、「阿里星-27届应届生」（与应届生同一 batchId）。
- 列表：`POST /position/search?_csrf=<token>`，JSON `{"batchId", "pageIndex", "pageSize", "channel": "campus_group_official_site", "language": "zh"}`
  → `content.datas[]`、`content.totalCount`（应届生批次 458）。每条含 `name`、`workLocations`、`circleNames`、
  `categoryName`、`batchName`、**`description`（职责）与 `requirement`（要求）原文**。
- 不带 token 直接 POST → 403；带页面下发的 token 与会话 cookie → 200（第 38 轮，纯 httpx，无需浏览器）。
- 无验证码、无签名参数、无需登录。

## 判断
2026-10-20 时按旧铁律（不使用 cookie/token）判 blocked。用户 2026-10-21 批准匿名会话后复查：
token 与 cookie 是站点下发给任何匿名访客的，按浏览器正常顺序使用、只在内存里，不伪造不逆向 → 可做。
fixtures 录制时按适配器 `secret_patterns` 把 token 替换为 `REDACTED`。

## 待查
- 阿里云（careers.aliyun.com）、淘天（talent.taotian.com）子站是否同一系统（可用 `params.base_url` 复用）。
- 社招站（talent.alibaba.com）。
