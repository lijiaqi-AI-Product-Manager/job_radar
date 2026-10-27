# 变更日志

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号用 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.4.0] - 2026-10-28

### 新增

- **数据源 738 → 1,131，可采公司 706 → 1,099**：北森 870、大易 94、飞书 ATSX 51、图普惠 32、
  旧版北森 28、Workday 25、旧版大易 12，其余 19 个自研站/门户按公司各一条。
  这一轮不是「多写几行 YAML」：每家都跑过探活请求 + 门户 `<title>` 定归属 + 岗位数抽样，
  归属对不上的一律不收——共享门户（`ys.zhiye.com` 这种一个池子挂多个品牌）、多品牌聚合页、
  标题只写「招聘官网」的门户，全部挡在源清单之外。
- **子域枚举 + 门户标题定归属**是这轮唯一跑通的规模化发现路径：公开的子域查询接口一次能给
  几百个真实子域（`zhiye.com` 927 个、`hotjob.cn` 320 个、`jobs.feishu.cn` 103 个），
  再逐个探活、读 `<title>` 反推公司名。反过来，「凭公司名猜拼音租户」这条老路已经走到头：
  40 家 × 5 个候选名 × 3 个平台 = 600 次请求，**0 命中**，因为剩下没建源的公司正是以前猜不中的残差。
- **目标清单 1,117 → 1,655 家，新增 31 个省级行政区**（`targets/top_companies.yaml` 的
  `provinces:` 段，808 家地方重点企业，西藏也补了 14 家：西藏天路、奇正藏药、海思科、藏格矿业…）。
  行业块 1,117 家与省域块 808 家去重后 1,655 家；同一家公司（腾讯=互联网、广东）只算一次，
  覆盖率分母不再重复计数。日历管线 `target_names()` 同时输出行业与省域两组目标，
  省域公司标成 `省域·广东` 这类归属，`jobradar calendar-build` 按新目标生成条目。
- **`scripts/coverage_report.py` 增加分省覆盖率表**：31 个省级行政区逐行给「目标 / 已覆盖 / 覆盖率」，
  零覆盖的省份也列出来（不再只报一个全局数字）。当前 547/1,655（33%），不可合规覆盖 12 家。
- **飞书 ATSX 门户按「有没有校招岗」筛过一遍**：108 个门户逐源跑适配器，51 个有产出
  （合计 8,337 条校招/实习岗，蔚来 863、安克 856、理想 791、小鹏 628、得物 586），
  57 个只放社招（接口能查到岗位，但类型全是社招，适配器按校招口径跳过）。
  这 57 个源已移除，并在 `blocked.jsonl` 记 `reason_code: society_only`——
  留着一个永远吐 0 条的源，覆盖率会虚高，每天还要白跑一次请求。

### 修复

- **紧凑单行 YAML 条目在去重时被整行漏掉**。形如 `- {id: beisen-hisense, company: 海信, params: {...}}`
  的一行式源，旧逻辑按行 `startswith("company:")` 扫，永远扫不到 → 海信、奇瑞、恒生电子被登记成
  「两家公司、两条源」。现在统一走 `jobradar.sources.load_sources` 结构化比对
  （`(adapter, tenant/host)` 与 `(adapter, 公司名去后缀)` 双键），`beisen_host` 与 `beisen` 视为同一适配器。
- **大易门户判定只认 `wecruit`**：伊利 `yili.hotjob.cn` 首页 200、但跳转到 `/wt/yili/...`，
  正文里没有 `wecruit`，被误判成「这家没有门户」。现在接受 `/wt/<corp>/` 形态的跳转。
- **删源之后 `companies.jsonl` 还在说「官方页可抓」**：同一家公司有两套源（永辉=飞书+北森 `yhchaoshi`、
  出门问问/小马智行=飞书单源）时，删掉只放社招的飞书源，公司行仍写 `jd_status: official_page`。
  现在改成 `blocked`，并在 `evidence.grade_why` 注明「门户只有社招，校招源已移除」。
- **仓库根目录 226 个 `tmp_*` 临时脚本与抓取快照污染 lint**（占 816 条告警的绝大多数）。
  已全部清掉，`ruff check .` 恢复全绿；要留的工具脚本统一收进 `work/`，逐个过 lint。

### 其他

- 适配器 23 个在用；测试 **851 条**全绿，`ruff check .` 全绿。
- `companies.jsonl` 1,009 → 1,664 行（新增省域与扩展池目标）；`blocked.jsonl` 835 → 892 行。
- 岗位数、JD 覆盖率、日历条数由每日抓取滚动刷新（Release 与 `calendar.db` 为准），
  仓库里不写死某一轮抓取的快照数字。

## [1.3.0] - 2026-10-27

### 新增

