# 安装与版本兼容

需要 Python 3.11+。在实际运行 CLI 或 MCP 的 Python 环境中升级：

```bash
pip install --upgrade "jobsearchradar[mcp]==2.1.4"
jobradar --version
jobradar search --help
jobradar calendar --help
```

仅使用 CLI 可以安装 `jobsearchradar==2.1.4`。包名是 `jobsearchradar`，命令仍为 `jobradar` / `jobradar-mcp`。

2026-11-03已从正式PyPI索引全新安装 `2.1.4`：7项CLI兼容检查、MCP九工具、11次CLI结果对照及标准错误恢复通过。72个包内运行文件与固定标签逐字节一致，简称映射相同；GitHub、CI与PyPI的wheel和源码包摘要一致。

首次安装曾因新版本索引尚未可见而失败，正常重试成功。一次MCP统计请求超过20秒验收限制，单独CLI统计计时24.15秒；相同20秒约束的协议重放通过。统计首用延迟尚无稳定分布，不能据重试成功宣称所有请求均在20秒内。当前可用版本以 [PyPI 官方元数据](https://pypi.org/pypi/jobsearchradar/json)为准。

历史验证：2026-11-02 从 PyPI 全新安装 `2.1.3`，七项兼容检查、MCP九工具与错误恢复、23个品牌及公告分类通过。该版本的GitHub/PyPI产物摘要及72个包内文件与固定标签一致；历史结果不代替新版本验收。

## 渠道与固定源码

| 渠道 | 版本与核验范围 | 用途 |
| :--- | :--- | :--- |
| PyPI `2.1.4` | 全新安装、7项CLI检查、九工具与错误恢复通过；统计延迟限制见上文 | 推荐安装 |
| PyPI `2.1.3` | 全新安装、7项CLI检查、MCP九工具与错误恢复通过 | 历史安装记录 |
| PyPI `2.1.2` | 已核实的历史发行包 | 历史安装记录 |
| PyPI `2.1.1` | 已核验的上一版发行包 | 历史安装记录 |
| GitHub `v2.1.4` | 固定发行标签，产物分别核对摘要 | 下载 wheel 或源码包 |
| 固定源码标签 | `v2.1.4`，代码版本 `2.1.4` | 发布后可复现的备用安装 |
| `2.0.1` | 历史补丁 | 最新一批缺失JD时可能误拒收合法更新，请升级至2.1.2；失败时旧数据保留 |
| `2.0.0` / `1.1.1` | 历史发行版 | 不包含本轮全部可靠性修正 |

备用源码安装不要求本机安装 Git。不同源码修订可能使用同一版本号，因此源码安装使用 `--force-reinstall`：

```bash
pip install --upgrade --force-reinstall "jobsearchradar[mcp] @ https://github.com/lijiaqi-AI-Product-Manager/job_radar/archive/v2.1.4.zip"
```

[PyPI 官方元数据](https://pypi.org/pypi/jobsearchradar/json)提供索引当前版本。
安装目标记录于 [install-target.json](install-target.json)。后续文档修改不会改变固定提交的内容。

## 安装后检查

`--version` 应显示 `2.1.4`；`search --help` 应正常退出，并列出 `--deadline-before`；
`calendar --help` 应列出 `--city` 和 `--include-expired`。参数不受支持或帮助报错时，
先核对终端与 MCP 使用的 Python 环境，再按上述命令升级，不要删除筛选条件。

维护者可用 `scripts/check_installed_cli.py --python <目标环境的 Python>` 执行 7 项离线兼容检查；
核对固定源码安装时另加 `--require-pinned-source`。脚本使用临时样本，不访问招聘网站，
确认导入来自目标环境的已安装包。发布 CI 同样验证构建出的 wheel。

数据另行下载：`jobradar update`。新版在 `JOBRADAR_HOME/snapshots/` 中验证整套三库后切换，
`doctor` 会显示实际 `data_dir`。快照下载成功不代表全部来源已刷新，需同时查看来源新鲜度。

发布流程与账号配置见 [发布配置](PUBLISHING.md)。
