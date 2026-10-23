# job_radar — 给 Claude Code 的施工规范

目标：做一份**每日自动更新、带历史、合规**的中国校招/实习/社招岗位开放数据集，并配套 CLI / MCP / Skill 让任何 AI agent 能即时查询。
主要用户是中国校招同龄人。零服务器：采集跑在 GitHub Actions，数据发布到 Release，用户在本地查询。

## 铁律（任何情况下不得违反；与用户指示冲突时先停下来说明）

1. **合规**
   - 只访问公开、无需登录的页面/接口。**遇到验证码、登录墙（需要账号）、需要逆向请求签名/加密参数才能访问的接口：立即停止，不实现，在侦察文档里标记 `blocked` 并向用户报告。** 不使用代理池、不伪造 UA、不绕过任何反爬措施。
   - **匿名会话（2026-10-21 用户批准）**：站点对任何匿名访客下发的会话 cookie、页面内嵌的匿名 token（如 CSRF token、`__token__`），
     可以按浏览器的正常顺序使用——先打开公开页面，再带着站点下发的值请求接口。只在同一次抓取的内存里使用，
     不落盘、不进 fixtures/日志；不伪造、不改写、不靠逆向算法生成。用账号登录拿到的 cookie 不在此列（仍禁止）。
   - 每个源必须有 `compliance` 记录（robots、条款、核查日期），没有就不能 `enabled: true`（模型层已强制）。
   - 限速：默认 ≤1 请求/秒/源；UA 固定为 `adapters/base.py` 的 `USER_AGENT`，不得改。
   - 不持久化 cookie/token/个人信息（上面的匿名会话只在内存里）；fixtures 里也不能有，录制前脱敏。
2. **schema 不可随意改**：已有迁移文件（`src/jobradar/store/migrations/**`）**永远不改**。要改 schema = 新增下一个编号的迁移文件 → 运行 `uv run python scripts/update_schema_lock.py` 登记 → 补测试。`tests/test_schema_guard.py` 会强制检查，**不要为了让测试通过去改 `schema_lock.json` 里已有的哈希**。
3. **测试先行**：先写测试（并确认它失败），再写实现。改动 `pipeline/ingest.py` 或 `core/queries.py` 前先读完对应测试文件——它们记录了业务规则（尤其"抓取失败不得导致岗位下架"）。
4. **每个适配器必须带 fixtures 和专属测试**（见下），否则 `tests/test_adapter_contract.py` 失败。测试不得访问真实网络。
5. **流水线里不调用 LLM、不引入付费服务**。归一化用规则和映射表（`taxonomy/`）。需要 LLM 辅助整理映射表时，作为离线工作产出 PR，由人审核。
6. **浏览器渲染（Playwright）2026-10-21 起经用户批准可用**，但只在公开页面必须执行 JS 才能拿到内容、且找不到公开 JSON 接口时使用。
   固定 UA、限速、robots 规则同样适用；渲染中出现验证码/登录框立即停止并标 `blocked`。优先级仍是：公开 JSON 接口 > 服务端渲染 HTML > 浏览器渲染。
7. 查询逻辑只在 `src/jobradar/core/queries.py` 写一份；CLI、MCP 只调用它，不写 SQL、不写业务逻辑。
8. **JD 正文必须入库**（2026-10-21 起）：每个适配器都要抓职责与要求原文（列表没有就请求详情页/详情接口），
   并能被全文检索（`search --text`）。`tests/test_adapter_contract.py::test_adapter_stores_jd_text` 强制 ≥90% 岗位有正文；
   `crawl-check` 报告里的 `JD-GAP` 行列出真实抓取中正文不足的源。

## 常用命令

```bash
uv sync                                          # 安装依赖
uv run pytest                                    # 全部测试（提交前必须全绿）
uv run ruff check . --fix                        # lint
uv run python scripts/update_schema_lock.py      # 新增迁移后登记
uv run python scripts/record_fixtures.py <source_id> --max-pages 2   # 录制某个源的 fixtures（会发少量真实请求）
```

## 目录

```
sources/            公司清单（yaml）。_ 开头的是示例，不会被加载
taxonomy/           职类/城市/学历/批次的归一化映射表
src/jobradar/
  models.py         Job / SourceConfig（适配器的输出契约）
  sources.py        加载 sources/*.yaml
  adapters/         base.py(基类+注册表) example.py(模板) recording.py(录制/回放) 以及每个真实适配器
  pipeline/ingest.py 抓取结果 -> 入库 + 事件（下架判定、熔断）
  store/            SQLite 迁移
  core/queries.py   对外查询的唯一实现
tests/              fixtures/<adapter_id>/ 与 adapters/test_<adapter_id>.py
docs/recon/         侦察结论（适配器会话的输入）
evals/              评测集：判断改动是否变好的唯一客观依据
```

## 命名规范