- **数据面大幅扩张**：数据源 **279 → 738**（北森 507、hotjob 82、飞书 ATSX 39、图普惠 32、旧版北森 28、
  Workday 25…共 25 个适配器），公司清单 **866 → 1,009 家**，目标清单 **1,014 → 1,117 家**，
  招聘日历 **1,383 个文件 / 2,078 条条目**，其中 18 家行业龙头补齐了入口与批次。
  新增适配器：Avature、Radancy、飞书 ATSX 门户族、Workday 多租户、图普惠、自助建站、HR360、
  京东校招、百度招聘、字节校园、帆软、深信服、NextData、JSON 门户等（`src/jobradar/adapters/`）。
  单个数据源进库前都跑过字段覆盖率抽查：城市 ≥93%、发布日期 ≥96%、JD 正文 ≥99%。
- **飞书招聘 ATSX 门户族：一次接入四家**（`adapters/feishu_atsx.py` + `sources/{nio,xpeng,momenta}.yaml`）。
  字节跳动那套接口不是它自研的，是**飞书招聘（ATSX）的标准门户**——任何 `<tenant>.jobs.feishu.cn`
  都吃同一套 `/api/v1/csrf/token` + `/api/v1/search/job/posts`。2026-10-26 按公开品牌名逐个实测
  59 个子域（`curl -o /dev/null -w '%{http_code}'`，不做字典爆破），找出 3 家可匿名访问的门户并接入：
  **蔚来 869 条**、**小鹏汽车 629 条**、**Momenta 17 条**（月之暗面门户存在但当时 0 条在招）。
  三家城市覆盖均 **100%**、JD 覆盖 **100%**；在招岗位 104,575 → **106,090**，数据源 370 → 373。
  做法上把 `bytedance.py` 重构成「通用 `feishu_atsx` + 薄子类 `bytedance`」，
  `tests/adapters/test_bytedance.py` 19 条测试**一行未改**仍全绿。
- **多源适配器的 fixtures 按 source 分目录**（`scripts/record_fixtures.py --multi-source`）。
  原来一个适配器只能录一套 fixtures（固定写 `tests/fixtures/<adapter>/`），
  一个适配器服务多家公司时后录的会覆盖先录的、契约测试也回放不到自己的域名。
  现在多源适配器写 `tests/fixtures/<adapter>_<source>/`，契约测试自动发现并对**每个目录各跑一遍**
  契约（含「≥90% 岗位有 JD 正文」「fixtures < 300 KB」两条硬约束）。

### 修复

- **`companies.jsonl` 漏掉了「有日历条目但没有高校简章」的公司**（`work/align_deliverables.py`）。
  收录口径要求「必须有高校就业网命中的简章」，于是**华为、字节跳动、蔚来、小鹏、京东、兴业证券**
  这类只有企业自有招聘站、没有简章转载的公司整批缺席——**866 家里一家头部互联网/车企都没有**。
  日历条目本身就是最硬的证据（带届次、批次、投递入口），不该被「没有简章」一票否决。
  改后 **866 → 1,009 家**，华为/字节跳动/蔚来/小鹏/京东等 143 家头部雇主一次补齐。
  同时把 `sector` 用 `targets/top_companies.yaml` 的人工标注兜底（**228 行空行业 → 0**），
  行业浏览功能才真正可用。
- **`dedupe_auto` 把自动条目的字段一起丢掉了**（`pipeline/calendar.py`）。人工入口条目通常只有
  「投递入口」一项，`cities`/`apply_end`/`grad_year` 全空；同公司的自动条目从结构化职位表里带着
  完整城市与截止日。原实现整条丢弃自动条目，产品里就成了「蔚来：校招｜城市未知｜无网申时间」——
  数据在手却看不见。现在改**字段级合并**：自动条目被丢弃前，先把人工条目**空着**的字段补上
  （人工已写的一律不覆盖），并且把证据来源四件套（`observed_from/to`、`source_*`、`jd_status`）
  一起搬过去，避免「引用入口页却带着职位表的城市」这种错标。
- **`proposed-sources.yaml` 里 597 行写了不存在的适配器**。`adapter:` 直接用了 host 指纹
  （`unknown`/`self_hosted`/`moka`/`beisen`），而这些不是已注册适配器 id，整段贴进 `sources/`
  会立刻报「未知适配器」。现在按注册表归一，判不出的显式标注 `⚠ 需先实现适配器`。
- **`ats_of()` 不认识飞书招聘门户**：`<tenant>.jobs.feishu.cn` 全被判成 `unknown`，
  33 行飞书门户的 `ats` 列是错的。现在识别为 `feishu_atsx`。
- **`publish_date()` 遇到越界时间戳会抛 `ValueError`**（`adapters/feishu_atsx.py`）。
  `datetime.fromtimestamp(99999999999999999/1000)` 直接 `ValueError: year 3170843 is out of range`，
  一条脏数据就能打断整轮抓取。现在先做范围判断（≤2040-01-01）再转换，异常一律兜底返回 `None`。
- **`_d()` 会构造出不存在的日期**（`pipeline/calendar_extract.py`）。只校验「月 1~12、日 1~31」时，
  页面上「2025年11月00日」这种占位写法会被拼成 `2025-11-00` 写进 `calendar/entries/hongqingting.yaml`，
  随后 `ManualEntry` 抛 `day is out of range for month`，**整个 `calendar-build` 失败**——
  一条脏数据让 1,475 条日历全部生成不出来。现在改用真日历校验（2 月 30 日、4 月 31 日、11 月 0 日
  一律判废），并补了 11 条测试（含闰年 2-29 必须通过的反向断言）。
