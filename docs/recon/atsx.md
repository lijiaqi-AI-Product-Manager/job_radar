# 侦察：飞书 ATSX 招聘门户（字节 / 蔚来 / 小鹏…）

- 侦察日期：2026-10-22（本机 + GitHub Actions 的浏览器抓包）
- 侦察人：本机探针
- **结论（2026-10-22）：blocked（当时判断需要前端计算的请求签名）——已于 2026-10-26 推翻**，见文末「后记」与 `docs/recon/feishu-atsx.md`
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
| 字节跳动 | jobs.bytedance.com | ~~blocked~~ → **已接入**（`adapters/feishu_atsx.py`） |
| 蔚来 | nio.jobs.feishu.cn | ~~blocked~~ → **已接入**（同一适配器） |
| 小鹏 | xiaopeng.jobs.feishu.cn | ~~blocked~~ → **已接入**（同一适配器） |
| 大疆 | apply.careers.dji.com | **不是 ATSX，是 Moka**：`/api/outer/ats-apply/website/jobs/v2` 返回 `data` 为加密串 + `necromancer` 字段 → blocked（响应加密，铁律 1） |

## 4. 以后可以再看的前提

- 官方提供无需签名的公开 API / 数据导出；
- 或站点取消该签名校验（届时同样的请求会直接 200）。

其中大疆仍用 `calendar` 兜底（投递入口 + 时间），不抓岗位明细。

## 5. 后记（2026-10-26）：405 与 `_signature` 无关，三家公司已接入

按上面的结论停了两天后，重新抓了一次**浏览器自己的请求**，发现上一版复现实验里漏了两个头，
而这两件事都不是签名：

1. `x-csrf-token` 必须是 `POST /api/v1/csrf/token` **响应 body 里的原值**，
   不是 cookie `atsx-csrf-token` 那个（cookie 是 URL 编码过的，直接用就会 405）；
2. 必须带 `Accept: application/json`。缺它 → 405（不是 401/403，非常容易误判成"接口不存在"）。

补上这两条后 `POST /api/v1/search/job/posts` 稳定 200。至于 `_signature`：把它改成任意值
（甚至删掉）依然是 200——**服务端不校验**，所以从头到尾都不涉及逆向签名，也不违反铁律 1。

结局：字节跳动 `jobs.bytedance.com`、蔚来 `nio.jobs.feishu.cn`、小鹏 `xiaopeng.jobs.feishu.cn`
（还有 Momenta、月之暗面）已经用同一套匿名接口接入，见 `docs/recon/feishu-atsx.md`。
大疆仍是 Moka 响应加密，维持 blocked。