| 对象 | 规则 | 例 |
|---|---|---|
| 适配器 id / 模块文件 / fixtures 目录 | 小写蛇形，三者完全一致；草稿期模块名前加 `_` | `beisen` → `adapters/beisen.py`（草稿 `_beisen.py`）→ `tests/fixtures/beisen/` |
| 适配器类 | `<Id>Adapter`，用 `@register` | `MokaAdapter` |
| 专属测试 | `tests/adapters/test_<id>.py` | `test_moka.py` |
| source id | 小写，`-` 分隔；平台型 `<平台>-<租户slug>`，自研站直接用公司拼音/英文 | `moka-acme`、`tencent` |
| 迁移文件 | `NNNN_动词_对象.sql`，编号连续 | `0002_add_job_salary.sql` |
| 时间 | 一律 UTC，`YYYY-MM-DDTHH:MM:SSZ` | |
| recruit_type | 只能是 `campus` / `intern` / `social` | |
| 提交信息 | `adapter(moka): ...` / `core: ...` / `schema: ...` / `docs: ...` | |

## 新增适配器（一个适配器 = 一个会话）

**输入**：`docs/recon/<平台或公司>.md`（侦察结论）。没有侦察文档或结论不是"可做"，**先去做侦察**（用 `/recon`），不要凭猜测写适配器。
**输出**：适配器 + fixtures + 测试 + sources 条目，且 `uv run pytest` 全绿。

流程（`/new-adapter <id>` 会按此执行）：

1. 读侦察文档，确认结论为"可做"、合规信息齐全。
2. 复制 `adapters/example.py` → **`adapters/_<id>.py`（草稿，以 `_` 开头）**，只改站点常量与字段映射，不要改结构。草稿不进注册表、不进契约测试，所以此时 CI 仍是绿的。
3. 在 `sources/` 加条目（平台型：往 `sources/<平台>.yaml` 追加一行；自研站：新建文件），填真实 `compliance`。
4. **录制 fixtures**：本地能访问目标站点就用 `scripts/record_fixtures.py <source_id> --max-pages 1`；不能（例如云端沙箱）就在 `docs/recon/record.txt` 写一行 `<source_id> [页数]` 并推送，`record-fixtures` 工作流会在 Actions 上录制并把 fixtures 提交回分支，随后 `git pull`。检查体积 <300KB、无敏感信息；必要时裁剪。
5. **先写专属测试** `tests/adapters/test_<id>.py`：断言至少一条真实记录的全部关键字段（标题、城市、届别/批次、类型、链接、JD 文本），以及缺字段记录被正确跳过或留空。
6. `git mv adapters/_<id>.py adapters/<id>.py` 转正（此时契约测试开始覆盖它），修实现直到全部测试通过。
7. 全部测试 + ruff 通过后提交。**一个适配器一次提交**，不要夹带无关改动。
8. 若发现需要改 `models.py`/schema/`ingest`：**停下来**，说明原因并请用户确认，不要顺手改。

适配器代码规范：
- 网络请求只能用 `self.request_json` / `self.request_text`；不得自己 sleep/重试；不得读取环境变量里的凭据。
- 必须产出 JD 正文（`description`/`requirements`）；详情请求很多时用 `params.page_size` 让 fixtures 保持小体积。
- `normalize` 里拿不准的字段留 `None`，不要猜；`category/subcategory` 默认留空（归一化阶段统一处理）。
- 标题中**明写**的信息（被分隔符隔开的城市名、届别年份）由 crawl 阶段统一提取（`pipeline/crawl.py::_enrich`，规则在 `normalize.py`），适配器不要各自实现。提取 ≠ 推测：不得根据公司名、部门名等推断城市或届别。
- 平台型适配器（如 Moka、北森）：一个适配器类服务多个租户，租户差异全部放 `source.params`。
- 站点返回字段缺失/类型变化要**显式处理**（抛 `SkipRecord` 或留 `None`），不能让整次抓取崩溃。

## 完成的定义（提交前自查）

- [ ] `uv run pytest` 全绿，`uv run ruff check .` 无错误
- [ ] 新适配器有 fixtures + 专属测试；测试里没有真实网络
- [ ] 没改动任何已有迁移文件；若改了 schema，已新增迁移并登记
- [ ] 新增源都有真实的 `compliance`
- [ ] 改动了查询层/入库层 → 对应测试已先于实现更新
- [ ] 改动影响 agent 的回答（字段、行为）→ 跑一遍 `evals/`（见 evals/README.md），在提交说明里写结果

## 遇到这些情况，停下来问用户

- 需要绕过验证码/登录/签名；robots 或条款明确禁止自动化访问
- 需要改 schema、`models.py`、`ingest.py` 的规则（阈值、下架判定）
- 想引入新依赖（Playwright 已批准）、付费服务
- 某源的岗位数量/结构与侦察文档严重不符

## 招聘日历字段（长期要求，2026-10-23 用户确认；详见 docs/CALENDAR-FORMAT.md）

一条日历 = 一个「集团 × 届次 × 项目类型」的招聘活动，必须包含：
集团、具体公司/产品、届次、项目类型（寒假/暑假/实习/春招/秋招/提前批/校园大使/校招/社招/兼职/线上，**分条目**）、
方向（track 级，方向+具体岗位名，可多条）、网申时间、城市、投递入口、来源（公众号要带日期）、数据时间戳。

JD 不要求 100%：
- 有公开 JD 必须挂（数据层关联或官方 JD 页）
- JD 被挡（验证码/登录墙）只发日历信息，末尾加 `{公司名}希望你去他们的招聘页逛一逛哦~`

**500+ 家公司全部要有日历条目，一家都不能少**；字段拿不到就留空，不编造；
已知不可做的写进 `targets/top_companies.yaml` 的 `blocked` 并说明原因。