- **自动日历条目的网申时间恒为空**（`pipeline/calendar.py`）。`_auto_entries` 把 `apply_start` /
  `apply_end` 硬编码成 `None`，于是 `job.apply_end` 里几千条真实截止日在自己的产品里一条也看不到。
  现在按与 `export_job_evidence` 完全一致的口径填：截止日取**多数**职位写的那天（不是 `min`——
  实测兴业证券 43 条里有 1 条写 2026-09-30、26 条写 2027-09-29、14 条写 2026-11-02，取 min 会把
  整批截止日提前一个月），起点只在「同批 ≥3 条且 ≥40% 同一天上架」时给，且起点晚于终点一律丢弃。
- **`--has-window` 要求起止两端都有值**（`core/queries.py`）。写着「截止 9-30、开始未公布」的批次
  被判成「没有网申时间」，而它恰恰是用户最需要的（知道什么时候之前必须投）。改为起止任一有值。
- **入口条目完全不含日期**（`work/build_calendar_entries.py`）。交付物里的入口条目 `apply_start` /
  `apply_end` 100% 为空，因为只从入口页正文抽日期，而入口页正文中位数只有 108 字（全是标题）。
  现在接入同仓 `work/ats_evidence.jsonl` 的结构化字段，规则与 pipeline 一致，**361 条条目拿到真实网申窗口**。
- **日历查询把「最紧迫的」埋在 200 条之后**（`core/queries.py`）。`--deadline-before 2026-12-31`
  原来按 `group_name` 字母序排，ABB 排第一、一周内截止的公司沉底；用户在问「最紧迫的是哪个」，
  按字母序回答等于没回答。现在问截止日就按截止日升序（无日期的排最后），`--open-on` 按开放日倒序。
- **`--open-on` 会返回已过期的批次**。`apply_end IS NULL` 的条目被放行是合理的（没写 ≠ 已截止），
  但写了截止日且早于那天的必须挡掉——否则「今天还能投什么」会返回去年的秋招。
- **过期截止日混进交付物**（`work/build_calendar_entries.py`）。鸿星尔克/中国国航两条入口条目带着
  2025-11-15 / 2025-12-31 的旧公告日期，用户点进去只会看到「已截止」。现在入口保留、**日期清空**。
  另拒绝了一条第三方聚合站入口（`campus.niuqizp.com` 牛企直聘，标题里自称转载），红线不能开例外。
- **同一批次在日历里出现两次**（`pipeline/calendar.py` 新增 `dedupe_auto`）。360 集团同时有「校招」
  人工条目和自动条目，214 组同键条目里 11 组截止日互相矛盾——问「什么时候截止」会得到两个答案。
  现在人工条目覆盖的 (集团, 批次, 届次) 不再生成自动条目（**自动条目 1,087 → 748**，混合重复归零），
  但届次不同的都保留：那可能是不同届的两个批次，合并比重复更糟。副作用是两项覆盖率反而上升
  （城市 44.9% → 45.9%、网申时间 20.4% → 23.0%），说明重复条目本来就在稀释数据。

### 变更

- **发布自检的两个日历指标改为双口径并排输出**。`日历有城市` / `日历有网申时间` 的分母排除
  `project_type=社招`（本产品是校园招聘日历，社招板一家几千条岗位既无届次也无批次窗口）
  与「只有入口、不含任何字段」的条目（它的价值是投递入口，本来就取不到日期），
  同时把「全部条目」口径一并打印（城市 43.4%、网申时间 15.6%），避免用口径选择掩盖问题。
- **目标清单 1,014 → 1,117 家**。103 个已经验证官方入口、并且已生成日历条目的集团不在
  `targets/top_companies.yaml` 里，违反「日历里的集团必须是目标」这条不变量；按实测行业标注
  补进对应行业块，实测没有行业标注的归入「扩展池（实测确认）」，不硬猜。

### 收尾修正（本轮）

- **`work/build_calendar.py` 的 `pypinyin` 改成按需导入**。原来顶层 `from pypinyin import ...`，
  而它只是写日历条目时才需要的可选依赖；干净环境里跑 `tests/test_calendar_evidence_index.py`
  会直接 `ModuleNotFoundError`，把整包测试卡在收集阶段。现在 `slug_of()` 里按需导入，
  缺依赖时给出「生成日历条目需要 pypinyin：pip3 install pypinyin」的可执行提示。
- **`adapters/workday.py` 的 `cities_of()` docstring 改成 raw string**，消掉 Python 3.12 的
  `SyntaxWarning: invalid escape sequence '\s'`（`-W error` 的 CI 会因此失败）。
- **`jobradar search --help` 不再抛 traceback**。`--dedupe` 的帮助文本里写了裸的「9.2%」，
  argparse 会对 help 做 `%` 插值 → `ValueError: unsupported format character`。改成 `%%`，
  并新增 `test_every_subcommand_help_renders` 把 12 个子命令的帮助挨个渲染一遍（这类问题
  功能测试发现不了）。
