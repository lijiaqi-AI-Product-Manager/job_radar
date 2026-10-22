# 路线图

> ✅ 已完成　🟡 进行中　⬜ 未开始　⛔ 不做（附原因）

## 数据源状态（2026-10-22 更新）

| 来源 | 类型 | 状态 | 说明 |
|---|---|---|---|
| 北森新版门户 `*.zhiye.com` | 平台 | ✅ 196 家公司 | 明文 JSON，含 JD 原文；城市字段缺失（标题中明写的城市会提取）；2026-10-22 新增京东方、海信、名创优品、泡泡玛特、长安汽车、潍柴动力、科大讯飞 |
| 腾讯社招 careers.tencent.com | 自研 | ✅ 适配器完成 | 约 2300 岗位 |
| Moka `app.mokahr.com` | 平台 | ⛔ blocked | 职位接口响应 AES 加密，按铁律不逆向（`docs/recon/moka.md`） |
| 北森旧版门户 | 平台 | ✅ 12 家 | 中船、上海航天、成飞所、科伦、中芯国际（变体 B，含 JD）等；航天科工、威衡路径 404 |
| 腾讯校招 join.qq.com | 自研 | ✅ 适配器完成 | 约 1000 岗（应届生+实习），含职责/要求 |
| 美团 zhaopin.meituan.com | 自研 | ✅ 适配器完成 | 校招 196 + 实习 370 + 社招 2609，含职责/要求 |
| 字节 jobs.bytedance.com | 自研 | ⛔ blocked | 飞书 ATSX：列表接口 POST 405，页面未下发 CSRF，且部署滑块验证（`docs/recon/bytedance.md`） |
| 阿里 campus-talent.alibaba.com | 自研 | ✅ 适配器完成 | 匿名会话（页面 token + 会话 cookie，2026-10-21 用户批准）；校招 458 + 日常实习 360 + 研究型实习 257，含职责/要求 |
| 网易 campus.163.com / campus.game.163.com | 自研 | ✅ 适配器完成 | 公开 JSON；网易互联网 81 + 互娱 38，含职责/要求；接口无单岗位链接，url 用项目列表页（`docs/recon/netease.md`） |
| 小米 hr.xiaomi.com | 自研 | ⛔ 不做 | 只有品牌介绍页，投递走公众号，无公开岗位列表（`docs/recon/bigtech.md`） |
| 京东 campus.jd.com | 自研 | ⛔ blocked | 验证码（`docs/recon/jd.md`） |
| gllue、大易 | 平台 | ⬜ | 未侦察 |

## 已完成

- ✅ schema / 迁移守卫；入库（下架判定、失败不下架、骤降熔断）；查询层
- ✅ 适配器框架：模板、草稿流程、fixtures 录制（Actions 上真实录制并提交回分支）与回放、契约测试
- ✅ crawl 编排（同平台串行、跨平台并行）
- ✅ CLI：`update search show diff compare trends sources doctor crawl`
- ✅ MCP server（6 个只读工具）
- ✅ Skill（`skill/jobradar/`）
- ✅ 每日采集发布工作流（`daily.yml`，合并到 main 后生效）+ 每周快照
- ✅ 侦察工具：`recon-probe`、`tenant-verify`、`record-fixtures` 工作流
- ✅ 评测题集 24 题；端到端测试
- ✅ 覆盖率攻坚计划（`docs/COVERAGE-PLAN.md`）：blocked 逐家判定必然/短暂、替代路径矩阵、平台优先路线；2026-10-22 新增京东方、海信（北森租户）

## 下一步

1. ✅ 北森租户：6 批验证，新版 189 家 + 旧版 12 家入库（目标 200+ 已达成）；🟡 持续发现
2. ✅ 合并 PR #1 → 第一次 `daily-crawl`（132 源、全部成功）→ Release `data-latest` 已发布
2a. ✅ 仓库已公开（2026-10-21），可匿名下载 Release；国内网络走 Gitee 镜像
3. 🟡 评测：已用真实数据跑查询（`eval-queries`），据此修复届别/城市/职类/表格输出；完整判分见 evals/
4. ⬜ 北森城市字段（找详情接口）
5. ✅ 北森旧版门户适配器（12 家，含中芯变体 B）
6. 🟡 大厂自研站：✅ 腾讯社招、腾讯校招、美团、阿里（匿名会话）、网易（互联网 + 互娱）；⛔ 字节（飞书 ATSX 405 + 滑块）、小米（无公开岗位列表）、京东、拼多多（验证码）、百度/华为（匿名不可访问）、快手（robots 禁止）（`docs/recon/bigtech.md`）
7. ✅ 职类归一化（`taxonomy/`，覆盖约 45%）
8. ✅ 周报自动生成（每周一）；✅ 健康报告自动开/关 issue；✅ 国内下载镜像（Gitee Release，`mirror.yml`）

## 不会承诺的

- 具体的 star 数、具体的公司数——取决于侦察结果。
- "每家大厂都能抓"——自研站逐家评估，不可做的明确标注不支持。
