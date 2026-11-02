# 安装与版本兼容

需要 Python 3.11+。在实际运行 CLI 或 MCP 的 Python 环境中升级：

```bash
pip install --upgrade "jobsearchradar[mcp]==2.1.2"
jobradar --version
jobradar search --help
jobradar calendar --help
```

仅使用 CLI 可以安装 `jobsearchradar==2.1.2`。包名是 `jobsearchradar`，命令仍为 `jobradar` / `jobradar-mcp`。

2026-11-02 已从 PyPI 官方索引在全新环境安装 `2.1.2`，七项兼容检查、MCP 九工具协议、23 家新公司按品牌查询与公告分类均通过。
GitHub Release 与 PyPI 的 wheel / sdist 逐项 SHA-256 相同；安装包的 72 个代码、迁移与来源目录文件和 `v2.1.2` 标签逐字节一致，公司简称映射也一致。

## 渠道与固定源码

| 渠道 | 已核实状态（2026-11-02） | 用途 |
| :--- | :--- | :--- |
| PyPI `2.1.2` | 全新安装及7项兼容检查通过；MCP九工具、标准错误与恢复通过 | 推荐安装 |
| PyPI `2.1.1` | 已核验的上一版发行包 | 历史安装记录 |
| GitHub `v2.1.2` | 与 PyPI 使用相同发行文件 | 下载 wheel 或源码包 |
| 固定源码标签 | `v2.1.2`，代码版本 `2.1.2` | 发布后可复现的备用安装 |
| `2.0.1` | 历史补丁 | 最新一批缺失JD时可能误拒收合法更新，请升级至2.1.2；失败时旧数据保留 |
| `2.0.0` / `1.1.1` | 历史发行版 | 不包含本轮全部可靠性修正 |

备用源码安装不要求本机安装 Git。不同源码修订可能使用同一版本号，因此源码安装使用 `--force-reinstall`：

```bash
pip install --upgrade --force-reinstall "jobsearchradar[mcp] @ https://github.com/lijiaqi-AI-Product-Manager/job_radar/archive/v2.1.2.zip"
```

[PyPI 官方元数据](https://pypi.org/pypi/jobsearchradar/json)提供索引当前版本。
安装目标记录于 [install-target.json](install-target.json)。后续文档修改不会改变固定提交的内容。

## 安装后检查

`--version` 应显示 `2.1.2`；`search --help` 应正常退出，并列出 `--deadline-before`；
`calendar --help` 应列出 `--city` 和 `--include-expired`。参数不受支持或帮助报错时，
先核对终端与 MCP 使用的 Python 环境，再按上述命令升级，不要删除筛选条件。

维护者可用 `scripts/check_installed_cli.py --python <目标环境的 Python>` 执行 7 项离线兼容检查；
核对固定源码安装时另加 `--require-pinned-source`。脚本使用临时样本，不访问招聘网站，
确认导入来自目标环境的已安装包。发布 CI 同样验证构建出的 wheel。

数据另行下载：`jobradar update`。新版在 `JOBRADAR_HOME/snapshots/` 中验证整套三库后切换，
`doctor` 会显示实际 `data_dir`。快照下载成功不代表全部来源已刷新，需同时查看来源新鲜度。

发布流程与账号配置见 [发布配置](PUBLISHING.md)。
