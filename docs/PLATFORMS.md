# 选择你常用的助手

**优先选择能导入技能、运行本地工具的 Agent 工作模式。** 把[首次接入请求](GETTING-STARTED.md)发给助手，由它检查环境并引导接入。求职时只需要说自己的条件。

Skill 可以理解为“助手的求职查询说明”，MCP 是“助手调用搜索工具的连接方式”。任选当前平台支持的一条路径即可，无需同时配置两套。单独导入说明文件不会自动提供数据或可执行工具。

## 各平台从哪里开始

下表依据平台官方资料整理，核对日期为 **2026-11-03**。平台能力会随客户端、版本、套餐和权限变化；有官方接入能力，不代表本项目已在每个客户端完成全流程验证。

| 平台或工作模式 | 建议路径 | 当前需要注意 |
| :--- | :--- | :--- |
| **WorkBuddy** | 优先导入 `jobradar-skill.zip` 或 `skill/jobradar`，让助手准备本地工具和数据；也可使用本地 MCP | 官方支持 Skill、MCP 与 CLI 技能连接器。本项目未声明已经上架其商店。见[插件说明](https://www.codebuddy.cn/docs/workbuddy/Plugins)、[连接器说明](https://open.workbuddy.cn/docs/connector)及[技能导入示例](https://docs.rag.bailian.aliyun.com/cookbook/office-agent)。 |
| **千问办公** | 可先发送仓库技能安装请求；也可从“扩展 → 技能”导入压缩包 | 官方示例支持对话安装和界面上传，需能访问仓库并运行 Python。见[官方技能接入示例](https://docs.rag.bailian.aliyun.com/cookbook/office-agent)。 |
| **Kimi 的本地 Agent 模式** | 在支持技能和本地命令执行的客户端加载技能，或添加 MCP | 官方本地 Agent 文档列有技能与 MCP；不能据此推断普通 Kimi 网页对话能执行本地工具。见[Kimi 官方文档](https://moonshotai.github.io/kimi-code/zh/)。 |
| **Claude Desktop** | 安装查询工具、下载数据后，添加本地 MCP 服务；技能路径以客户端支持情况为准 | 本地 MCP 与网页端远程连接器是不同机制。见[本地 MCP 说明](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop)、[远程连接器说明](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)。 |
| **ChatGPT 桌面端 / Work** | 官方桌面端提供本地 MCP 设置时，可添加 stdio 服务；使用本地工具的工作模式也可按技能路径准备。仅有网页端远程连接入口时需另行托管服务 | 本项目提供本地 stdio 服务，尚无本项目运营的公共 HTTP 服务地址。不能把仓库链接填成 MCP 服务地址。见[官方 MCP 接入说明](https://learn.chatgpt.com/docs/extend/mcp)、[自定义服务器说明](https://developers.openai.com/api/docs/guides/custom-mcp-server)。 |
| **扣子** | 如使用能运行本地 Python 的 Agent 环境，可按技能路径检查接入；仅使用 MCP 页面时需另行提供远程服务 | 官方 MCP 页面明确支持 Streamable HTTP / SSE、暂不支持 stdio。当前本地配置不能直接粘贴到该远程入口。见[官方 MCP 说明](https://docs.coze.cn/mcp)。 |
| **智谱清言** | 先让当前客户端检查是否开放自定义技能、本地执行或兼容 MCP；不满足时换用上面的兼容工作模式 | 当前未取得足以确认本项目直接接入方式的官方说明，也未完成该客户端全流程验证，暂不列为已支持。模型本身能对话，不等于所在平台能加载工具。 |
| **其他 Agent 平台** | 能执行 Python 的技能模式，或能启动本地 stdio MCP 的模式 | 不按模型品牌判断，按实际工具能力判断。远程托管、桥接及其运维不包含在当前安装包里。 |

## 导入技能

在[当前代码 Release](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/latest)下载 **`jobradar-skill.zip`**。支持上传技能的平台，选择“添加技能 / 导入技能”，按界面上传；需要目录时先解压，选择含 `SKILL.md` 的文件夹。也可直接从本仓库取出 `skill/jobradar` 目录。

技能包含查询工作流、字段说明和接入步骤，不包含数据库。导入后仍需具备 Python 3.11+、安装包与数据下载能力；让助手按照包内 `references/setup.md` 完成准备。安装不要求上传简历，也不提供自动代投。

完整环境检查、安装、数据准备与 MCP JSON 见[安装指南](INSTALLATION.md)。当前验证覆盖查询工具、CLI 与标准 MCP 协议，本文不把文档能力核对写成客户端实测。