- **入口点测试显式 `stdin=DEVNULL`**。`tests/test_entrypoints.py` / `tests/test_version.py` 里
  4 处 `subprocess.run` 以前继承父进程 stdin，父进程 stdin 若是永不关闭的管道（后台任务、
  部分 CI/沙箱），子进程会挂在读输入上，表现为超时 60s+。
- **`targets/top_companies.yaml` 的 blocked 名单 17 → 12 家**。字节跳动、蔚来、小鹏汽车、
  京东、百度已确认有公开可采入口（飞书 ATSX 匿名接口 / `campus.jd.com` / `talent.baidu.com`），
  继续挂在 blocked 里会让覆盖率报告与日历的 `blocked_reason` 一起说谎。剩余 12 家
  （大疆 Moka 响应加密、拼多多/华为、快手/博世 robots、四家第三方招聘平台、微博登录墙、
  招商蛇口无入口、中国建筑 hcm_param 加密）理由不变。
- **`docs/recon/atsx.md` 补「后记」**：2026-10-22 那次判定 405 是签名缺失，实际是
  `x-csrf-token` 取错了值（用了 URL 编码过的 cookie 而不是响应 body 原值）且缺
  `Accept: application/json`；`_signature` 服务端不校验。旧结论留档，但表格与 ROADMAP /
  FAQ / RELEASE / SKILL 等 8 处「这几家抓不到」的说法一并改掉。

## [1.2.0] - 2026-10-26

数据规模与日历质量的一轮系统性升级。**目标 500 → 1,014 家**，**数据源 279 → 370 个**，
**在招岗位 89k → 97,607 个**，**日历条目 1,330 → 2,425 条**，发布自检 8 项从「7 PASS / 1 FAIL」变成全绿。

### 新增

- **数据源从 279 扩到 370**（`work/add_missing_sources.py`）。此前 `sources/` 只有 272 家公司，
  而侦察阶段实测已打通的租户有 122 家——两边差 91 家「已验证可抓但没建源」的公司，
  数据源覆盖这道闸门因此长期卡在 20% 左右。现在把差集按 (adapter, tenant) 去重后真正写入
  `sources/beisen.yaml`（+75）/`beisen_legacy.yaml`（+8）/`hotjob.yaml`（+8）。
- **结构化职位证据打通进日历**（`export_job_evidence` + `calendar-build --evidence-out`）。
  热招（大易）列表接口每个岗位自带 `workPlaceStr`（「长沙市-长沙县」）和 `endDate`（真实截止日），
  以前这些字段只落到 jobs.db，日历完全用不到。现在 `export_job_evidence()` 把它们按招聘类型
  汇总成每家一条，日历生成时作为**权重最高的一路证据**接入。
  **校园岗城市覆盖率 0.6% → 29.8%**，日历城市条目 547 → 624，届次 616 → 670，
  条目数 1,326 → 1,337。
- **日历「来源」这一列终于有日期**（`work/build_calendar.py`）。原来 1,326 条条目的 `source.date`
  全是 null，用户看到「来源：某校就业网」却不知道是哪天的公告，没法判断时效。
  现在只采信**该批次自己那批公告**的发布日期（`source.date` 覆盖 308 条），
  且绝不拿 `as_of` 或别的批次的日期冒充。
- **`stats` 报字段完整度**：`field_filled` / `field_ratio` / `entries_complete_7of10`。
  以前只报「覆盖率 62%」，看不出是缺截止日还是缺城市，而这两个缺口成因完全不同。
- **`calendar --city / --direction / --deadline-before / --deadline-after`**（上一版已加，
  本版用真实数据验证：`--city 北京` 命中 200+ 条，`--deadline-before` 只在真知道截止日时命中）。

### 修复

- **7 对同一主体在 targets 里重复**（`work/merge_duplicate_targets.py`）：`ABB`/`ABB中国`、
  `宝洁`/`宝洁中国`、`微软`/`微软中国`、`西门子`/`西门子中国`、`SAP`/`SAP中国`、
  `阿斯利康`/`阿斯利康中国`、`民生银行`/`中国民生银行`。两套写法分属不同行业，
  导致行业分布统计失真，日历也被拆成两个 group（用户在「ABB」下只看到半条）。
  合并后 1,021 → 1,014 家，被合并名进 `aliases` 保证 `match_targets` 仍能双向命中。
- **`site_resource.city` 口径**：`campus_city_ratio` 的分母把社招/实习也算进去，稀释了指标；
  现在只算校园岗，并修正 `'null'` 字符串未排除的问题。
- **`source.date` 在此之前全为 null**（见上）。
- **`apply_end`/`publish_at` 全链路落地**：新增 migration `0002_job_window.sql`，
  `Job` 模型、`hotjob` 适配器（含 `3000-01-01` 哨兵值归一）、`ingest` 三处写入同步。

### 已知限制（如实记录，不做粉饰）

