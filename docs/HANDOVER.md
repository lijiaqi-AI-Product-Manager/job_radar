# 交接说明（2026-10-22）

> 写给接手这个仓库的人（以及未来的自己）。当前状态、做过什么、还差什么，一次说清。

## 1. 现在的状态

- ✅ **已推送到 `origin/main`**（2026-10-22；classic PAT，需要 `repo` + `workflow` scope）。
  CI 双平台（ubuntu + windows）在最新提交上全绿。
- 工作树干净，`uv run pytest` 全绿（380+ 用例），`uv run ruff check .` 无错误。
- 数据源 **221 个**：北森新版 200 家、北森旧版 14 家、自研 7 个（腾讯社招/校招、美团、阿里、网易×2）、Workday 1 家（英伟达）。
- 目标覆盖 **99 / 370（27%）**；不可合规覆盖 **10 家**；待侦察 261 家。
- 备份：`pre-takeover` 标签（接手前的主干）、`backups/*.bundle`（全量历史）、`backups/worktree-*.zip`（接手时的工作树）。

> Windows CI 第一次跑就发现一个真 bug：迁移文件的 SHA 受 CRLF 影响。已修
> （`migration_digest()` 归一换行 + `.gitattributes` 统一 LF），现在双平台全绿。

## 2. 这轮做了什么（按主题）

### 修复（Windows 用户原本跑不起来）

- `jobradar update` 在 Windows 必失败：校验 SQLite 的连接没关，`replace()` 报 WinError 32；`_fetch` 的 404 分支也在文件打开时 unlink。
- GBK 控制台遇到零宽空格直接崩：`main()` 先 `_configure_stdio()`，管道统一 UTF-8、终端只降级不崩。
- CI 增加 `windows-latest` 矩阵（这两个 bug 都是"只在 Windows 出现"）。

### 数据质量

- 职类覆盖 50.3% → 58.0%；届别 9.2% → 10.9%（标题没写时取 JD 里唯一明写的「20XX届」）。
- 公司简称可查（`中核`→中国核工业集团 等，`taxonomy/company_aliases.yaml`）。
- 城市覆盖率无法靠规则提升：4.8 万个缺城市岗位里标题能提取的只有约 150 个（北森列表接口 `LocNames` 恒空），已在 `COVERAGE-PLAN.md` 量化说明。

### 新数据源

- 阿里（匿名会话，校招 458 + 日常实习 360 + 研究型实习 257）
- 网易（互联网 81 + 互娱 38）
- 北森租户 11 家：京东方、海信、名创优品、泡泡玛特、长安汽车、潍柴、科大讯飞、中国人保、中海地产、致同、康龙化成（+3,008 岗）
- 汇顶科技（北森旧版，100 岗）
- 英伟达（Workday，中国分面 244 岗）
- 工具：`scripts/probe_beisen_tenants.py`（猜租户名）、`scripts/smoke_sources.py`（上线前冒烟）

### 评测与查询

- 30 题端到端评测（22 ✅ / 4 ⚠️ / 4 ❌）→ `evals/results/2026-10-22-agent-run.md`
- 按评测结果补了 `diff --by category`、`compare --text`、公司简称
- 修了覆盖率报告的误匹配（`京东` 被子串匹配到 `京东方`）

### 合规把关

- SmartRecruiters（博世）：技术上能抓 1,331 个中国岗，但 robots 对非 LinkedInBot 一律 `Disallow: /` → **不实现**，记入 blocked。
- 字节/京东/拼多多/百度/华为：逐家复测，全部是「必然阻断」（405/验证码/no-auth/403），不是限流；快手 robots 禁止。

## 3. 推送方式（已完成一次，留作参考）

2026-10-22 已用 classic PAT 推送成功；CI 双平台全绿。**token 需要两个 scope：`repo` + `workflow`**
——没有 `workflow` 会被 GitHub 拒绝（提交里改了 `.github/workflows/`）。

```powershell
$tok = Get-Content "...\default-workspace\.secrets\github_token.txt" -Raw
$b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$($tok.Trim())"))
cd "...\job_radar\job_radar-main"
..\..\tools\git\cmd\git.exe -c http.extraHeader="AUTHORIZATION: basic $b64" push origin main
```

注意：`record-fixtures` 工作流会在 push 后**自己往 main 推一个提交**（重新录制 fixtures），
所以本地再次 push 前要先 `git pull --rebase`。

## 4. 下一步（按 ROI 排序）

1. **飞书 ATSX**（字节、蔚来、小鹏）：2026-10-22 已在 Actions 抓到真实请求（`recon-probe #53`），
   结论是搜索 POST 需要前端算的 `_signature`，本机按抓包参数复现仍 405 → 按铁律 1 不做
   （`docs/recon/atsx.md`）。除非官方取消签名校验。
2. **Workday 租户发现**：英伟达已接；其他外资需从官网 Careers 链接拿完整 host/tenant/site（不要猜，会 422）。
3. **自研站逐家**：OPPO/荣耀/联想/比亚迪都是自研，需逐个侦察。
4. **北森租户**：命中率已从 6% 掉到 ~3%，还能挖但收益递减。
5. **日历覆盖到 370 家**：这是唯一能对"所有公司"给出"去哪投、什么时候"的兜底。

## 5. 已知边界（别浪费时间重试）

| 来源 | 判定 | 依据 |
|---|---|---|
| 字节 / 蔚来 / 小鹏 | 必然阻断 | 飞书 ATSX：CSRF 可拿，搜索 POST 需要前端 `_signature`（`docs/recon/atsx.md`） |
| 大疆 | 必然阻断 | 其实是 Moka：职位接口返回加密串 + `necromancer` |
| 京东/拼多多 | 必然阻断 | 页面级验证码 |
| 百度/华为 | 必然阻断 | 匿名 no-auth / 403 |
| 快手 | robots 禁止 | `Disallow: /` |
| 博世 | robots 禁止 | SmartRecruiters 对非 LinkedInBot 一律 Disallow |
| 小米 | 无数据可抓 | 只有品牌页，投递走公众号 |
| 高通 | 需浏览器 | 403 `Not authorized for PCSX` |
| AMD | 接口未知 | `/api/apply/v2/jobs` 404 |

## 6. 环境备注

- 本机没有 `git`/`uv`，仓库外装了 portable MinGit（`workspace/tools/git`）和 uv（`workspace/tools/uv`）。
- `.venv` 里有 `sitecustomize.py`（本地沙箱要求：0700 目录不可访问，强制 0777），**不要提交**。
- 沙箱禁止命名管道，Playwright 起不来（`spawn EPERM`）；浏览器相关侦察只能在 Actions 上做。
