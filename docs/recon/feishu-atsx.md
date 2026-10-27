# 侦察：飞书招聘 ATSX 门户族（蔚来 / 小鹏 / Momenta / 月之暗面）

- 侦察日期：**2026-10-26 05:58–06:10 CST**（全部为真实请求，时间取自机器时钟）
- 结论：**可用**。同一套匿名 JSON 接口服务多家公司，适配器 `src/jobradar/adapters/feishu_atsx.py`
- 本批新增源：`sources/nio.yaml`、`sources/xpeng.yaml`、`sources/momenta.yaml`
- 同族既有源：`sources/bytedance.yaml`（字节跳动，见 `docs/recon/bytedance.md`，7044 条）

## 0. 一句话结论

字节跳动那套接口**不是它自研的，是飞书招聘（ATSX）的标准门户**。任何
`<tenant>.jobs.feishu.cn` 都吃同一套 `/api/v1/csrf/token` + `/api/v1/search/job/posts`，
换个域名就能抓。2026-10-26 一次性把可匿名访问的门户全找出来并逐个验证。

因此把 `bytedance.py` 重构为 `feishu_atsx.py`（通用）+ `bytedance.py`（薄子类，只固定默认域名），
行为与测试全部保持向后兼容：`tests/adapters/test_bytedance.py` 19 条一条没改仍全绿。

## 1. 门户清单（2026-10-26 逐个实测）

| 门户 | `/campus` | csrf | 列表 | 岗位数 | 招聘项目（job_subject） | 备注 |
|---|---|---|---|---|---|---|
| `jobs.bytedance.com` | 200 | 200 | 200 | **7044** | 2027届校园招聘 / ByteIntern | 见 bytedance.md |
| `nio.jobs.feishu.cn` | 200 | 200 | 200 | **869** | `2027届校园招聘-正式批` | 蔚来，城市全，届次 807/869 |
| `xiaopeng.jobs.feishu.cn` | 200 | 200 | 200 | **629** | 空（靠 `recruit_type.parent`） | 小鹏，`/campus` 是校招站 |
| `momenta.jobs.feishu.cn` | 200 | 200 | 200 | **17** | `Mstar计划` | Momenta，项目名不含届次 |
| `moonshot.jobs.feishu.cn` | 200 | 200 | 200 | **0** | — | 月之暗面，当时门户无开放岗位 |
| `xiaomi.jobs.feishu.cn` 等 | 404 | — | — | — | — | 未开 ATSX 门户 |

探测方法（只读，不做字典爆破，只按**公开品牌名**试，59 个子域）：

```bash
for h in nio xiaopeng momenta moonshot huawei honor mi byd geely zeekr ...; do
  curl -s -o /dev/null -w "$h %{http_code}\n" -A "jobradar/0.1" "https://$h.jobs.feishu.cn/campus"
done
```

`404` 表示该租户不存在；`200` 再验证 csrf + 列表两个接口。**只用品牌名本身**试（`nio`、`xiaopeng`），
不试拼音变体组合——那属于猜域名，且对站点不礼貌。

## 2. 小鹏的坑：官网给的是社招站

`https://www.xiaopeng.com/join.html` 页面里链到的是 `https://xiaopeng.jobs.feishu.cn/index`。
如果直接照抄这个 URL：

- 300 条抽样里 **293 条是社招**（`recruit_type.parent.name="社招"`，`name="全职"`）；
- 只有 1 条实习、0 条校招。

也就是说「跟着官网链接走」会得到一份看起来很大（1588 条）、实际全是社招的数据集，
再被 `recruit_type_of()` 全部过滤掉 —— 白跑一轮还污染审计日志。

**正确入口是 `/campus`**：同一租户下校招站独立存在，`job_subject` 为空，
但 `recruit_type` 的父节点是「校招」，母节点是「正式 / 实习」，629 条全部是校招/实习。

> 教训：ATSX 门户的 `/campus` 与 `/index` 是两套不同的岗位池，**不能按「官网链接」推断**。
> 每接入一个新租户，两个路径都要各打一次列表接口、看 `recruit_type.parent` 的分布。

为此 `recruit_type_of()` 加了一层「向上找父节点」的判定，并且**父级=社招优先于类型名**：