- **北森新版门户不返回城市和截止日**：扫完全部 251 个北森租户 × 30 条，
  `LocNames` 恒为 `[]`、`LocID` 恒为 `null`、`EndTime`/`PostDate` 恒为 `0001-01-01`。
  这是平台限制，不是代码缺陷。城市和截止日只能从大易、旧版北森和高校简章拿到。
- **日历 `apply_start` 仍只有 2.6%**：795/1,055 篇高校简章正文写的是流程描述
  （「简历投递→笔试→面试」），没有可抽取的起止日期。留空比编造正确。
- **164 家目标公司仍没有可用招聘入口**：多为 Workday/Taleo/自建站，需逐家人工侦察。

## [1.1.1] - 2026-10-24

**首次发布到 PyPI**：`pip install "jobradar[mcp]"` 即可安装（Trusted Publishing / OIDC，
仓库里不存任何 PyPI token）。数据仍然不走 PyPI，装完跑一次 `jobradar update` 从 Release / Gitee 下载。

- 8 个语言的 README 与 `skill/jobradar/SKILL.md` 的安装说明改为 PyPI 安装，README 加 PyPI 徽章
- `scripts/check_docs_links.py` 规则反转：发布后仍写「尚未发布到 PyPI」会直接失败
  （CHANGELOG 与 `docs/internal/` 的历史记录除外）
- `docs/PUBLISHING.md` 标注已发布并保留后续发版步骤

## [1.1.0] - 2026-10-24

按用户实测反馈（P0/P1/P2）做的一轮体验修缮，外加 8 语言 README、中英演示 GIF 与 social preview。

### 修复（用户直接踩到的）

- **搜不到就引导到日历**：搜「字节跳动/华为/小米/招商银行」不再只回"数据里没有"，结果为空时
  返回 `calendar` 字段（条目数、届次、项目类型、投递入口）+ 提示 `jobradar calendar --group X --table`，
  blocked 的公司带 `{公司名}希望你去他们的招聘页逛一逛哦~`。CLI 与 MCP 都生效。
- **`calendar --table` 真的可读**：以前把 20 个字段堆在一行；现在一条一块，按「集团·届次·项目类型 /
  方向 / 网申 / 城市 / 入口 / 来源 / JD」输出，`window_status=unknown` 会明确写「来源没写起止，不能断定今天还能投」。
- **文档三处不一致**：
  - 版本徽章 1.0.1、正文 1.0.2、代码 1.0.3 → 统一 1.1.0
  - README 说"尚未发布到 PyPI"，Skill 却让 `pip install jobradar` → 全部改成源码安装，并说明 PyPI 未发布
  - README 的日历输出示例与真实输出不一致 → 换成 `--table` 的真实渲染
- **新增 `scripts/check_docs_links.py`**（CI 会跑）：断链、版本号漂移、`pip install jobradar` 未标注
  "尚未发布" 都直接失败——这类问题不该靠人肉发现。

### 新增（压噪声与可观测性）

- **`search --exclude-store`**（MCP `exclude_store`）：排掉门店/店员/导购/收银/咖啡师/店长等零售岗
  （喜茶、星巴克门店帖约 8 千条），默认不过滤。
- **Workday 报错说清楚**：`request_json` 遇到非 JSON 时抛「返回的不是 JSON（HTTP 303, …）。常见原因：
  被限流/反爬拦截…」，以前只有 `Expecting value: line 1 column 1`，排障时完全看不出被挡。
- **MCP 自定义数据目录**：文档补 `JOBRADAR_HOME` 的传法（否则 MCP 去找默认目录报"本地没有数据"）。

### 文档与素材

- **README 8 种语言**：中文为主版本，另有 en / ja / ko / es / fr / de / ru，顶部语言切换，事实口径一致。
- **演示 GIF 两版**（15 秒，8 fps）：`docs/assets/demo-zh.gif`、`demo-en.gif`，由 `scripts/make_assets.py` 生成（Pillow 手绘，可重复产出）。
- **social preview**：`docs/assets/social-preview.png`（1280×640，中文主视觉）。
- **内部过程文档移到 `docs/internal/`**：PROGRESS ×2 / REVIEW-TRIAGE / COVERAGE-PLAN / SOURCE-DISCOVERY，
  面向用户的 README 不再链到过程文档深处。

### 已知未做（下一轮）

- **PyPI 发布**：代码侧就绪，需要维护者在 PyPI 配一次 Trusted Publishing（步骤见 `docs/PUBLISHING.md`）。
- **腾讯社招 38 分钟**：一个源 2,300 次详情请求，1 req/s 下就是 38 分钟。要加速只能做「只对新增/变更
  PostId 拉详情」的增量详情（需要给适配器传已有 id 集合，改的是适配器基类契约，先确认再动）。
- **字段补全**（届次 / 北森城市 / 职类映射）与**日历细化**（把 387 条笼统「校招」拆成提前批/正式批/暑期实习）。

## [1.0.3] - 2026-10-24

接 1.0.2：把评审里剩下的三条工程债清掉，再做一轮扩源尝试（结论写入 `docs/COVERAGE-PLAN.md` §8）。

### 优化

