# 侦察：Moka（app.mokahr.com 租户站）

- 侦察日期：2026-10-20
- 侦察人：recon-probe 工作流（请求从 GitHub Actions 发出，第 2–4 轮）
- **结论：blocked（职位接口响应被加密，需要逆向解密才能使用）**
- 类型：平台型（多租户）

## 1. 入口与范围
- 租户校招站：`https://app.mokahr.com/campus_apply/{orgId}/{siteId}`，例：`atour/7562`（亚朵）、`bjwgby/29108`
- 页面为前端渲染，HTML 中有 `<input id="init-data" value="{...}">`（含 org 信息与 `aesIv`）

## 2. 合规核查
- robots.txt（app.mokahr.com）：仅 `Disallow: /social-recruitment/lingjuninvest/46355`、`/social-recruitment/shopee/74378`，校招页未被禁止。
- 页面加载网易易盾（`cstaticdun.126.net/load.min.js`），用于投递/验证码环节。
- **职位列表接口的响应是加密的**（见下），属于平台主动设置的技术保护措施。

## 3. 取数接口
- 职位列表：`POST https://app.mokahr.com/api/outer/ats-apply/website/jobs`，body `{"orgId","siteId","limit","offset"}`
- 实测响应：`{"data":"<base64 密文>","necromancer":"<16 位十六进制>"}`
- 前端 `applyWeb-*.js` 中：`decryptResponse(e) = e.necromancer ? JSON.parse(decryptCbc(e.data, e.necromancer)) : e`，AES-CBC，IV 取自页面 `init-data.aesIv`。
- Moka 官方开放 API（`api.mokahr.com/api-platform/v1/jobs/{orgId}`）需要企业客户的凭证，不适用于第三方。

## 结论与理由
解密在技术上并不困难，但这是平台为阻止直接读取而加的混淆层。按 CLAUDE.md 铁律 1（不逆向加密参数、不绕过技术措施），**不实现**。

## 后续可能
- 若某些租户在 Moka 之外另有公开职位页（公司官网自建），按公司单独侦察。
- 若 Moka 未来提供公开数据接口或获得授权，再评估。

## 2026-10-22 复核（第二次抓包，换租户验证）

- 用 RENDERXHR 抓了**吉利**（`app.mokahr.com/campus-recruitment/geely/78436`）：
  `POST /api/outer/ats-apply/website/group-by-job` 的 body 是
  `{"orgId":"geely","siteId":78436,"locale":"zh-CN"}`，响应同样是
  `{"data":"zBpVxS4NuymSc2K7..."}` 加密串；部门树（`departments/flat`）是明文。
- 与大疆（定制域名 `apply.careers.dji.com`）结论一致：**所有租户的职位数据都加密**，
  不是个别配置，解密需要前端密钥 → 按铁律 1 不做。
- **可以用的部分**：Moka 的校招/社招页面本身公开可访问，已作为招聘日历的 `apply_url`
  （吉利、恒瑞、华润置地、新城控股、旷视、新浪、古茗、大众中国、宁德时代、安踏…）。
