# 侦察：京东校招（campus.jd.com）

- 首次侦察：2026-10-20（recon-probe 第 16、17、19 轮）——当时结论 **blocked（验证码）**
- **二次侦察：2026-10-26 14:20–14:21 CST——结论改为「可抓」**，7 个项目合计 355 条
- 已落：`sources/jd.yaml` + `src/jobradar/adapters/jd.py`

## 0. 结论为什么变了

首次侦察看到首页加载 `jcap.m.jd.com/home/requireCaptchaPc.js`，判断有滑块验证码，按铁律停止。
这次把 `umi.js`（1.35 MB）拉下来读 `parseParam`，发现 **列表接口本身不触发验证码**——
验证码是投递/投简历环节挂的。并且发现了一个决定性的域名差异：

| 域名（同路径 `/api/wx/position/getProjectList`） | 结果 |
|---|---|
| `zhaopin.jd.com` | `302 → passport.jd.com/new/login.aspx?ReturnUrl=…%2Ferror`，body 空 |
| `campus.jd.com` | `200`，6 KB JSON，无需 Cookie |

同路径、同参数，**只差域名**。如果不知道这条，就会得出「京东全站需登录」的错误结论并一直 block 下去。

## 1. 域名对比的补充观察

- `zhaopin.jd.com` 加 `Referer` 仍 302；`Origin` 无效。
- 访问 `zhaopin.jd.com/web/job/job_list` 页面本身也跳 `passport.jd.com`。
- 但 `zhaopin.jd.com/` 根路径 200（24 KB）→ 不是整站墙，是**招聘路径**上挂了登录。
- `campus.jd.com` 全程不需要任何 Cookie。

> 合规判断：`zhaopin.jd.com` 有登录墙，**遵守，不走那条路**。`campus.jd.com` 无登录、
> 无签名、无验证码，属公开页面。不逆向 `jcap` 的验证/签名流程。

## 2. 接口一：项目字典

```
GET https://campus.jd.com/api/wx/position/getProjectList
Referer: https://campus.jd.com/
```

返回 `body.projectList[].{code, release, groupList[].planMapList[].{id, planName}}`。实测：

| type (`code`) | 含义 | planId | 计划名 | 岗位数 |
|---|---|---|---|---|
| `talent` | TGT 专项 | 47 | TGT-顶尖青年技术天才计划 | 122（含 55） |
| | | 55 | TGT-顶尖青年技术实习生 | ↑ |
| `present` | 应届生 | 56 | JDS-新星计划 | 129 |
| | | 57 | TET-管理培训生 | ↑ |
| | | 58 | 新锐之星 | ↑ |
| `internship` | 实习生 | 45 | JD YOUNG-实习生计划 | 104 |
| | | 51 | 新锐之星实习生 | ↑ |
| | | | **合计** | **355** |

`release: false` 的项目要跳过。适配器**不硬编码 planId**，每次运行从字典接口读——
京东随时会加/停项目。

## 3. 接口二：岗位分页

```
POST https://campus.jd.com/api/wx/position/page?type={talent|present|internship}
Content-Type: application/json
Referer: https://campus.jd.com/

{"pageSize":50,"pageIndex":0,
 "parameter":{"positionName":"","planIdList":[56],
   "jobDirectionCodeList":[],"workCityCodeList":[],"positionDeptList":[]}}
```

响应：`{"success":true,"body":{"totalNumber":85,"pageCount":0,"items":[…]}}`

### 三个参数细节（都是踩过的）

1. **`pageIndex` 从 0 开始**（不是 1）。写 1 会直接漏掉第一页。
2. **`pageCount` 恒为 0**，只有 `totalNumber` 可信。别拿 `pageCount` 判结束。
3. **筛选字段名是 `positionDeptList`**，不是 `deptCodeList`。写错时 Tomcat 直接吐
   `HTTP 400` + HTML 错误页（不是 JSON），极易误判成"接口坏了"。

参数结构是从 `umi.js` 的 `parseParam` 逐字抄的：

```js
var t={pageSize:e.pageSize||o.PAGESIZE,pageIndex:e.pageIndex,
  parameter:{positionName:e.positionName||"",planIdList:e.planIdList||[],
    jobDirectionCodeList:e.jobDirectionCodeList||[],
    workCityCodeList:e.workCityCodeList||[],positionDeptList:e.positionDeptList||[]}};
```

## 4. 岗位记录结构（关键字段）

```json
{"publishId":9107,"reqId":2359,"positionName":"物流运营",
 "publishTime":1784814564000,
 "jobDirection":"采销与物流方向","jobDirectionCode":"01",
 "workContent":"1. 系统参与京东物流…","qualification":"1. 2026年10月1日至2027年9月30日期间毕业…",
 "requirementVoList":[{"workCity":"重庆市-重庆市","positionBg":"京东物流",
                       "workCityCode":"00234","interviewCity":"远程面试"}, …]}
```

| Job 字段 | 来源 | 备注 |
|---|---|---|
| `source_job_id` | `publishId` | 整数 |
| `title` | `positionName` | 标题很短（"物流运营"），方向在 `jobDirection` |
| `recruit_type` | `type` + `planName` | **`talent` 里的 55 是"技术实习生"**，按 planName 是否含"实习"改判 intern |
| `cities` | `requirementVoList[].workCity` | `"省-市"` 格式；一个岗位可能挂 60 个城市 → 取并集 |
| `publish_at` | `publishTime` | **毫秒时间戳**（`1784814564000`），由 `date_only()` 归一 |
| `subcategory` | `jobDirection` | 京东自己的方向名 |
| `description` | `workContent` | |
| `requirements` | `qualification` | |
| `url` | 拼接 | `https://campus.jd.com/#/job/detail/{publishId}` |

## 5. 容量与请求量

1 次字典 + 7 个项目 × 1~3 页 ≈ **20 次/天**，1 req/s，约 20 秒。

## 6. 复现

```bash
# 项目字典
curl -s "https://campus.jd.com/api/wx/position/getProjectList" \
  -H "Referer: https://campus.jd.com/" \
  -H "User-Agent: Mozilla/5.0 (compatible; jobradar-bot/0.1)" | head -c 300

# JDS 新星计划第一页
curl -s -X POST "https://campus.jd.com/api/wx/position/page?type=present" \
  -H "Content-Type: application/json" -H "Referer: https://campus.jd.com/" \
  -H "User-Agent: Mozilla/5.0 (compatible; jobradar-bot/0.1)" \
  -d '{"pageSize":1,"pageIndex":0,"parameter":{"positionName":"","planIdList":[56],"jobDirectionCodeList":[],"workCityCodeList":[],"positionDeptList":[]}}' \
  | head -c 400
```

## 7. 合规

- `campus.jd.com/robots.txt` 无 `Disallow` 规则。
- 不带 Cookie、不带签名；只带同源 `Referer`（浏览器本来就会带）。
- 不伪造浏览器 UA（用诚实爬虫标识 `jobradar-bot/0.1`）。
- `storage.360buyimg.com`（静态资源 CDN）robots 是 `Disallow: /` → **不抓它的任何资源**，
  只读 `campus.jd.com` 的 API 响应。
- `zhaopin.jd.com` 登录墙：遵守。
- 用户协议待人工复核。