- **每源耗时入库**：`source_run.duration_s` 以前永远是 NULL。crawl 现在按源计时（成功/失败/超预算都记），
  `sources --summary` 给出 `slowest` Top5，慢源和超时源第一次能被看见。
- **`sources` 从 79KB 降到 1.5KB**：新增 `data_status_summary`（计数 + 有问题的源 + slowest）；
  `jobradar sources --summary` 与 MCP `data_status()` 默认走摘要（MCP 传 `verbose=True` 看逐源明细）。
  顺带把 277 源 × 3 条查询（831 条）压成 3 条聚合查询：**120ms → 55ms**。
- **周归档只留 8 周**：`data-archive` 每周一份 ~85MB 快照、此前无上限；daily 归档后按资产名里的日期删 8 周前的。
- `--text` 实测 240–410ms（85MB 主库 + 144MB 原文库），对本地 CLI 够用，**FTS5 暂不做**，实测数字记进评审处置记录。

### 扩源（+2 个源，69 个岗位；下一次 daily 起生效）

- **北森**：322 家未覆盖目标 × 拼音/英文/suffix 变体 = **1,448 次**探测，15 个租户存在，逐个用真实适配器
  核对「页面标题 + 岗位内容 + JD 覆盖率」后：**新增 2 个**
  —— 中国信达（`cinda`，35 岗）、鱼跃医疗（`yuwellhr`，34 岗），两者 JD 正文均 100%。
- **拒掉 13 个**（证据写进 `docs/COVERAGE-PLAN.md` §8）：4 个同名不同公司（`sunny`=天阳地产、
  `ctghr`=易才集团、`haitian`=海天精工、`dongpeng`=东鹏控股）、`5i5j` 门店销售帖含招聘人姓名、
  `minmetalshr` 是笔试题库、`chinaamc` 详情页取不到 JD（按铁律放弃）、`hundsun` 只有 2023 年旧岗，
  其余 5 家门户存在但没挂职位。
- **Workday**：13 个上一轮已知租户逐个校验 China 分面时被限流（CXS 连续返回 303/500，连在用的 nvidia 也 303），
  按合规停止，不加新租户。
- **大易 hotjob**：荣耀 `career.honor.com` 重定向到 `wecruit500.hotjob.cn/SU5fb…`，但列表接口返回
  「官网不存在，无法继续访问」，接不进。
- 结论：平台型租户发现已接近到底，剩下的 337 家都在加密平台（Moka/飞书 ATSX）或自研站，
  下一轮必须逐家写适配器；候选顺序与做法写在 `docs/COVERAGE-PLAN.md` §8。

## [1.0.2] - 2026-10-24

修外部评审（5 份）指出的「会让用户得出错误结论」的缺陷。原则：**宁可 0 条并说明原因，不返回看似正确的错数据**。

### 修复（结果错误类）

- **`--company` 张冠李戴**：`--company 京东` 以前按 `LIKE %京东%` 返回「京东方」的 200+ 行岗位，
  且没有任何提示。现在按「全等 → 简称表 → 唯一子串」解析，只差一个字的前缀延伸不猜；
  命中方式写进 `company_match`（`exact` / `alias` / `contains` / `ambiguous` / `none`），
  没确定时返回 0 条 + 候选，CLI 同时在 stderr 说明原因。新增 `--contains` 显式开启子串搜索。
- **`diff --by category --company X` 静默忽略 `--company`**：以前把全库数字当成该公司的
  （腾讯实测：全库 14,156 → 现在 1,283）。`new_jobs_by_category` 增加 `company` 参数并真的过滤。
- **空结果被「连续拒绝」保护放行**：`MAX_REJECTS` 连续 3 轮后无条件放行，连「返回 0 条」也放行，
  源一旦挂掉/改版就会把整家公司洗空。现在空结果永不自动放行，只能由源配置
  `params.allow_empty: true` 显式接受（`crawl` 已接线）。
- **本地库损坏时裸 traceback**：`doctor` 之外的所有命令都会把 `sqlite3.DatabaseError` 直接抛给用户。
  现在 `local.open_db` 统一转成「本地库损坏（…）→ `jobradar update --force`」，CLI 与 MCP 同一套文案；
  MCP 另加兜底，返回结构化 `error` 而不是崩掉进程。

### 修复（误导类）

- **`calendar --open-on` 把「没写起止」当「确定可投」**：现在这类条目仍会带回（否则等于藏起 99% 的校招），
  但会标 `window_status: unknown`，agent 不能再说成「确定还能投」。
- **空结果没有下一步提示**：`search` 返回空且带过滤条件时新增 `hints`（例如「`--grad-year` 只命中
  写了届别的岗位，去掉它再查一次」；公司名没唯一确定时提示候选），避免 agent 把「字段没写」说成「没岗位」。
- **重复岗位 9.2% 首次公开**：8,115/88,608 是「同公司+同标题+同城市」的多条 ATS req
  （星巴克门店岗一家 2,907 条）。新增 `search --dedupe` 折叠成一条并给出 `variants`
  （星巴克实测 2,907 条 → 22 组），默认计数口径不变，因此发布门槛不受影响。
