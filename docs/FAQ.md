# 常见问题（FAQ）

## 数据相关

**Q：为什么有些公司在日历里，但搜不到岗位？**

日历覆盖 494/500 家（其余 6 家不可合规覆盖），但**能抓到岗位级数据的是 161 家**。
剩下的公司要么是自研招聘站（每家接口不同，需要一家一家适配）、要么是加密平台
（Moka / 飞书 ATSX，页面能看、接口加密）。对这些公司，日历仍会给出
届次、项目类型、方向、城市、投递入口和来源，并在 JD 被挡时附一句
`{公司名}希望你去他们的招聘页逛一逛哦~`。

**Q：数据多久更新一次？**

每天 UTC 19:17（北京时间 03:17）自动采集并发布新 Release；每周一额外打一个归档快照。
Gitee 镜像同日同步，通常比 GitHub 晚 30~60 分钟。

**Q：为什么 `jobradar update` 有时秒回、有时要下载 55MB？**

默认是**增量更新**：先比对 Release 里各文件的 sha256，没变就跳过。
`--force` 可以强制全量重下。

**Q：为什么某些岗位没有 JD 原文？**

数据集只收「能拿到职责/要求原文」的岗位（当前在招岗位里 99.8% 有正文）。
某些大厂的 JD 接口有滑块/签名/登录墙，这类公司只发日历信息，不硬凑正文。

**Q：岗位下架是怎么判定的？**

连续 3 次成功抓取都没再出现才标记为下架。**抓取失败不会导致下架**
（防止一次网络故障把几万个岗位误删）。

**Q：网申时间为什么很多是空的？**

1372 条日历里只有 8 条（0.6%；纯人工条目 1.8%）带完整网申起止——官网大多只写「9 月起」。公众号推文通常有，
但微信对数据中心 IP 会返回验证页，按合规要求不绕过，所以留空而不是编造。

## 使用相关

**Q：`--company 京东` 为什么返回 0 条？明明库里有「京东方」**

因为京东和京东方是两家公司，而这个数据集里目前**没有京东**。
`--company` 的匹配顺序是：公司名全等 → 简称表（`中核`→中国核工业集团）→
**唯一**子串（`阿里`→阿里巴巴）。子串只差一个字的前缀延伸不算命中
（`京东` 只差「方」一个字，属于典型的张冠李戴），这时会返回 0 条并给出提示：

```json
"company_match": {"match": "none", "matched": [], "candidates": ["京东方"]}
```

要看「所有名字里带 X 的公司」，显式加 `--contains`（如 `--company 中国 --contains`）。
命中多家时 `match` 为 `ambiguous`、同样不返回数据——**宁可说没有，也不把别家的岗位当成本家的**。

**Q：结果为空，是不是说明这家公司没在招？**

不是。先看返回里的 `hints` 和 `company_match`：
- `company_match.match = none/ambiguous` → 名字没对上，换完整公司名再查；
- `hints` 里有「`--grad-year` 只命中写了届别的岗位」→ 去掉该过滤再查一次
  （届别/城市/职类是从标题和 JD 原文里按规则提取的，很多岗位两处都不写）；
- 都没有才说明「这批数据里没有它的在招岗位」，而不是「它没在招」。

**Q：需要 API key 吗？**

不需要。数据是公开的 Release 资产，匿名即可下载；查询完全在本地 SQLite 上跑。
设置 `GITHUB_TOKEN` 只是提高 GitHub API 限额（增量更新用一次调用）。

**Q：国内下载慢怎么办？**

```bash
jobradar update --mirror gitee      # 或 export JOBRADAR_MIRROR=gitee
```
Gitee 上的大文件是分片存放的（`.partNN`），客户端会自动下载并合并；失败自动回退 GitHub。
也可以把 `JOBRADAR_MIRROR` 设成任意 GitHub 加速前缀（如 `https://ghproxy.example/`）。

**Q：怎么让 AI agent 用上？**

- Claude Code：把 `skill/jobradar/` 复制到 `~/.claude/skills/jobradar/`
- MCP 客户端（Claude Desktop / Cursor）：命令填 `jobradar-mcp`（stdio）
- 直接当库：`from jobradar.core import queries`

**Q：数据可以商用/二次分发吗？**

代码 MIT。数据是各公司官网的公开岗位信息，请自行评估目标站点的条款；
本项目只做聚合与结构化，不代替官方投递渠道。

## 开发相关

**Q：怎么加一家公司？**

先侦察（`docs/recon/`），再按 `CLAUDE.md` 的适配器流程做；北森/大易/Workday 只需在
`sources/*.yaml` 加一行。详见 [CONTRIBUTING.md](../CONTRIBUTING.md)。

**Q：改了查询逻辑怎么确认没变差？**

`evals/` 里有固定的问题集和期望答案，`uv run python -m pytest` 之外可按
[evals/README.md](../evals/README.md) 跑一遍对照。

**Q：Windows 上要注意什么？**

本项目在 Windows 上跑全量测试（CI 有 windows-latest）。
非中文 locale 的控制台也已处理（CLI 会把输出切到 UTF-8）。

**Q：本地数据坏了（磁盘错误、下载被中断）怎么办？**

`jobradar doctor` 会显示 `jobs_db: false` 并给出建议。直接跑：

```bash
jobradar update --force     # 全量重下，覆盖坏文件
```

`update` 本身也会自愈：增量比对时如果发现本地库打不开（`PRAGMA quick_check` 失败），
会跳过「已是最新」的判断、重新下载那个库。

**Q：Gitee 镜像同步到一半（分片不全）会怎样？**

客户端会先试整文件、再试 `.partNN`；拼接出来的文件要过 gzip + SQLite `quick_check`，
不完整就自动退回下一个镜像（GitHub）。镜像工作流本身也有大小校验，不会把半成品当成功。
