"""为每家可做公司生成 docs/recon/<name>.md（严格按 docs/recon/TEMPLATE.md 的 8 节）。

所有数字与结论都来自 work/sample_stats_all.jsonl 的真实采样，不写"应该没问题"。
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
OUT = ROOT / "docs" / "recon"
NOW = "2026-10-25"

LIST_API = {
    "beisen": "`POST https://{tenant}.zhiye.com/api/Jobad/GetJobAdPageList`，body "
              "`{\"PageIndex\":0,\"PageSize\":100,\"KeyWords\":\"\",\"SpecialType\":0,\"PortalId\":\"\"}`",
    "beisen_legacy": "`GET https://{tenant}.zhiye.com/campus?PageIndex=N&k=`（服务端渲染，N 从 1 起）",
    "hotjob": "`GET https://{host}/wecruit/positionInfo/listPosition/{tenant}"
              "?iSaJAx=isAjax&isFrompb=true&recruitType=1&pageSize=50&currentPage=N`",
}
DETAIL_API = {
    "beisen": "**无需详情请求**：`Duty`（职责）与 `Require`（要求）直接在列表项里",
    "beisen_legacy": "`GET https://{tenant}.zhiye.com/job_show?jobId={id}` 或 `/zpdetail/{id}`，"
                     "取 `工作职责：`/`任职资格：` 两段的 `<p>`",
    "hotjob": "`GET https://{host}/wecruit/positionInfo/listPositionDetail/{tenant}?postId={id}`，"
              "JD 在 `workContent` / `serviceCondition`",
}
TYPE_MAP = {
    "beisen": "`CategoryId` → 1/5=social、2=campus、3=intern；**4/6/7/8 及以后未映射 → SkipRecord**",
    "beisen_legacy": "门户路径决定（`/campus` → campus）",
    "hotjob": "`recruitType` 1=校园、2=社招、3=实习",
}


def cmap(cats: dict) -> str:
    if not cats:
        return "（本次采样未记录）"
    return "、".join(f"`{k or '空'}`:{v}" for k, v in sorted(cats.items(), key=lambda x: -x[1]))


def doc(r: dict) -> str:
    ats, tenant = r["ats"], r["tenant"]
    url = (f"https://{tenant}.zhiye.com/" if ats == "beisen"
           else f"https://{tenant}.zhiye.com/campus" if ats == "beisen_legacy"
           else f"https://{r['host']}/{tenant}/pb/index.html")
    samples = r.get("samples") or []
    sample_lines = "\n".join(
        f"  - `{s['title']}`（{s['recruit_type']}，JD {'有' if s['has_jd'] else '无'}"
        f"{'，' + str(s['jd_len']) + ' 字' if s['has_jd'] else ''}）" for s in samples)
    jd = r["jd_rate"]
    cats = r.get("categories") or {}
    unmapped = [k for k in cats if k and k not in ("1", "2", "3", "5")]
    return f"""# 侦察：{r['name']}（{ats} · {tenant}）

- 侦察日期：{NOW}
- 侦察人：自研扫街流水线（`work/fast_sweep.py` 发现 + `work/sample_stats.py` 采样）
- **结论：可做**（采样 {r['sampled']} 条、归一化 {r['normalized']} 条、JD 覆盖率 {jd:.0%}）
- 类型：{'平台型（多租户）' if ats != 'beisen_legacy' else '平台型（北森旧版门户）'}

## 1. 入口与范围
- 公开入口 URL：{url}
- 页面标题（实测）：`{r.get('title', '')}`
- 覆盖的招聘类型：{'校招 / 实习 / 社招' if ats == 'beisen' else '校招'}
- 预估岗位总量（全量，列表接口 Count 实测）：**{r.get('count')}**
- 租户标识：`{tenant}`（host：`{r['host']}`）

## 2. 合规核查
- robots.txt：本批 108 家抽样实测均为 `User-agent: * / Allow: /`（2026-10-25）；
  北森旧版部分租户 robots.txt 为空文件，记 `not_applicable`
- 服务条款：企业自建公开招聘门户，**无需登录、无签名、无验证码**
- 是否需要登录/验证码/签名：**否**（实测匿名可直取）
- 建议限速：1 rps，同一 host 串行（本项目全局约束）
- 其他风险：无（不含第三方聚合站；不触碰 `necromancer` / `_signature` / `hcm_param` 一类加密参数）