- **过期判定两套阈值**：`sources` 用 36h、`envelope` 用 48h，同一份数据在两个命令里可能一个
  说新鲜、一个说过期。统一为 48h（连续两个日报周期没成功），并加测试钉住两者一致。

### 修复（打包 / 文档）

- **wheel 里没有简称映射表**：`taxonomy/` 在仓库根、不在 `src/jobradar` 下，pip 装完
  `--company 中核` 直接查不到。改用 hatch `force-include` 打进 `jobradar/_data/`，
  CI 增加「wheel 必须包含 company_aliases.yaml」检查。
- **文档数字全面对齐实测**：门槛 7→8 项；采集时间 UTC 22:19→19:17（北京时间 03:17）；
  测试数 255→491；「约 5% 有网申时间」→ 实测 8/1372（0.6%，纯人工 1.8%）；
  标题「按公司 60.7%」标明分母是 596 个集团而非 500 家；README 不再宣称已发布 PyPI；
  `docs/CALENDAR-FORMAT.md` 的 `janitor/taxonomy/…` 路径修正；新增「重复岗位 9.2%（8,115 条）」
  的已知限制说明。

## [1.0.1] - 2026-10-24

### 推广与工程（2026-10-24）

- **PyPI 发布就绪**：`publish.yml` 用 Trusted Publishing(OIDC) 发版，tag `v*` 自动触发；`docs/PUBLISHING.md` 写明 PyPI 侧一次性配置
- **Gitee 镜像分片**：>12MB 文件切成 `.partNN` 上传（3 路并行），`jobradar update` 整文件 404 时自动按序下载并拼接；`verify_gitee.py` 支持分片求和校验
- **增量更新**：比对 Release asset 的 sha256 digest，未变化则跳过 55MB 下载（二次 update 实测 0 下载）；新增 `--force`
- **CI**：ubuntu(3.12)+windows(3.12) 之外增加 ubuntu(3.11) 兼容性作业；加 concurrency 取消过期运行
- **文档**：CONTRIBUTING.md、SECURITY.md、issue 模板、docs/README.md 索引、README 真实输出示例
- **修复**：非中文 locale 控制台打印中文崩溃（CI windows 红）；`jobradar-mcp --help` 挂在 stdio

### 招聘日历（2026-10-23 起）

- **字段规范固化为长期约定**：`docs/CALENDAR-FORMAT.md` + `CLAUDE.md`（集团/公司/届次/项目类型/方向/网申时间/城市/入口/来源/时间戳；JD 有则挂、被挡只发日历并带提示语）
- **补全通道**：入口页 HTML 抽取（届次）、Playwright 渲染（岗位/城市，含 XHR 嗅探）、数据层投票（届次/方向）、JD 明写工作地点（城市）、备注明写（届次）
- **成果**：≥7/11 字段的条目 25.0% → **38.0%**（187/492）；全部条目 **74.9%**；按公司 **60.7%**（362/596）
- **发布门槛**：新增「日历字段完整度 ≥37%」与「日历按公司完整 ≥60%」两道门槛

### 数据源（2026-10-23）

- 新增 4 家：新华保险（北森旧版 267 岗）、英特尔（Workday 30）、辉瑞（Workday 200）、阿斯利康（Workday 240）
- Workday 适配器支持三处租户差异：`locationMainGroup` 分面、`Location_Country` 精确匹配、`China - 上海 - 上海` 城市写法
- 数据源覆盖 157 → **161/500**

### 修复

- **限额配置静默失效**：`max_pages` 写在源顶层而不是 `params` 里时被 pydantic 忽略，
  限额完全不生效（星巴克一次抓了 18418 岗）。11 个源已修正，加载器现在对未知顶层字段直接报错。
- **加限额反而把源判死**：给源加 `max_pages` 后，骤降保护会拿「历史全量」当基线，
  每轮都判 `dropped 18418 -> 3000` 并 rejected（rejected 不下架，旧岗位永远挂着）。
  新增 `expected_max`：限额能覆盖的最大条数参与基线计算。
- **真实下架导致源被永久封印**：校招季结束后岗位掉 50%+，rejected 不更新基线 →
  永远拒绝。现在连续 3 轮 rejected 后放行一次（`MAX_REJECTS`），空结果保护不变。
- **`python -m jobradar` 不可用**：wheel 装进干净 venv 才暴露（只有 console script）。补 `__main__.py`。

### 优化

- **采集并行单位改为「适配器 + 站点」**：北森几百个租户各在不同子域，串行跑一轮 70+ 分钟；
  现在不同子域并行、同站点仍串行（1 req/s 不变），daily 新增 `--workers`。
- **`jobradar sources --problems`**：只列出未成功/过期的源，排障不用再翻几百行 summary。
- **日历入口分级**：A 官方招聘页 / B 官方公众号 / C 仅官网首页，7 条 C 档已升级为真实招聘页。

### 侦察

- 大易旧版 wt 门户可做（列表自带 JD 正文）；中国建筑网关加密 → blocked；
  招商银行接口明文但仅 19 岗且列表无 JD；北森城市字段三次验证为空（见 docs/recon）。
