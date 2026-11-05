# 发布到 PyPI

目标：让用户一条命令装上——`pip install jobsearchradar`（**发布名**），装完命令仍是 `jobradar`。

**已发布的包与当前可用版本**：<https://pypi.org/project/jobsearchradar/>
`jobradar` 这个名字在 PyPI 上与已有的 `job-radar` 过于接近、无法注册，所以 distribution 叫
`jobsearchradar`；import 包名、命令行（`jobradar` / `jobradar-mcp`）都不变。

## 当前渠道状态

2026-11-05已从PyPI官方普通索引无缓存全新安装当前正式版`2.3.3`：14项安装兼容检查、MCP九工具16次调用、15组CLI对照与错误恢复通过。76个运行文件及2份职类/公司映射与v2.3.3逐字节一致；GitHub与PyPI的wheel和源码包实际下载SHA-256一致，三份GitHub发行附件全部通过摘要及大小核对。

该正式安装完成`2026-11-05T08:58:42Z`快照的真实三库更新：12项发布检查无跳过、37条文档示例通过；更新中的旧读者保持可用，释放后重复更新清理闲置旧代。首次GitHub下载HTTP失败后原三库哈希不变，普通重试成功；另一次不可达连接验证确认失败时活动指针与三库SHA-256均保留。快照与来源范围见[覆盖口径](COVERAGE.md)和[空间说明](STORAGE.md)。

以下为此前2.3.2的已完成记录。

2026-11-05已从PyPI官方普通索引无缓存全新安装`2.3.2`：14项安装兼容检查、MCP九工具16次调用、15组CLI对照与错误恢复通过。76个运行文件及2份职类/公司映射与v2.3.2逐字节一致；GitHub与PyPI的wheel和源码包实际下载SHA-256一致，三份GitHub发行附件全部通过摘要及大小核对。无效通用GitHub令牌不影响三库下载；连接失败场景中，活动指针和三库哈希均保留。

2026-11-05新快照`2026-11-05T05:01:25Z`已由正式PyPI 2.3.2完成真实三库更新：12项发布检查无跳过，37条文档示例、MCP九工具16次调用及15组CLI对照通过。真实更新中的旧读者继续使用原代，释放后重复更新清理旧代；连接失败时活动指针与三库SHA-256保持不变。最新来源范围及体积见[覆盖口径](COVERAGE.md)与[空间说明](STORAGE.md)。

2026-11-04已从PyPI官方普通索引无缓存全新安装`2.3.1`：14项安装兼容检查、MCP九工具16次调用、15组CLI结果对照和错误恢复通过。76个包内运行文件及2份职类/公司映射与固定标签逐字节一致；GitHub与PyPI的wheel、源码包SHA-256一致。正式安装完成无损正文流三库下载，再次更新跳过全部未变化文件，默认保留一代快照。

2026-11-03已核实PyPI `2.2.2`发布成功；普通安装索引同步后，本次独立环境无缓存安装、7项CLI兼容检查与MCP九工具16次调用通过，72个包内运行文件与固定标签一致。GitHub与PyPI的wheel和源码包SHA-256一致，五份Release附件逐个下载核验通过。技能包使用固定文件顺序、LF换行与统一ZIP平台标记，Windows导出与Linux发行构建逐字节一致。

2026-11-03已核实PyPI `2.2.1`发布成功；普通安装索引同步后，独立环境无缓存复装、7项CLI检查与MCP九工具16次调用通过。GitHub与PyPI的wheel/源码包摘要一致，7份Release附件逐个下载验证；30秒横竖版短片与海报独立于Python包分发。

历史记录：2026-11-03 已核实 PyPI `2.2.0` 发布成功，并从官方索引在全新环境安装复测。七项安装兼容检查、九工具16次调用与标准错误恢复通过；GitHub/CI/PyPI发行文件逐项SHA-256一致。Trusted Publisher与`PYPI_ENABLED`已生效，不能重复上传已有版本。
当前安装目标与验证状态见 [安装指南](INSTALLATION.md)。发布之后必须从 PyPI 官方索引重新安装并验证，不能用本地源码运行结果替代。

下面的一次性配置用于新仓库或发布关系变更；当前仓库不需要重复配置已正常工作的授权。

## 一次性配置（需要仓库所有者操作，约 5 分钟）

1. 注册/登录 <https://pypi.org>，进入 **Account settings → Publishing → Add a new pending publisher**
2. 按下表填（这是 Trusted Publishing，之后不需要在仓库里存任何 token）：