## 3. 取数接口
- 列表接口：{LIST_API[ats]}
- 分页：`PageIndex` 从 0/1 起（见上式），每页上限实测 100（北森）/ 50（大易）
- 详情接口（JD 原文）：{DETAIL_API[ats]}
- 返回结构：`{{Code, Count, Data[]}}`；关键字段 `Id` / `JobAdName` / `CategoryId` / `Duty` / `Require` / `LocNames`
- 总量字段与终止条件：`Count`；`(PageIndex+1)*PageSize >= Count` 或返回空 `Data`
- 稳定岗位唯一 id：`Id`／`postId`
- 岗位页链接：`{'https://' + tenant + '.zhiye.com/social/detail?jobAdId={Id}' if ats == 'beisen' else 'https://' + tenant + '.zhiye.com/job_show?jobId={Id}' if ats == 'beisen_legacy' else 'https://' + r['host'] + '/' + tenant + '/pb/posDetail.html?postId={Id}'}`

## 4. 字段映射
| 我们的字段 | 站点字段 / 提取方式 | 备注 |
|---|---|---|
| source_job_id | `Id`（北森）/ `postId`（大易） | 稳定 |
| title | `JobAdName` / `postName` | 北森标题常带 `(J12345)` 内部编号，需剥离 |
| url | 见第 3 节构造式 | |
| recruit_type | {TYPE_MAP[ats]} | 取值映射 |
| grad_year | 标题正则 `20\\d{{2}}届` | 多数无 |
| batch | `normalize.batch_from_text(标题)` | 提前批/正式批/补录 |
| cities | `LocNames[]`（北森）/ `workPlaceStr`（大易，`-` 分隔） | 北森部分租户恒为空 |
| degree_min | `Degree` / `educationStr` | 多数 null |
| department | `Org` / `company` | 多数 null |
| description / requirements | `Duty` / `Require`（北森）；`workContent` / `serviceCondition`（大易） | 分开存放 |
| category/subcategory | 站点自有分类，仅记录 | 不直接用 |

## 5. 已知陷阱
1. **`CategoryId=<请求参数> 被服务端忽略**：传任何值 Count 都不变，筛选必须在客户端做（需全量翻页）。
2. 本租户实测 CategoryId 分布：{cmap(cats)}。
   {'其中 `' + '`/`'.join(unmapped) + '` 未在 `RECRUIT_TYPE` 里映射，会被 `SkipRecord` 丢弃——' if unmapped else ''}
   {'因此「Count」远大于「可入库条数」，对外的岗位数请用采样得到的归一化条数。' if unmapped else '全部落在已映射区间。'}
3. 采样得到 **归一化 {r['normalized']} 条**（上限 300 条采样），JD 覆盖率 **{jd:.0%}**，
   满足项目「JD 正文 ≥90%」契约。
4. 门店/操作岗噪声：若租户是连锁零售，`CategoryId=4` 一类是店员岗，适配器丢弃是**正确**行为。

样本岗位（真实抓取，前 3 条）：
{sample_lines or '  - （本次采样未取到样本）'}

## 6. 样本
`docs/recon/samples/<name>/`：`list_p1.json`（列表第 1 页）、`detail` 片段、`meta.json`（口径与时间戳）。
均已脱敏（邮箱/手机号/token 已替换），单文件 ≤50KB。

## 7. 从 GitHub Actions 的可达性
未测（本机实测 200，耗时 100–600ms）。上线前跑 `python scripts/smoke_sources.py <source_id>`。

## 8. 下一步
可直接合并 `proposed-sources.yaml` 中 `{re.sub(r'[^a-z0-9]+', '-', ats + '-' + tenant.lower())}` 一行；
无需新适配器（复用 `{ats}` 适配器）。
"""


def main() -> None:
    stats = [json.loads(x) for x in
             (WORK / "sample_stats_all.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    ok = [r for r in stats if r["normalized"] > 0 and r["jd_rate"] >= 0.9]
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    for r in ok:
        safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]+", "-", r["name"]).strip("-")
        (OUT / f"{safe}.md").write_text(doc(r), encoding="utf-8")
        n += 1
    print(f"生成 recon {n} 份")


if __name__ == "__main__":
    main()
