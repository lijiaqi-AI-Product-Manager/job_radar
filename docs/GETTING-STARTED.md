# 第一次使用

job_radar 为你的助手提供中国校招、实习、社招与招聘日历的本地查询工具。日常提问可以使用自然语言，首次需要安装工具、下载快照，并在支持 MCP 的客户端配置服务。

## 1. 安装并准备数据

需要 Python 3.11+，支持 Windows、macOS、Linux。在将运行服务的环境中执行：

```bash
python -m pip install --upgrade "jobsearchradar[mcp]==2.2.1"
jobradar update
jobradar doctor
```

`jobradar` 是安装后的命令，`jobsearchradar` 是发行包名。首次下载包含岗位、正文与日历三个数据库，体积随快照变化；需要留出下载文件和解压数据库的空间。默认从 GitHub 下载，下载失败会保留已通过验证的旧数据。当前其他渠道状态见[安装渠道](DISTRIBUTION.md)。

`doctor` 应能报告数据目录和快照时间。若提示找不到命令，请检查 Python 环境的可执行目录是否在 PATH 中，或使用该环境内可执行文件的完整路径。

## 2. 连接兼容助手

在客户端的 MCP 服务配置入口添加 stdio 服务。以下为常见的 JSON 结构；部分客户端使用不同的顶层键，请以其设置界面为准：

```json
{
  "mcpServers": {
    "jobradar": {
      "command": "jobradar-mcp"
    }
  }
}
```

保存并按客户端要求重新连接或重启服务。在工具列表中应能看到搜索、详情、日历和统计等9个工具。若客户端找不到命令，将 `command` 改为安装环境中 `jobradar-mcp`（Windows为 `jobradar-mcp.exe`）的绝对路径；JSON中的Windows反斜杠需写成 `\\`。

如下载数据时设置了 `JOBRADAR_HOME`，也要在服务的 `env` 中传入同一目录。助手与终端应使用同一安装环境和同一份数据。仅安装 MCP 不会自动下载快照。

## 3. 说出完整的需求

可以复制并修改：

> 帮我找苏州或无锡的2027届财务校招，排除上海。明确写了2027届的与届次没写的候选分开列，给出来源链接和数据时间。

> 我每周只能实习三天，持续两个月。请读岗位正文核实出勤和时长，不符合或没写明的单独说明。

> 查看招聘日历，把有完整起止日期的批次与日期不全的候选分开，不要把候选数量说成当前确定可投数量。

结果中的未知字段表示尚无明确数据，不能视为不限。薪资、远程、语言和实习安排等细节需要读原文核实。投递前打开来源链接，确认岗位、资格和截止时间。

## 日常使用

执行 `jobradar update` 获取新快照；已是最新时会跳过下载。下载后本地查询可离线运行，查阅原网站仍需联网。

终端使用者可直接运行：

```bash
jobradar search --cities 苏州 无锡 --exclude-city 上海 --category 财务 --type campus --limit 5 --table
jobradar calendar --grad-year 2027 --limit 5 --table
```

更详细的参数、缺失字段与条件核实见[个人条件查询](CANDIDATE-SEARCH.md)、[安装排错](INSTALLATION.md)和[常见问题](FAQ.md)。
