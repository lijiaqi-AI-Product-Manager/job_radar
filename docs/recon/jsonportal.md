# 自建 SPA 招聘门户（jsonportal）侦察记录

> 结论先行：国内一大批集团/央企的「招聘官网」是 Vue/React 打包 + 一个明文 JSON 分页接口。
> 这类站**不需要登录、不需要签名、不需要验证码**，可以从接口直取岗位、城市、截止日、JD。
> 适配器 `jsonportal` 把它们做成配置驱动，一个适配器服务所有同类站点。

## 1. 识别方法（可复现）

1. 打开招聘页 → 看 `<head>` 里是否有 `/assets/index-<hash>.js`（Vue/React 打包特征）；
2. 抓那个 js，搜 `baseURL` / `"/api/` / `"/xxx-api/`，找到接口前缀与路径；
3. 带普通 UA POST 一次空条件请求，能回 `{"code":"000000","data":{...}}` 就是匿名可调；
4. 从门户真实请求里抄分页参数名（Playwright 监听 network），**不要猜**。

## 2. 已收录

| 站点 | 接口 | 分页参数 | 岗位数（2026-10-27） | 备注 |
|---|---|---|---|---|
| 中国电子 `campus.cec.com.cn` | `POST /student-api/api/position/search` | `page` / `size`（1 起） | 校招 788 + 社招 816 | `org` 字段给子公司名（华大九天等）；`closeDate` 是真实截止日 |

### 中国电子的三个坑（都实测过）

1. **默认长 UA 被 403**：本仓库的 `USER_AGENT` 带括号与分号，这个站的 WAF 直接 403；
   换成 `jobradar/0.1` 就 200。这是它的 header 解析缺陷，不是反爬。
   适配器因此支持 `params.user_agent`（只对本源生效，不动全局常量）。
2. **分页参数名传错不报错**：传 `pageNum/pageSize` 永远回第 1 页（10 条），
   看起来像「这站只有 20 个岗」。真实的参数名是 `page/size`，且必须带
   `{"name":"","degree":null,"orgId":[]}` 这几个固定字段。分辨方法：看响应里的
   `data.current` 是不是跟着走。
3. **每页条数被服务端压到 10**：`size=50` 时响应 `size` 仍是 50 但 `records` 只有 10 条，
   所以翻页判定不能按 `page*size >= total` 算，要用响应里的 `current`/`pages`。

## 3. 明确排除的（不写适配器）

| 站点 | 原因 |
|---|---|
| Moka `app.mokahr.com` | 前端签名方案，逆向即破红线（用户已确认不做） |
| 国聘 `*.iguopin.com` | 登录 + 验证码 |
| `cetc.iguopin.com` | 同上（中国电科的校招走国聘） |

## 4. 待办

- 把 `probe_url.py` 里 `ats_hint` 命中的自建站逐个按第 1 节流程过一遍；
  目前 `has_portal` 名单里还有 ~200 个自建站没拆接口。
