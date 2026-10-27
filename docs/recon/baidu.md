# 百度 招聘站侦察（talent.baidu.com）

- 侦察时间：2026-10-26 14:1x–14:33 CST
- 结论：**可抓**。单一 JSON 接口，无需登录、无签名、无验证码。
- 覆盖：校招 159 + 实习 536 = **695 条**（社招 1700 条不抓，本数据集只收校招/实习）
- 落地：`sources/baidu.yaml` + `src/jobradar/adapters/baidu.py` + `tests/adapters/test_baidu.py`（11 条）

## 0. 一句话结论

| 问题 | 答案 |
|---|---|
| 要不要登录 | 不要 |
| 有没有签名/token | 没有 |
| 要不要逐岗详情 | **不要**，列表一次给全（含 JD 正文） |
| 最大的坑 | 分页参数**必须在 query**；`recruitType` **必须 query + body 双写**；**必须带 `Referer`** |

## 1. 接口

```
POST https://talent.baidu.com/httservice/getPostListNew?recruitType=GRADUATE&curPage=1&pageSize=10
Content-Type: application/json
Referer: https://talent.baidu.com/jobs/list?recruitType=GRADUATE

{"recruitType":"GRADUATE"}
```

> body 里**只放 `recruitType`**。分页、筛选参数放 body 里全部无效。

响应：

```json
{"status":"ok","data":{"total":"159","list":[{"postId":"545e6823-…","name":"北京-网络研发工程师(J100700)",
 "workPlace":"北京市","postType":"技术","publishDate":"2026-07-08","updateDate":"2026-08-05",
 "projectType":"校招","orgName":"","workContent":"…","serviceCondition":"…"}, …]}}
```

## 2. 五个坑（全是 200 状态码 + 业务错误，或者干脆不报错）

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| 1 | `{"status":"no-auth","message":"illegal-visit"}` | 缺 `Referer` | 带 `Referer: …/jobs/list?recruitType={类型}` |
| 2 | 同上 | 只带 `Origin: https://talent.baidu.com` **无效** | 实测只要 Referer，不要 Origin |
| 3 | `Illegal argument : recruitType` | `recruitType` 只在 query 或只在 body | **两处都写** |
| 4 | `Illegal argument : recruitType` | 用了 `CAMPUS`/`SCHOOL`/小写 | 校招是 **`GRADUATE`** |
| 5 | `Illegal argument : pageSize` | `pageSize` 写了 10 以外的值 | **只能 10** |

### 最坑的那个：分页参数放 body，服务端静默忽略

这是本轮花时间最多、也最容易漏检的一条。

```
# ❌ 错误：分页在 body
{"recruitType":"GRADUATE","pageSize":100,"curPage":16}
→ 200 ok，total=159，返回 10 条 —— 但永远是第 1 页的那 10 条，不报错

# ✅ 正确：分页在 query
?recruitType=GRADUATE&curPage=16&pageSize=10
  body: {"recruitType":"GRADUATE"}
→ 200 ok，返回第 16 页
```

因为它**不报错**，第一版适配器"翻页"了 16 次、每次都拿到同一页，
最终入库 20 条而不是 694 条——日志上看着是"抓取成功"，数据却少了 97%。

**判别方法**（必须做，不能只看 `total`）：

```bash
# 第 1 页和第 2 页的首条 postId 必须不同，否则分页没生效
curl -s -X POST "...getPostListNew?recruitType=GRADUATE&curPage=1&pageSize=10" ... | jq -r '.data.list[0].postId'
curl -s -X POST "...getPostListNew?recruitType=GRADUATE&curPage=2&pageSize=10" ... | jq -r '.data.list[0].postId'
```

适配器里也加了自检：用 `postId` 去重，发现整页都是"见过的"就停下（`test_repeated_page_stops_instead_of_looping` 锁住）。

### 排查过程（留档，供复用）

前前后后试过：

