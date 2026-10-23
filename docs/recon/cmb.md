# 侦察：招商银行招聘门户（career.cmbchina.com）

- 侦察日期：2026-10-23（recon #60）
- **结论：待定（接口是明文 JSON，但岗位列表端点还没定位到）**
- 类型：企业自研门户（React SPA）

## 1. 已确认

- robots.txt：`User-agent: *` / `Disallow:`（空 = 全站允许）
- 首页 `https://career.cmbchina.com/index.html` 是 React 单页（入口 566B，main.js 916KB）
- 首页只请求两个「宣传视频」接口，响应是**明文 JSON**：

  ```
  GET /api/socialRecruitmentWebsite/common/getPromotionalVideoUrl
  → {"returnCode":"SUC0000","errorMsg":null,"body":"https://s3gw.cmbimg.cn/..."}
  ```

  命名规律：`/api/{social|?}RecruitmentWebsite/<模块>/<动作>`，返回 `returnCode/errorMsg/body`。

- 前端路由是客户端渲染：`/campus`、`/social`、`/job` 等都返回同一个 566B 外壳。
- main.js 里没有字面量 `/api/...` 路径（懒加载/动态拼接），所以岗位列表端点必须靠**在有岗位的路由上抓 XHR**。

## 2. 下一步（未做）

1. 用 RENDERXHR 抓 `https://career.cmbchina.com/` 的「校园招聘」路由（需先确定真实 path，可从首页导航的 href 读）。
2. 若列表接口是 `GET /api/campusRecruitmentWebsite/job/list?...` 这类明文 JSON，就照 `hotjob` 的写法做适配器；
   若带签名/加密，按铁律标 blocked。

## 3. 合规

- 公开页面、无登录；robots 允许；限速 1 req/s。侦察到此为止，未做任何绕过。