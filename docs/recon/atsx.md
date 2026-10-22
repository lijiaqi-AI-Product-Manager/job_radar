# 侦察：飞书 ATSX 招聘门户（字节 / 蔚来 / 小鹏…）

- 侦察日期：2026-10-22（本机 + GitHub Actions 的浏览器抓包）
- 侦察人：DeepSeek agent
- **结论：blocked（需要前端计算的请求签名）**
- 类型：平台（飞书招聘 ATSX，`*.jobs.feishu.cn` 与定制域名）

## 1. 已经确认可用的部分

- 页面与只读 GET 接口匿名可用，例如：
  - `GET /api/v1/common/setting` → 200
  - `GET /api/v1/config/job/filters/6` → 200
  - `GET /api/v1/ip/location` → 200
- CSRF 也能匿名取：`POST /api/v1/csrf/token`，body `{"portal_entrance":1}`
  → 200，返回 token 并下发 `atsx-csrf-token` cookie。

## 2. 卡住的地方：搜索接口要 `_signature`

用 Actions 的 `RENDERXHR` 抓到了真实请求（2026-10-22 recon-probe #53）：

```
POST /api/v1/search/job/posts?keyword=&limit=10&offset=0&…&portal_type=6&…&portal_entrance=1&_signature=***
```

- 浏览器第一次 POST（还没有 CSRF）→ **405**；拿到 CSRF 后的第二次 POST → **200**。
- 本机按同样顺序、同样 body、同样 headers（含 `website-path`、`portal-channel`、
  `portal-platform`、`x-csrf-token`、`x-request-id`）复现：**仍然 405**。
- 唯一对不上的就是 URL 里的 `_signature`：它是前端运行时算出来的，不是服务端下发的 token。
- 同域 GET 全部正常，说明不是 IP/UA/网络问题，而是该 POST 路由要求签名。

按 CLAUDE.md 铁律 1：「需要逆向请求签名/加密参数才能访问的接口：立即停止，不实现」。
**不做**，不尝试复现签名算法。

## 3. 影响的公司

| 公司 | 入口 | 判定 |
|---|---|---|
| 字节跳动 | jobs.bytedance.com | blocked（另有滑块） |
| 蔚来 | nio.jobs.feishu.cn | blocked（`_signature`） |
| 小鹏 | xiaopeng.jobs.feishu.cn | blocked（同一套 ATSX） |
| 大疆 | apply.careers.dji.com | **不是 ATSX，是 Moka**：`/api/outer/ats-apply/website/jobs/v2` 返回 `data` 为加密串 + `necromancer` 字段 → blocked（响应加密，铁律 1） |

## 4. 以后可以再看的前提

- 官方提供无需签名的公开 API / 数据导出；
- 或站点取消该签名校验（届时同样的请求会直接 200）。

在此之前，这四家用 `calendar` 兜底（投递入口 + 时间），不抓岗位明细。