## [1.0.0] - 2026-10-23（正式版）

第一版「可发布」：五项发布门槛全部达标（`scripts/release_check.py`）。

```
PASS 数据源覆盖    150/500     有岗位数据的公司
PASS 日历覆盖      494/500     抓不到 JD 的公司也能告诉你去哪投
PASS 校园岗城市    29.0%       用户第一诉求是「城市里有什么岗」
PASS JD 正文       100.0%      每条在招岗位都有职责/要求原文
PASS 发布文档      README/CHANGELOG/COMPLIANCE/LICENSE 齐全
```

### 新增

- **262 个数据源 / 100+ 个招聘平台租户**：北森、hotjob（新版 + 老版 wt）、企业自研站点等；
  每个源都有 compliance 记录与 fixtures。
- **hotjob 老版 wt 适配器**：列表 JSON 自带 JD 正文（`workContent`+`serviceCondition`），
  伊利 41 页校招、易方达 15 页社招等一批公司因此可抓。
- **招聘日历达到 494/500**：入口分三档（A 官方招聘专页 / B 官方公众号推文 / C 仅官网首页），
  `docs/CALENDAR.md` 说明如何区分；16 家因合规或技术原因标 `blocked` 并写明原因。
- **公众号来源管线** `scripts/wechat_entries.py`：自动取公众号昵称、发布日期、标题，
  只认「账号名以公司关键词开头」的官方号（踩过「电科」误配「西电科大」的坑）。
- **`doctor` 报告字段覆盖率与 JD 库一致性**，并给一句可执行建议。
- **简称查询**：`--group 中建` 能查到「中国建筑」，`--company 中核` 能查到「中国核工业集团」。
- **镜像半同步检测**：`update` 采样校验 JD 原文库与岗位库是否对得上，不一致自动改走 GitHub。

### 修复

- **daily 的日历步骤一直超时却不报警**：链接探活串行（1000 条 + 国内站点 20s 超时）撞上 30 分钟
  超时，`continue-on-error` 让它静默沿用旧 calendar.db —— 发布里的日历长期停在 270 条。
  改为按主机分桶并行（桶内仍 1 rps），951 条链接 331 秒跑完。
- **Moka 不做**：两次抓包（大疆、吉利）确认职位接口响应加密，按铁律不逆向；只作日历入口。
- 3 个错误域名（bob.com.cn / pzh.com.cn / cmsk.com 均为停放域名）已删除或改正。

### 数据

- 在招岗位 **80,000+**，覆盖 500 家目标公司中的 150 家（有数据）+ 494 家（有日历入口）。
- 校园岗城市覆盖从 18.4% 提升到 29.0%（靠 hotjob 系数据源自带 `workPlace`）。
## [0.9.0] - 2026-10-22（发布候选）

### 新增

- **招聘日历兜底**：抓不到 JD 的公司（字节/京东/拼多多/华为等）用日历记录批次、网申时间、投递入口；
  `jobradar calendar` 支持按集团/公司/项目类型/时间窗查询，blocked 条目附「{公司}希望你去他们的招聘页逛一逛哦~」。
- **500 家目标公司**（由 370 扩表），含智元、宇树、智谱、月之暗面、深度求索、百川、阶跃等 AI 公司。
- **新数据源**：阿里校招、网易（互联网 + 互娱）、英伟达（Workday）、京东方/海信/科大讯飞/中国人保等北森租户。
- `jobradar --version`；`update` 支持并行下载与 `--mirror gitee`。
- Gitee 国内镜像（Release `data-latest`），带匿名下载大小校验。

### 修复

- **Gitee 镜像"假成功"**：大附件删不掉导致新旧两份并存、下载拿到旧数据；改为每次重建 release + 大小校验。
- **日历串公司**：「京东」把「京东方」的 366 个岗位算进自己名下；匹配改为精确优先。
- **提示语病句**：`{岗位名}希望你去…` 改为公司名。
- **Windows**：迁移文件哈希受 CRLF 影响；`update` 的 `WinError 32`；GBK 控制台崩溃。
- **北森城市提取**：标题里的 `济南&青岛`、`苏州｜郑州`、`北京分所` 一个都提不出来；补分隔符与「城市+机构」规则。
- **慢镜像挂死**：`read timeout` 管不住"每秒滴几 KB"，加吞吐/总时长保护后自动回退。
- **sdist 117MB**：`.uv-cache` 被打进包；改为白名单，273KB，并加 CI 体积守卫。

### 数据

- 221 个数据源；最近一次采集 **221/221 成功**，68,170 个在招岗位，JD 正文 68,113（99.9%）。
- 日历覆盖 168/500、数据源覆盖 103/500；10 家公司因 robots/验证码/签名/加密不可合规覆盖，均有侦察文档。

### 已知缺口

- 校园岗城市覆盖低（北森列表接口不返回城市，标题只能补回一部分）。
- 校园岗届次缺失（来源未提供）。
- 字节/京东/拼多多/快手/百度/华为/大疆/蔚来/小鹏/博世 只能日历兜底。