| 输入 | 结果 |
|---|---|
| `job_subject="2027届实习"` | intern |
| `job_subject="2027届校园招聘-正式批"` | campus |
| `job_subject=null, recruit_type={name:"正式", parent:"校招"}` | campus |
| `job_subject=null, recruit_type={name:"全职", parent:"社招"}` | 跳过 |
| `job_subject=null, recruit_type={name:"全职"}`（无父级） | 跳过（不猜） |

## 3. 接口与字段

与字节跳动完全相同（同一套前端），字段口径见 `docs/recon/bytedance.md` §3–§4。差异只有三处：

| 项 | 字节跳动 | 蔚来 | 小鹏 | Momenta |
|---|---|---|---|---|
| `website_path` | `campus` | `campus` | `campus` | `campus` |
| 项目名带届次 | 是 | 是 | **否**（看父级） | 否（`Mstar计划`） |
| 岗位详情 URL | `/campus/position/{id}/detail` | 同 | 同 | 同 |

## 4. 数据落地（2026-10-26 06:07 CST 实测入库）

| 源 | campus | intern | 有城市 | 有届次 | 有发布时间 |
|---|---|---|---|---|---|
| nio | 429 | 440 | **869/869** | 807/869 | 869/869 |
| xpeng | 547 | 82 | **629/629** | 561/629 | 629/629 |
| momenta | 6 | 11 | **17/17** | 7/17 | 17/17 |

- 城市覆盖 **100%**（`city_list` 全量，多城市岗位也全给，如「嵌入式软件工程师 → 北京/苏州/上海」）；
- 届次缺失的是「发布日期早于本年度招季起点 7 月 1 日」的岗位——按 `_enrich` 的契约留空，
  不拿过期 JD 里的旧届次充数（见 bytedance.md §4）；
- JD 覆盖率 **100%**：职责与要求都在列表响应里，不需要逐岗详情页。

## 5. 成本与合规

| 项 | 值 |
|---|---|
| 请求数 | 每租户 1 次 csrf + ⌈n/100⌉ 页；四家合计约 90 次 |
| 限速 | 1 rps/主机，同主机关联串行（`rate_limit_rps: 1`） |
| robots.txt | `*.jobs.feishu.cn/robots.txt` → 404（平台层无站点级规则）；字节跳动自有域名显式 `Allow: /campus` |
| 登录/验证码/签名 | 均无。`_signature` 不校验（篡改后仍 200，实测） |
| 会话 token | 站点匿名下发，只在内存中使用，录制 fixtures 时按 `secret_patterns` 脱敏成 `REDACTED` |
| 触达范围 | 只读列表接口，不提交表单、不请求需登录态的用户中心 |

## 6. 复现

```bash
# 1) 拿 token
curl -s --compressed -X POST 'https://nio.jobs.feishu.cn/api/v1/csrf/token' \
  -H 'content-type: application/json' -H 'accept: application/json' \
  -d '{"portal_entrance":1}' | jq -r .data.token
# 2) 用上一步的 token 取列表（必须带 Accept: application/json，否则 405）
curl -s --compressed -X POST \
  'https://nio.jobs.feishu.cn/api/v1/search/job/posts?portal_type=3&limit=100&offset=0&portal_entrance=1' \
  -H 'content-type: application/json' -H 'accept: application/json' \
  -H "x-csrf-token: $TOKEN" -H 'website-path: campus' \
  -d '{"keyword":"","limit":100,"offset":0,"portal_type":3,"portal_entrance":1}' | jq '.data.count'
```

## 7. 踩坑记录

| 现象 | 根因 | 处理 |
|---|---|---|
| 一个适配器录三家 fixtures，后录的覆盖先录的 | `record_fixtures.py` 固定写 `tests/fixtures/<adapter>/` | 加 `--multi-source`，改写 `tests/fixtures/<adapter>_<source>/`；契约测试按目录逐套跑 |
| 小鹏抓到 1588 条但全是社招 | 官网 `join.html` 链到 `/index` | 改走 `/campus`，并在 `recruit_type_of` 里加父级判定 |
| `publish_date(99999999999999999)` 抛 `ValueError` | `datetime.fromtimestamp` 对越界值抛异常 | 先做范围判断（≤2040-01-01）再转换，异常兜底返回 None |
| 新 `SourceConfig` 报「enabled sources must have a compliance record」 | `Compliance` 是必填 | 每个 `sources/*.yaml` 都写 `compliance` 段；测试里用占位 `Compliance` |
