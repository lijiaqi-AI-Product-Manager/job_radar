# 侦察：中国建筑招聘门户（recruit.cscec.com）

- 侦察日期：2026-10-23
- **结论：blocked（网关返回的 hcm_param 是加密串，属主动技术保护）**
- 类型：企业自研门户（Angular 单页应用）

## 1. 入口

- 校招门户：`https://recruit.cscec.com/recruit`
- 首页 27KB，Angular 应用；JS bundle 合计约 6.7MB
  （`/static/recruit/pc/index-*.js`、`/static/recruit/pc/common-*.js`）

## 2. 已确认

- `/api/...` 是一条 **Open API 网关**，未知路径会返回结构化错误：

  ```json
  {"code": 500, "message": "Unknown Open API:Jobad/GetJobAdPageList"}
  ```

  说明它**不是**北森（北森是 `{"Code":200,...}` 大写 C），而是自研网关，
  但端点名是白名单式的（叫错就报 Unknown Open API）。

- JS 里能看到的接口线索：
  - `/api/language/get_language`
  - `/api/auth/get_auth`、`/api/auth/role_error_msg`
  - `/api/open_api/customer_template_export`
  - 业务侧只有 **前端路由/组件名**：`campus_job`、`campusJobListCtrl`、`zsb-campus-job`、
    `portal-job-list-pc`、`/portal_job_detail`，没有直接的接口名

## 3. 抓包结论（recon #59，2026-10-23）

用 `recon-probe` 工作流的 RENDERXHR 抓一次真实页面（已加入 `docs/recon/probe.txt` 第 46 轮），
从 XHR 里读出岗位列表接口。若能确认是公开 GET/POST JSON，就可以照 `hotjob` 的写法做适配器 ——
中国建筑是 500 家里还没拿到数据的大目标之一。

## 4. 合规

- 只访问公开页面，无登录、无签名；列表接口若需登录态则放弃并标 blocked。
- robots.txt 待查（首页可匿名访问）。