| 字段 | 值 |
|---|---|
| PyPI Project Name | `jobsearchradar` |
| Owner | `lijiaqi-AI-Product-Manager` |
| Repository name | `job_radar` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

3. 到 GitHub 仓库 **Settings → Environments** 新建两个环境：`pypi`、`testpypi`（可只对 tag 设保护）

配置完成后，工作流 `publish-pypi` 就能用 OIDC 身份直接发布，仓库里不需要任何 PyPI 密钥。

## 发一个版本

```bash
# 1) 改版本号（唯一来源：src/jobradar/__init__.py 的 __version__）
#    pyproject.toml 用 hatch 动态读它，不要在那里写死 version
#    uv lock 由 uv 自动更新
uv lock

# 2) 更新 CHANGELOG（把 Unreleased 段落改成 [x.y.z] - 日期）

# 3) 本地自检
uv run pytest && uv run ruff check src tests scripts
uv run python scripts/check_docs_links.py
uv run python scripts/release_check.py --home ~/.cache/jobradar

# 4) 提交 + 打 tag + 推（tag 会触发 publish-pypi）
git add -A && git commit -m "release: x.y.z"
git tag -a vx.y.z -m "job_radar x.y.z"
git push origin main vx.y.z

# 5) 验证
pip install -U jobsearchradar && jobradar --version
```

## 代码版本与数据快照

`v2.3.3` 是代码版本，源码中的版本号为 `2.3.3`；GitHub 版本说明介绍所包含的能力与有日期的数据规模。推送版本标签会执行仓库已配置的构建与发布流程。

发布构建另外导出 `jobradar-skill` 工作流附件。将其中的 `jobradar-skill.zip` 附到代码 Release，供支持技能的平台导入；它不进入 PyPI 的 `dist/` 上传目录。技能包须包含根目录 `SKILL.md` 与所引用的 `references/` 文件，不含数据库或本地配置。

`data-latest` 和 `data-archive` 专门分发数据，不能删掉或改成代码版本号，否则现有下载与归档入口会失效。PyPI 和 GitHub 使用同一构建版本，但数据仍独立下载。

## 预演（TestPyPI）

GitHub → Actions → **publish-pypi** → Run workflow → `target` 选 `testpypi`。
装预演版本：`pip install -i https://test.pypi.org/simple/ jobsearchradar`。

## 发布了什么

- wheel（`jobsearchradar-<ver>-py3-none-any.whl`）+ sdist
- 只包含 `src/jobradar` + 少量数据文件（sources/taxonomy/targets/calendar/skill/docs），
  **不含**任何 `*.db`、缓存或密钥；CI 会检查产物 < 5MB
- 数据本体不走 PyPI，仍由 `jobradar update` 从 Release / Gitee 下载（PyPI 有单文件大小限制）

## 常见问题

- **`invalid-publisher`**：PyPI 上的 pending publisher 和实际 workflow 文件/环境名对不上，逐字段核对上表
- **`File already exists`**：PyPI 不允许覆盖已发布版本，必须升版本号
- **想撤回**：PyPI 允许 yank（不删），`pip install` 默认会跳过 yanked 版本

独立技能包的导出命令：`python scripts/package_skill.py --output .tmp/skill/jobradar-skill.zip`。常规CI也执行该导出，检查包内相对引用能否独立读取。

## 两个正式渠道保持一致

正式发行使用与源码版本一致的固定`vX.Y.Z`标签。标签推送先通过源码检查、构建和安装兼容检查，再用Trusted Publishing上传PyPI；GitHub代码Release复用同一次构建的wheel、源码包和独立技能包。发布前核对PyPI官方元数据中的文件大小与SHA-256，GitHub附件逐个核验后才公开草稿。已有版本附件不覆盖，重复执行复用相同文件；临时上传响应丢失时先复查再有限重试。

手动预演可选`none`或`testpypi`。手动选择`pypi`时同样必须选择固定版本标签，分支名或版本不匹配会在构建阶段明确失败。需要重试时选择失败作业，已成功发布的PyPI版本不重新上传。该流程完成后仍须从正式PyPI索引安装，验证CLI/MCP与真实快照；元数据摘要一致不能替代安装体验验收。

GitHub代码Release中断时，可运行`code-release-repair`并填写原标签与`publish-pypi`运行编号。流程先核对原构建提交、构建及PyPI发布成功状态，再复用其原始附件，重新核对PyPI摘要；不重传PyPI或重建同版本安装包。草稿按Release编号读取，不依赖仅查询已发布标签的接口。
