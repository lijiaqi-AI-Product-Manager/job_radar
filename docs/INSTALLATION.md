# 安装与版本兼容

安装命令使用 `--force-reinstall`：不同源码修订可能使用同一版本号，仅加 `--upgrade` 会保留先前安装的代码。

当前功能指南固定到已验证的源码提交 `ebe2aba4e9c80f9cec93505599cde7ad12ddaac3`。
直接下载源码归档安装，不要求本机安装 Git：

```bash
pip install --upgrade --force-reinstall "jobsearchradar[mcp] @ https://github.com/lijiaqi-AI-Product-Manager/job_radar/archive/ebe2aba4e9c80f9cec93505599cde7ad12ddaac3.zip"
jobradar --version
jobradar search --help
jobradar calendar --help
```

已安装旧版时也执行同一条升级命令；请在运行 CLI 或 MCP 的那个 Python 环境中安装。
仅有 `jobradar` 命令存在不能证明包含最近的修正；本次安装后应显示 `2.0.1`，固定提交地址用于明确代码来源。

## 渠道区别

| 渠道 | 已核实状态（2026-11-01） | 用途 |
| :--- | :--- | :--- |
| PyPI | `2.0.0` 已发布，`2.0.1` 正在完成发布验收 | 补丁发布后以官方索引重新安装核验 |
| GitHub `v2.0.0` | 2.0 正式版安装包 | 发布时的固定版本，不包含发布之后的全部修正 |
| 上述固定源码提交 | 代码版本 `2.0.1`，含城市召回、正文验证、来源新鲜度与成套快照更新 | 本指南的默认安装目标 |

[PyPI 官方元数据](https://pypi.org/pypi/jobsearchradar/json)提供包索引当前版本。
固定提交记录维护于 [install-target.json](install-target.json)，当前仓库的后续文档修订不改变该提交的内容。

## 安装后检查

`search --help` 应正常退出，并列出 `--deadline-before`；`calendar --help` 应列出
`--city` 和 `--include-expired`。不支持参数或帮助命令报错时，先核对终端与 MCP 使用的 Python 环境，
按上面的固定地址升级，不要删除筛选条件来掩盖版本不匹配。

维护者可以用 `scripts/check_installed_cli.py --python <目标环境的 Python> --require-pinned-source`
执行 6 项离线兼容检查。脚本创建临时样本，不下载招聘快照、不访问招聘网站，
并确认导入来自目标环境中的已安装包。CI 也会检查构建出的 wheel 的帮助命令、筛选与简称映射。

需要配置 PyPI 发布渠道时，另见 [发布配置](PUBLISHING.md)。
