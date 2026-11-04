# 首次接入：由助手准备查询能力

只在首次使用、连接失败或版本不兼容时阅读。本技能查询公开招聘信息，不需要简历、招聘账号或自动投递权限。

## 先检查所在环境

- 已连接 jobradar MCP：优先使用其工具，调用 `data_status` 检查数据；发现缺库或过旧时，在实际运行服务的环境更新。
- 支持技能和本地命令执行：检查 Python 3.11+、可用磁盘和下载网络，再在独立环境安装；遵守当前平台的安装与权限提示。
- 只能网页聊天、阅读附件，或只接受远程 MCP URL：说明当前模式缺少执行入口，引导用户查看[平台选择](https://github.com/lijiaqi-AI-Product-Manager/job_radar/blob/main/docs/PLATFORMS.md)。本项目没有运营中的公共 HTTP MCP 地址，不编造地址，也不把 GitHub 仓库链接当服务地址。

未实际调用成功前，不回答“已接入”。需要用户做界面操作时，只给当前这一步以及成功标志，不一次倾倒全部命令和配置。

## 安装并下载数据

在将实际运行查询的 Python 环境中执行：

```bash
python -m pip install --upgrade "jobsearchradar[mcp]==2.3.0"
jobradar --version
jobradar update
jobradar doctor
```

首次更新下载岗位、JD 正文和日历三库，体积随快照变化，检查足够的下载和解压空间。默认使用 GitHub；镜像当前状态见[安装渠道](https://github.com/lijiaqi-AI-Product-Manager/job_radar/blob/main/docs/DISTRIBUTION.md)。已有有效数据时，下载失败保留旧快照，但需说明旧数据时间。

有执行能力时由助手运行，再用自然语言解释结果。没有该能力时如实说明并提供兼容客户端的接入路径。

## 两种查询入口任选其一

**技能 + 本地工具：** 按 `SKILL.md` 调用 `jobradar`，读取 JSON；不必为此额外配置 MCP。

**本地 MCP：** 在客户端添加 stdio 服务。常见结构如下，实际字段以客户端官方设置为准：

```json
{
  "mcpServers": {
    "jobradar": {
      "command": "jobradar-mcp"
    }
  }
}
```

客户端找不到命令时，将 `command` 替换为安装环境中可执行文件的绝对路径；Windows JSON 路径的反斜杠写成 `\\`。自定义数据目录时，在服务 `env` 中设置同一 `JOBRADAR_HOME`。仅添加 MCP 不会自动下载数据。

## 确认可以使用

1. 读取数据状态，确认库存在，记录 `data_as_of`；过旧按技能规则处理。
2. 按用户原始条件实际查询少量候选；MCP 应能列出搜索、详情、日历等九个工具。
3. 回答候选、原始链接、数据时间与未知条件。没有结果也返回真实查询说明，不虚构成功样本。

之后用户可以直接说“换成深圳”“排除上海”“先看这周截止的”。保留未被修改的条件，精细资格需读原文，放宽后的候选单列。

安装故障与固定源码备用路径见[安装指南](https://github.com/lijiaqi-AI-Product-Manager/job_radar/blob/main/docs/INSTALLATION.md)。技能压缩包不含数据库，不能仅靠上传文件实现无工具查询。
