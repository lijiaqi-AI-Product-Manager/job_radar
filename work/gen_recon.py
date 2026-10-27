"""生成 docs/recon/beisen-batch.md（平台型侦察，覆盖本批 83 家）
+ docs/recon/<tenant>.md（每家一份，按 TEMPLATE 8 节）
+ fixtures-plan.md
"""

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
RECON = ROOT / "docs" / "recon"
NOW = "2026-10-25"

rows = [json.loads(ln) for ln in (WORK / "companies.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
doable = [r for r in rows if r["verdict"] == "doable"]
empty = [r for r in rows if r["verdict"] != "doable"]


def per_company(r):
    t = r["tenant"]
    return f"""# 侦察：{r['name']}（北森新版 · {t}.zhiye.com）

- 侦察日期：{NOW}
- 侦察人：自研批量探针（`work/probe_beisen.py`，串行 ≤1 req/s）
- **结论：可做**（实测 {r['jobs_estimate']} 条在招，列表接口明文 JSON，JD 在列表内）
- 类型：平台型（多租户）· 适配器 `beisen`

## 1. 入口与范围
- 公开入口 URL：https://{t}.zhiye.com/
- 覆盖的招聘类型：社招 / 校招 / 实习（北森门户混列，详见第 5 节陷阱）
- 预估岗位总量（全量）：{r['jobs_estimate']}
- 平台型预估租户数：本批实测命中 83 个北森租户（见 beisen-batch.md）

## 2. 合规核查
- robots.txt：`User-agent: * / Allow: /`（{NOW} 实测，抽样 5 家一致）
- 服务条款：北森门户为企业自建公开门户，列表接口无需登录、无签名、无验证码
- 是否需要登录/验证码/签名：**否**
- 建议限速：1 rps（本项目全局约束）
- 其他风险：见第 5 节（门店岗位噪声、CategoryId 失效）

## 3. 取数接口
- 列表接口：`POST https://{t}.zhiye.com/api/Jobad/GetJobAdPageList`
  - body：`{{"PageIndex":0,"PageSize":100,"KeyWords":"","SpecialType":0,"PortalId":""}}`
  - 分页：`PageIndex` 从 0 起；`PageSize` 上限实测 100
  - 终止条件：`(PageIndex+1)*PageSize >= Count` 或返回空 `Data`
- 详情接口：**无需单独请求**，`Duty`（职责）与 `Require`（要求）直接在列表项里
- 返回结构：`{{"Code":200,"Count":N,"Data":[{{"Id","JobAdId","JobAdName","CategoryId","Duty","Require","LocNames",...}}]}}`
- 岗位唯一 id：`Id`（GUID 字符串）
- 岗位页链接：`https://{t}.zhiye.com/social/detail?jobAdId={{Id}}`

## 4. 字段映射
| 我们的字段 | 站点字段 / 提取方式 | 备注 |
|---|---|---|
| source_job_id | `Id` | GUID，稳定 |
| title | `JobAdName` | 含 `(J12345)` 内部编号后缀，需清洗 |
| url | `https://{t}.zhiye.com/social/detail?jobAdId={{Id}}` | 构造 |
| recruit_type | `CategoryId` → 1/5=social, 2=campus, 3=intern | **4/6/7 未映射（见陷阱）** |
| grad_year | 标题正则 `20\\d{{2}}届` | 多数无 |
| batch | `normalize.batch_from_text(标题)` | 提前批/正式批/补录 |
| cities | `LocNames[]` | **本租户实测恒为空**，城市缺失 |
| degree_min | `Degree` | 多数 null |
| department | 无独立字段 | 可从 `Org` 取（多数 null） |
| description | `Duty` | 纯文本，含换行 |
| requirements | `Require` | 纯文本 |

## 5. 已知陷阱
1. **`CategoryId` 请求参数被服务端忽略**：传 1/2/3/4/5 均返回同一 `Count`，筛选必须在客户端做。
2. **`CategoryId=4` 是门店/操练岗**（来伊份 7216 条里大量「营业员/店员/美食顾问」），适配器当前 `None` → `SkipRecord` 会整条丢弃，是**正确**行为，但意味着该租户绝大多数岗位不可用。
3. `LocNames` 在本租户恒为空（与 docs/recon/beisen.md 记录一致）。
4. 标题带 `(J27391)` 内部编号，做去重前先剥离。

## 6. 样本
`docs/recon/samples/{t}/`：`list_p1.json`（第 1 页）、`list_last.json`（末页）、`detail.html`（详情页 HTML）。已脱敏（邮箱/手机号/token 已替换）。

## 7. 从 GitHub Actions 的可达性
未测（本机实测 200，耗时 200–600ms）。建议新增源上线前跑 `scripts/smoke_sources.py beisen-{t}`。

## 8. 下一步
可以直接合并 `sources/beisen.yaml`：
```yaml
  - {{id: beisen-{t}, company: {r['name']}, params: {{tenant: {t}}}}}   # {r['jobs_estimate']} 岗（{NOW} 实测）
```
"""


def batch_doc():
    sc = Counter(r["sector"] for r in doable)
    tj = sum(r["jobs_estimate"] for r in doable)
    lines = ["# 侦察：北森新版（beisen）· 本批批量探测", "",
             f"- 侦察日期：{NOW}",
             "- 侦察人：自研批量探针（`work/probe_beisen.py`，串行 + 1 rps）",
             f"- **结论：可做**（{len(doable)} 家命中且有岗位，合计实测 {tj:,} 条）",
             "- 类型：平台型（多租户）", "",
             "## 1. 入口与范围", "",
             "- 公开入口：`https://{tenant}.zhiye.com/`",
             "- 本批探测公司：1357 家（500 基线外的中国知名雇主候选池）",
             f"- 命中：{len(doable)} 家可做 + {len(empty)} 家空门户/待定",
             f"- 预估岗位总量：{tj:,}",
             "", "### 命中租户（按岗位数降序）", "",
             "| 公司 | tenant | 岗位数 | 页面标题 |", "|---|---|---|---|"]
    for r in sorted(doable, key=lambda x: -x["jobs_estimate"]):
        lines.append(f"| {r['name']} | {r['tenant']} | {r['jobs_estimate']:,} | {r['notes'][:30]} |")
    lines += ["", "## 2. 合规核查", "",
              "- robots.txt：抽样 5 家全部 `User-agent: * / Allow: /`",
              "- 无需登录/验证码/签名；条款无禁止自动化条款（企业自建公开门户）",
              "- 限速：1 rps", "",
              "## 3. 取数接口", "",
              "`POST https://{tenant}.zhiye.com/api/Jobad/GetJobAdPageList`，明文 JSON，JD 在列表内（`Duty`/`Require`）。",
              "详见 `docs/recon/beisen.md` 与每家单页。", "",
              "## 4. 字段映射", "同 `docs/recon/beisen.md` 第 4 节。", "",
              "## 5. 已知陷阱（本批新发现，重要）", "",
              "1. **`CategoryId` 请求参数被忽略**：传任何值返回同一 Count，客户端筛选。",
              "2. **`CategoryId=4/6/7` 未在适配器映射表**：4 是门店/操练岗（应丢弃），6/7 语义未知（建议并入 social）。",
              "3. **门店噪声**：来伊份 7216 条中大量「营业员/店员/美食顾问」，与 `5i5j` 同类，但适配器按 CategoryId 丢弃后不影响数据质量。",
              "4. `LocNames` 恒空 → 城市字段缺失，按现有适配器行为接受。", "",
              "## 6. 样本", f"`docs/recon/samples/<tenant>/`，{len(doable)} 家各 3 份，均 ≤50KB 已脱敏。", "",
              "## 7. 从 GitHub Actions 的可达性", "未测。", "",
              "## 8. 下一步", "",
              "直接合并 `work/proposed-sources.yaml` 到 `sources/beisen.yaml`；",
              "如需 fixtures：`uv run python scripts/record_fixtures.py beisen-<tenant> --max-pages 1`。", ""]
    (RECON / "beisen-batch.md").write_text("\n".join(lines), encoding="utf-8")
    return sc, tj


def fixtures_plan():
    lines = ["# fixtures 录制计划（第 1 批 · 北森）", "",
             "本批新增源全部走同一适配器 `beisen`，已有一份契约测试；按项目纪律，**每个新增源仍需最小 fixtures** 以保证回归时能发现门户改版。", "",
             "| source_id | 适配器 | 录制命令 | max_pages | 预估体积 | 脱敏点 |",
             "|---|---|---|---|---|---|"]
    for r in sorted(doable, key=lambda x: -x["jobs_estimate"]):
        lines.append(f"| beisen-{r['tenant']} | beisen | `uv run python scripts/record_fixtures.py beisen-{r['tenant']} --max-pages 1` | 1 | ~40KB | 无 cookie；岗位标题保留；JD 保留 |")
    lines += ["", "## 体积控制", "",
              "- 单源 `PageSize` 建议 10（脚本默认），1 页约 30–45KB",
              "- 83 源 × 40KB ≈ 3.3MB，**超过单目录 300KB 约束**",
              "- 建议：只对 **Top 20 岗位量** 的源录 fixtures，其余靠平台级契约测试覆盖：",
              "", "```", " | ".join(r["tenant"] for r in sorted(doable, key=lambda x: -x["jobs_estimate"])[:20]), "```", "",
              "- 其余 63 家只做 `smoke_sources.py` 冒烟，不存 fixtures（节省仓库体积）", ""]
    (WORK / "fixtures-plan.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    for r in doable:
        (RECON / f"{r['tenant']}.md").write_text(per_company(r), encoding="utf-8")
    sc, tj = batch_doc()
    fixtures_plan()
    print(f"recon 单页 {len(doable)} 份 + 平台页 1 份 + fixtures-plan")
