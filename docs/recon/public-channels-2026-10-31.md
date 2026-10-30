# 公开补源渠道复核（2026-10-30 / 31，北京时间）

这份记录说明实测路径与内容边界，不把 HTTP 200 当作转载许可，也不把入口线索算成覆盖。

## 牛客：可做最小事实与官方入口发现，尚未完成全量接入

- [robots.txt](https://www.nowcoder.com/robots.txt)：实测 200，禁止 `/search`、`/nccommon`、`/ab/ab-test-flow`，未禁止公开招聘日程路径。
- [公开日程](https://www.nowcoder.com/jobs/school/schedule?type=0)：无需登录，直接解析 SSR `window.__INITIAL_STATE__` JSON；不执行脚本、不调用私有接口。
- [免责声明](https://www.nowcoder.com/html/disclaimer)：社区用户原创内容转载需书面授权。当前只提取公司名、明示时间、城市与原始入口，不复制 JD、社区正文、评价或招聘者个人资料。
- `scripts/discover_nowcoder.py` 有真实最小样本回放和在线首屏验证；输出 `source_kind: aggregator`、`ownership_verified: false`，默认写 `.tmp/`。离线回放不伪造在线核查时间。
- 首屏实测 20 条，载荷声明 1,134 页；`page=2/3` 仍返回第一页，未实现或声称全量分页。
- robots 声明的 [岗位 sitemap](https://www.nowcoder.com/sitemap/nowpick/sitemap.xml) 指向 [链接表](https://www.nowcoder.com/nowpick/sitemap1.xml)，实测 2,239 条。后续在允许路径继续核验，链接数不等于公司覆盖数。
- `static.nowcoder.com` 的 robots 禁止抓取。侦察曾误取一次脚本，已删除并弃用所有衍生信息；后续只依赖允许的 HTML/JSON 载荷及 sitemap，不访问或使用禁止路径。

## 实习僧与高校就业网：保留聚合分类，逐源核验归属

`shixiseng`、`campus`、`yunjiuye` 均显式标 `source_kind: aggregator`。关键词命中与公司归属分别核验；不能把「圣邦集团」当「圣邦股份」，把「通威股份」当「通威集团」。

本轮新增两个高校源，均有明示当前截止日与可读正文：

| 目标 / 法律实体 | 核查 UTC | 真实岗位 / 日期 |
|---|---|---|
| 中天钢铁 / 中天钢铁集团有限公司 | 2026-10-30T15:57:09Z | [电气技术员 2266135](https://lnkjdx.bysjy.com.cn/detail/job?id=2266135)；发布 2026-09-28，截止 2026-12-17 |
| 神威药业 / 神威药业集团有限公司 | 2026-10-30T15:57:15Z | [信息管理 3270319](https://hbgc.bysjy.com.cn/detail/job?id=3270319)；发布 2026-10-15，截止 2027-10-15 |

见 [源配置](../../sources/yunjiuye_supplement.yaml) 与 [最小样本](../../targets/source_checks.yaml)。这些是定向关键词补充，未声称公司全部在招岗位。

这些学校的 robots 返回 HTTP 403；按 [RFC 9309 §2.3.1.3](https://www.rfc-editor.org/rfc/rfc9309.html#section-2.3.1.3) 属于 unavailable，没有可用规则，不能写成 `Allow: /`。岗位请求本身须成功且无挑战；条款、登录和验证码仍需停止。网络失败、5xx、429 或挑战页不按 unavailable 放行。

其余 19 个历史高校候选未在本次选择的站点/关键词取得合格当前样本，未新增；这不代表雇主其他地方没有招聘。

## 应届生：当前不启用

- [用户协议](https://www.yingjiesheng.com/about/service/user-agreement202108.pdf) 第五节要求复制、转载或抓取相关内容前取得书面许可，当前没有许可。
- `q.yingjiesheng.com` 实测返回阿里云 WAF 挑战，立即停止；未执行挑战脚本或生成凭据。
- 移动版或其他页面可访问，不会消除上述限制。运行时阻止该域及子域采集。后续从雇主/学校原始发布补源，或取得许可后复核。

## 官方入口核验与排除

通威门户标题为「通威股份有限公司」，抽样五岗均有正文，见 [样本](../../targets/source_checks.yaml)。配置由「通威」改成「通威股份」，未扩展到母集团或增加覆盖总数。

历史入口里多个链接实际属于别家公司：采埃孚指到长安福特，哪吒指到长安汽车，浦发/广银指到中国人寿，罗兰贝格指到容百，亿航指到亿联，三全指到三元，太平鸟指到中国太平。均未据此新增。中国巨石、长城资产、建信基金、中国航油、洋河与三个大易候选本次未取得合格当前样本，不宣称接通。

中国电子旧配置覆盖固定 UA。已移除；2026-10-30T16:32:57Z 用固定 UA 复核，robots 无法核实，在请求岗位前停止，暂时停用。旧 fixtures 仅作字段映射回归，不能证明当前可采。
