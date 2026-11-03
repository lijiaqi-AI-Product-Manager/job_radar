# 安装与版本兼容

需要 Python 3.11+。在实际运行 CLI 或 MCP 的 Python 环境中升级：

```bash
pip install --upgrade "jobsearchradar[mcp]==2.2.1"
jobradar --version
jobradar search --help
jobradar calendar --help
```

仅使用 CLI 可以安装 `jobsearchradar==2.2.1`。包名是 `jobsearchradar`，命令仍为 `jobradar` / `jobradar-mcp`。

2026-11-03已在独立环境从正式PyPI索引无缓存复装 `2.2.1`：7项CLI兼容检查、MCP九工具16次调用、15次CLI结果对照及错误恢复通过。72个包内运行文件与固定标签逐字节一致；GitHub与PyPI的wheel及源码包SHA-256一致。依赖沿用该独立环境中已验证的官方依赖。

历史验证：2026-11-03已从正式PyPI索引全新安装 `2.2.0`：7项CLI兼容检查、MCP九工具16次调用、15次CLI返回结果对照及标准错误恢复通过。72个包内运行文件与固定标签逐字节一致，23个公告品牌/分类和3个英文品牌映射通过；GitHub、CI与PyPI的wheel及源码包摘要一致。

正式安装的统计调用耗时4.35秒；候选阶段曾有一次请求超过20秒。独立重放通过不能证明冷启动或并发负载下全部请求低于20秒，来源字段与正文仍须分别核实。

全新三库下载19.86秒，全部来自GitHub；重复更新5.26秒，跳过三库且活动快照指针保持不变。数据截至2026-11-02T14:39:29Z；这些耗时只代表本次环境。

历史验证：2026-11-03正式安装2.1.4通过7项CLI检查与九工具；当时单次统计24.15秒，曾出现20秒超时。历史结果不代替新版本验收。

历史验证：2026-11-02 从 PyPI 全新安装 `2.1.3`，七项兼容检查、MCP九工具与错误恢复、23个品牌及公告分类通过。该版本的GitHub/PyPI产物摘要及72个包内文件与固定标签一致；历史结果不代替新版本验收。

## 渠道与固定源码

| 渠道 | 版本与核验范围 | 用途 |
| :--- | :--- | :--- |
| PyPI `2.2.1` | 正式索引无缓存复装、7项CLI检查、九工具16次调用及错误恢复通过 | 推荐安装 |
| PyPI `2.2.0` | 全新安装、7项CLI检查、九工具16次调用及错误恢复通过 | 历史安装记录 |
| PyPI `2.1.4` | 全新安装、7项CLI检查、九工具与错误恢复通过；统计延迟限制见上文 | 历史安装记录 |
| PyPI `2.1.3` | 全新安装、7项CLI检查、MCP九工具与错误恢复通过 | 历史安装记录 |
| PyPI `2.1.2` | 已核实的历史发行包 | 历史安装记录 |
| PyPI `2.1.1` | 已核验的上一版发行包 | 历史安装记录 |
| GitHub `v2.2.1` | 展示与安装入口修订的固定标签 | 下载 wheel 或源码包 |
| 固定源码标签 | `v2.2.1`，代码版本 `2.2.1` | 发布后可复现的备用安装 |
| `2.0.1` | 历史补丁 | 最新一批缺失JD时可能误拒收合法更新，请升级至2.1.2；失败时旧数据保留 |
| `2.0.0` / `1.1.1` | 历史发行版 | 不包含本轮全部可靠性修正 |

备用源码安装不要求本机安装 Git。不同源码修订可能使用同一版本号，因此源码安装使用 `--force-reinstall`：

```bash
pip install --upgrade --force-reinstall "jobsearchradar[mcp] @ https://github.com/lijiaqi-AI-Product-Manager/job_radar/archive/v2.2.1.zip"
```

[PyPI 官方元数据](https://pypi.org/pypi/jobsearchradar/json)提供索引当前版本。
安装目标记录于 [install-target.json](install-target.json)。后续文档修改不会改变固定提交的内容。

## 安装后检查

`--version` 应显示 `2.2.1`；`search --help` 应正常退出，并列出 `--deadline-before`；
`calendar --help` 应列出 `--city` 和 `--include-expired`。参数不受支持或帮助报错时，
先核对终端与 MCP 使用的 Python 环境，再按上述命令升级，不要删除筛选条件。

维护者可用 `scripts/check_installed_cli.py --python <目标环境的 Python>` 执行 7 项离线兼容检查；
核对固定源码安装时另加 `--require-pinned-source`。脚本使用临时样本，不访问招聘网站，
确认导入来自目标环境的已安装包。发布 CI 同样验证构建出的 wheel。

数据另行下载：`jobradar update`。新版在 `JOBRADAR_HOME/snapshots/` 中验证整套三库后切换，
`doctor` 会显示实际 `data_dir`。快照下载成功不代表全部来源已刷新，需同时查看来源新鲜度。

发布流程与账号配置见 [发布配置](PUBLISHING.md)。
