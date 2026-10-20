# 路线图

> ✅ 已完成　🟡 进行中　⬜ 未开始　⛔ 不做（附原因）

## 数据源状态（2026-10-20 侦察结果）

| 来源 | 类型 | 状态 | 说明 |
|---|---|---|---|
| 北森新版门户 `*.zhiye.com` | 平台 | ✅ 155 家公司 | 明文 JSON，含 JD 原文；城市字段缺失（标题中明写的城市会提取） |
| 腾讯社招 careers.tencent.com | 自研 | ✅ 适配器完成 | 约 2300 岗位 |
| Moka `app.mokahr.com` | 平台 | ⛔ blocked | 职位接口响应 AES 加密，按铁律不逆向（`docs/recon/moka.md`） |
| 北森旧版门户 | 平台 | ✅ 10 家 | 中船、上海航天、成飞所、科伦等；中芯（变体 B，标题截断需详情页）待做；航天科工、威衡路径 404 |
| 腾讯校招 join.qq.com | 自研 | ✅ 适配器完成 | 约 1000 岗（应届生+实习），含职责/要求 |
| 美团 zhaopin.meituan.com | 自研 | ✅ 适配器完成 | 校招 196 + 实习 370 + 社招 2609，含职责/要求 |
| 字节 jobs.bytedance.com | 自研 | ⬜ | 列表接口 405，需进一步侦察（不得绕过 token/签名） |
| 阿里 campus-talent.alibaba.com | 自研 | ⛔ blocked | 接口需页面下发的 token + 会话 cookie（`docs/recon/alibaba.md`） |
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

## 下一步

1. ✅ 北森租户：5 批验证，155 家入库；🟡 继续发现更多租户（目标 200+）
2. ✅ 合并 PR #1 → 第一次 `daily-crawl`（132 源、全部成功）→ Release `data-latest` 已发布
2a. ⚠️ **仓库目前为私有**：公开前用户无法匿名下载数据（`update` 已支持 `GITHUB_TOKEN`）
3. 🟡 评测：已用真实数据跑查询（`eval-queries`），据此修复届别/城市/职类/表格输出；完整判分见 evals/
4. ⬜ 北森城市字段（找详情接口）
5. ✅ 北森旧版门户适配器（10 家）；⬜ 中芯（变体 B）
6. 🟡 大厂自研站：✅ 腾讯校招、美团；⛔ 字节（验证码）、阿里（token）、京东（验证码）、拼多多（验证码）、百度/华为（匿名不可访问）、快手（robots 禁止）；⬜ 网易、小米（`docs/recon/bigtech.md`）
7. ✅ 职类归一化（`taxonomy/`，覆盖约 45%）
8. ✅ 周报自动生成（每周一）；✅ 健康报告自动开/关 issue；⬜ 国内下载镜像

## 不会承诺的

- 具体的 star 数、具体的公司数——取决于侦察结果。
- "每家大厂都能抓"——自研站逐家评估，不可做的明确标注不支持。
