# 侦察：Workday 租户（外资公司在华招聘）

- 侦察日期：2026-10-22
- 侦察人：本机探针（本机直连，固定 UA，≤1 req/s）
- **结论：可做（平台型适配器 `workday`）**
- 类型：平台（Workday CXS 公开 JSON）

## 1. 为什么值得做

外资在华目标（微软、苹果、亚马逊、英特尔、英伟达、高通、AMD、西门子、博世、施耐德、ABB、
特斯拉、宝马、奔驰、大众、索尼、松下）里，相当一部分用 Workday。一套适配器可复用。

## 2. 合规核查（以 NVIDIA 为例）

- `robots.txt`：`User-agent: * / Allow: /NVIDIAExternalCareerSite/`，另有几条 Disallow
  （`/talentcommunity/`、`/refreshFacet/` 等）；**没有禁止 `/wday/`**，接口按默认允许访问。
- 接口无需登录、无签名、无验证码；只读。
- 用户协议：待人工复核。
- 限速：1 req/s；中国岗位约 244 个 → 约 13 页列表 + 244 次详情 ≈ 260 次/天。

## 3. 取数接口

- 列表：`POST https://{host}/wday/cxs/{tenant}/{site}/jobs`
  body：`{"appliedFacets": {...}, "limit": 20, "offset": 0, "searchText": ""}`
  → `{"total": 244, "jobPostings": [{title, externalPath, locationsText, postedOn, bulletFields}], "facets": [...]}`
- 详情：`GET https://{host}/wday/cxs/{tenant}/{site}{externalPath}`
  → `{"jobPostingInfo": {title, jobDescription(HTML), location, externalUrl, jobPostingId, jobReqId, ...}}`
- **中国分面过滤**：`facets` 里 `locationMainGroup → locations` 的 value descriptor 形如
  `"China, Shanghai"`；取 `startswith("China, ")` 的 id 列表，放进
  `appliedFacets={"locations": ids}` 再查（NVIDIA 实测 2000 → 244）。
  找不到国家分面时**直接失败**，不抓全球岗位。

## 4. 字段映射

| 我们的字段 | 站点字段 |
|---|---|
| source_job_id | jobPostingId（缺省 jobReqId / externalPath 末段） |
| title | title |
| url | externalUrl |
| cities | location（"China, Shanghai" → 上海；英文城市名映射见适配器） |
| description | jobDescription（HTML 转纯文本） |
| recruit_type | source.params / recruit_types（外资站基本是社招） |

## 5. 已验证租户

| 公司 | host / tenant / site | 中国岗位 |
|---|---|---|
| 英伟达 | nvidia.wd5.myworkdayjobs.com / nvidia / NVIDIAExternalCareerSite | 244 |
| 英特尔 | intel.wd1.myworkdayjobs.com / intel / External | 无 China 分面（未接入） |
| 高通 / AMD | qualcomm.wd5 / amd.wd1 | 422，tenant/site 名不对（各自用 Eightfold 等，未接入） |

## 6. 下一步

- 用同样的方法找其他外资的在华 Workday 站点（host/tenant/site 可从官网「Careers」跳转拿到）。
- **不要猜 host/tenant/site**：2026-10-22 试了特斯拉/宝马/奔驰/大众/索尼/施耐德的
  `*.wdN.myworkdayjobs.com + External` 组合，全部返回 **422**（Workday 的 wdN 编号与
  site 名各家不同）。可靠做法是从官网 Careers 链接或搜索引擎拿到完整 URL，再用
  `scripts` 里的方式验证。
- 若某租户有多个 China 站点（北京/上海/深圳），分面 id 会全部取到，无需逐个配。