| 尝试 | 结果 |
|---|---|
| `curPage` / `pageNo` / `pageIndex` / `page` / `pageNum` 放 body | 全部返回同一页 |
| 按移动端写法（`POST /httservice/getPostListNew`，不带 query） | `Illegal argument : recruitType` |
| 带会话 Cookie | 无效（本来就无 Cookie） |
| `postType` / `workPlace` 筛选放 body | 也被忽略（total 恒 159） |
| 读 `umi.js` / `Page.*.chunk.js` / 全部异步 chunk | PC 端列表接口不在这些文件里 |
| 读 **移动端** `mobile/main.html` → `common.js` | 找到 `/httservice/getPostListNew` 与 `curPage: i+1` 的拼装 ← **关键** |

突破口是移动到 `talent.baidu.com/mobile/main.html`：PC 端把列表请求藏在运行时动态加载的
`list-fetch` chunk 里，而移动端把接口直接写在 `common.js` 里，并且把 `pageNum` 转成
**`curPage: i+1`** 发出去——于是知道字段名是 `curPage`，再试出它必须放 query。

类型名实测表（`total` 值）：

| 值 | total | 是否有效 |
|---|---|---|
| `GRADUATE` | 159 | ✅ 校招 |
| `INTERN` | 536 | ✅ 实习 |
| `SOCIAL` | 1700 | ✅ 社招（不抓） |
| `CAMPUS` / `SCHOOL` / `TRAINEE` / 小写 | — | ❌ `Illegal argument` |

## 3. 字段映射

| Job 字段 | 来源 | 备注 |
|---|---|---|
| `source_job_id` | `postId` | UUID 形式 |
| `title` | `name` | 自带城市前缀，如 `北京-后端开发工程师(J100737)` |
| `recruit_type` | 请求用的 `recruitType` | 不二次推断 |
| `cities` | `workPlace` | 逗号分隔多城市，如 `北京市,上海市` |
| `publish_at` | `publishDate` | `YYYY-MM-DD`，**直接用**；`updateDate` 是"最近更新"，不当上架日 |
| `grad_year` | `name`/`projectType` | 只认明写的 |
| `batch` | `projectType`/`name` | 仅校招推断 |
| `description` | `workContent` | |
| `requirements` | `serviceCondition` | |
| `url` | 拼接 | `https://talent.baidu.com/jobs/detail/{postId}?recruitType={code}` |
| `department` | `orgName` | **实测多为空串**，就不填 |

实测覆盖率：**`publish_at` 695/695、`cities` 695/695**（100%）。

## 4. 容量与请求量

| 类型 | total | 页数（pageSize=10） |
|---|---|---|
| GRADUATE | 159 | 16 |
| INTERN | 536 | 54 |
| 合计 | **695** | **70 次/天** |

1 req/s，70 次 ≈ 70 秒。

## 5. 复现

```bash
# 校招第 2 页
curl -s -X POST "https://talent.baidu.com/httservice/getPostListNew?recruitType=GRADUATE&curPage=2&pageSize=10" \
  -H "Content-Type: application/json" \
  -H "User-Agent: Mozilla/5.0 (compatible; jobradar-bot/0.1)" \
  -H "Referer: https://talent.baidu.com/jobs/list?recruitType=GRADUATE" \
  -d '{"recruitType":"GRADUATE"}' | head -c 400
```

## 6. 合规

- `talent.baidu.com/robots.txt` 返回 200 但正文是页面 HTML（无 `Disallow` 规则）。
- 无 Cookie、无签名、无验证码；**不伪造浏览器 UA**（用诚实标识 `jobradar-bot/0.1`）。
- `Referer` 是浏览器从列表页跳转时本来就会带的头，不是伪造身份。
- 只读了公开的列表 JSON 与前端静态 JS（后者用于确认参数名，不逆向加密逻辑）。
- 用户协议待人工复核——已标注在 `sources/baidu.yaml` 的 `compliance.terms`。
